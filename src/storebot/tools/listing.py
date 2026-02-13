import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from storebot.db import PlatformListing, Product, ProductImage
from storebot.tools.helpers import log_action
from storebot.tools.image import encode_image_base64, optimize_for_upload

logger = logging.getLogger(__name__)

VALID_LISTING_TYPES = {"auction", "buy_it_now"}
VALID_DURATION_DAYS = {3, 5, 7, 10, 14}


class ListingService:
    """Compound tool for managing draft listings with human-in-the-loop approval.

    All listings start as drafts and require explicit approval before
    they can be published to a marketplace.
    """

    def __init__(self, engine, tradera=None):
        self.engine = engine
        self.tradera = tradera

    def create_draft(
        self,
        product_id: int,
        listing_type: str,
        listing_title: str,
        listing_description: str,
        platform: str = "tradera",
        start_price: float | None = None,
        buy_it_now_price: float | None = None,
        duration_days: int = 7,
        tradera_category_id: int | None = None,
        details: dict | None = None,
    ) -> dict:
        """Create a draft listing for a product. Requires approval before publishing."""
        with Session(self.engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                return {"error": f"Product {product_id} not found"}

            errors = _validate_draft(
                listing_type=listing_type,
                start_price=start_price,
                buy_it_now_price=buy_it_now_price,
                duration_days=duration_days,
            )
            if errors:
                return {"error": "Validation failed", "details": errors}

            listing = PlatformListing(
                product_id=product_id,
                platform=platform,
                status="draft",
                listing_type=listing_type,
                listing_title=listing_title,
                listing_description=listing_description,
                start_price=start_price,
                buy_it_now_price=buy_it_now_price,
                duration_days=duration_days,
                tradera_category_id=tradera_category_id,
                details=details,
            )
            session.add(listing)
            session.flush()

            log_action(
                session,
                "listing",
                "create_draft",
                {"listing_id": listing.id, "listing_type": listing_type},
                product_id=product_id,
                requires_approval=True,
            )
            session.commit()

            preview = _format_draft_preview(listing, product)
            return {"listing_id": listing.id, "status": "draft", "preview": preview}

    def list_drafts(self, status: str = "draft") -> dict:
        """List listings filtered by status."""
        with Session(self.engine) as session:
            listings = (
                session.query(PlatformListing)
                .filter(PlatformListing.status == status)
                .order_by(PlatformListing.created_at.desc())
                .all()
            )
            return {
                "count": len(listings),
                "listings": [
                    {
                        "id": listing.id,
                        "product_id": listing.product_id,
                        "listing_title": listing.listing_title,
                        "listing_type": listing.listing_type,
                        "platform": listing.platform,
                        "status": listing.status,
                        "start_price": listing.start_price,
                        "buy_it_now_price": listing.buy_it_now_price,
                    }
                    for listing in listings
                ],
            }

    def get_draft(self, listing_id: int) -> dict:
        """Get full details for a single listing."""
        with Session(self.engine) as session:
            listing = session.get(PlatformListing, listing_id)
            if listing is None:
                return {"error": f"Listing {listing_id} not found"}

            product = session.get(Product, listing.product_id)
            return {
                "id": listing.id,
                "product_id": listing.product_id,
                "product_title": product.title if product else None,
                "platform": listing.platform,
                "status": listing.status,
                "listing_type": listing.listing_type,
                "listing_title": listing.listing_title,
                "listing_description": listing.listing_description,
                "start_price": listing.start_price,
                "buy_it_now_price": listing.buy_it_now_price,
                "duration_days": listing.duration_days,
                "tradera_category_id": listing.tradera_category_id,
                "details": listing.details,
                "created_at": listing.created_at.isoformat() if listing.created_at else None,
            }

    def update_draft(self, listing_id: int, **fields) -> dict:
        """Update allowed fields on a draft listing."""
        with Session(self.engine) as session:
            listing = session.get(PlatformListing, listing_id)
            if listing is None:
                return {"error": f"Listing {listing_id} not found"}

            if listing.status != "draft":
                return {
                    "error": f"Cannot edit listing with status '{listing.status}', only drafts"
                }

            allowed = {
                "listing_title",
                "listing_description",
                "listing_type",
                "start_price",
                "buy_it_now_price",
                "duration_days",
                "tradera_category_id",
                "details",
                "platform",
            }
            unknown = set(fields) - allowed
            if unknown:
                return {"error": f"Unknown fields: {', '.join(sorted(unknown))}"}

            for key, value in fields.items():
                setattr(listing, key, value)

            errors = _validate_draft(
                listing_type=listing.listing_type,
                start_price=listing.start_price,
                buy_it_now_price=listing.buy_it_now_price,
                duration_days=listing.duration_days,
            )
            if errors:
                session.rollback()
                return {"error": "Validation failed", "details": errors}

            log_action(
                session,
                "listing",
                "update_draft",
                {"listing_id": listing.id, "updated_fields": list(fields.keys())},
                product_id=listing.product_id,
            )
            session.commit()

            product = session.get(Product, listing.product_id)
            preview = _format_draft_preview(listing, product)
            return {"listing_id": listing.id, "status": "draft", "preview": preview}

    def approve_draft(self, listing_id: int) -> dict:
        """Approve a draft listing, moving it to 'approved' status."""
        with Session(self.engine) as session:
            listing = session.get(PlatformListing, listing_id)
            if listing is None:
                return {"error": f"Listing {listing_id} not found"}

            if listing.status != "draft":
                return {"error": f"Cannot approve listing with status '{listing.status}'"}

            listing.status = "approved"
            now = datetime.now(UTC)

            log_action(
                session,
                "listing",
                "approve_draft",
                {"listing_id": listing.id},
                product_id=listing.product_id,
                approved_at=now,
            )
            session.commit()

            return {"listing_id": listing.id, "status": "approved"}

    def publish_listing(self, listing_id: int) -> dict:
        """Publish an approved listing to Tradera. Uploads images and creates the listing."""
        if not self.tradera:
            return {"error": "Tradera client not configured"}

        with Session(self.engine) as session:
            error = self._validate_for_publish(session, listing_id)
            if error:
                return error
            listing = session.get(PlatformListing, listing_id)

            encoded_images = self._prepare_images(session, listing.product_id)
            if isinstance(encoded_images, dict):
                return encoded_images  # error dict

            create_result = self._create_tradera_listing(listing, encoded_images)
            if "error" in create_result:
                return {"error": f"Tradera API error: {create_result['error']}"}

            external_id = str(create_result["item_id"])
            listing_url = create_result["url"]
            duration = listing.duration_days or 7

            now = datetime.now(UTC)
            ends_at = now + timedelta(days=duration)
            listing.external_id = external_id
            listing.listing_url = listing_url
            listing.listed_at = now
            listing.ends_at = ends_at
            listing.status = "active"

            product = session.get(Product, listing.product_id)
            if product:
                product.status = "listed"
                price = listing.buy_it_now_price or listing.start_price
                if price:
                    product.listing_price = price

            log_action(
                session,
                "listing",
                "publish_listing",
                {"listing_id": listing.id, "external_id": external_id, "url": listing_url},
                product_id=listing.product_id,
            )
            session.commit()

            return {
                "listing_id": listing.id,
                "external_id": external_id,
                "url": listing_url,
                "status": "active",
                "listed_at": now.isoformat(),
                "ends_at": ends_at.isoformat(),
            }

    @staticmethod
    def _validate_for_publish(session: Session, listing_id: int) -> dict | None:
        """Validate that a listing is ready for publishing. Returns error dict or None."""
        listing = session.get(PlatformListing, listing_id)
        if listing is None:
            return {"error": f"Listing {listing_id} not found"}
        if listing.status != "approved":
            return {
                "error": f"Cannot publish listing with status '{listing.status}', must be 'approved'"
            }
        if listing.platform != "tradera":
            return {
                "error": f"Cannot publish to platform '{listing.platform}', only 'tradera' supported"
            }
        if not listing.tradera_category_id:
            return {"error": "Listing must have a tradera_category_id to publish"}
        return None

    @staticmethod
    def _prepare_images(session: Session, product_id: int) -> list[tuple] | dict:
        """Load, optimize, and encode product images. Returns encoded images or error dict."""
        images = (
            session.query(ProductImage)
            .filter_by(product_id=product_id)
            .order_by(ProductImage.is_primary.desc(), ProductImage.id)
            .all()
        )
        if not images:
            return {"error": "Product has no images, at least one image is required to publish"}
        return [encode_image_base64(optimize_for_upload(img.file_path)) for img in images]

    def _create_tradera_listing(self, listing: PlatformListing, encoded_images: list) -> dict:
        """Create listing on Tradera and upload images."""
        duration = listing.duration_days or 7
        details = listing.details or {}
        shipping_options = details.get("shipping_options")
        shipping_condition = details.get("shipping_condition")
        shipping_cost = None if shipping_options else details.get("shipping_cost")

        create_result = self.tradera.create_listing(
            title=listing.listing_title,
            description=listing.listing_description,
            category_id=listing.tradera_category_id,
            duration_days=duration,
            listing_type=listing.listing_type,
            start_price=listing.start_price,
            buy_it_now_price=listing.buy_it_now_price,
            shipping_cost=shipping_cost,
            shipping_options=shipping_options,
            shipping_condition=shipping_condition,
        )

        if "error" in create_result:
            return create_result

        # Image upload is non-fatal -- listing is already created on Tradera
        upload_result = self.tradera.upload_images(
            item_id=int(create_result["item_id"]),
            images=encoded_images,
        )
        if "error" in upload_result:
            logger.warning(
                "Image upload failed for listing %s: %s",
                listing.id,
                upload_result["error"],
            )

        return create_result

    def reject_draft(self, listing_id: int, reason: str = "") -> dict:
        """Reject and delete a draft listing."""
        with Session(self.engine) as session:
            listing = session.get(PlatformListing, listing_id)
            if listing is None:
                return {"error": f"Listing {listing_id} not found"}

            if listing.status != "draft":
                return {"error": f"Cannot reject listing with status '{listing.status}'"}

            product_id = listing.product_id
            session.delete(listing)

            log_action(
                session,
                "listing",
                "reject_draft",
                {"listing_id": listing_id, "reason": reason},
                product_id=product_id,
            )
            session.commit()

            return {"listing_id": listing_id, "status": "rejected", "reason": reason}

    def search_products(self, query: str | None = None, status: str | None = None) -> dict:
        """Search the local product database."""
        with Session(self.engine) as session:
            q = session.query(Product)

            if query:
                pattern = f"%{query}%"
                q = q.filter(
                    or_(
                        Product.title.ilike(pattern),
                        Product.description.ilike(pattern),
                        Product.category.ilike(pattern),
                    )
                )

            if status:
                q = q.filter(Product.status == status)

            products = q.order_by(Product.created_at.desc()).all()

            return {
                "count": len(products),
                "products": [
                    {
                        "id": p.id,
                        "title": p.title,
                        "category": p.category,
                        "status": p.status,
                        "acquisition_cost": p.acquisition_cost,
                        "listing_price": p.listing_price,
                        "condition": p.condition,
                        "era": p.era,
                    }
                    for p in products
                ],
            }

    def create_product(
        self,
        title: str,
        description: str | None = None,
        category: str | None = None,
        status: str = "draft",
        condition: str | None = None,
        materials: str | None = None,
        era: str | None = None,
        dimensions: str | None = None,
        source: str | None = None,
        acquisition_cost: float | None = None,
        weight_grams: int | None = None,
    ) -> dict:
        """Create a new product in the database."""
        with Session(self.engine) as session:
            product = Product(
                title=title,
                description=description,
                category=category,
                status=status,
                condition=condition,
                materials=materials,
                era=era,
                dimensions=dimensions,
                source=source,
                acquisition_cost=acquisition_cost,
                weight_grams=weight_grams,
            )
            session.add(product)
            session.flush()

            log_action(
                session,
                "listing",
                "create_product",
                {"title": title},
                product_id=product.id,
            )
            session.commit()

            return {
                "product_id": product.id,
                "title": product.title,
                "status": product.status,
            }

    def save_product_image(
        self,
        product_id: int,
        image_path: str,
        is_primary: bool = False,
    ) -> dict:
        """Save an image record for a product."""
        from pathlib import Path

        if not Path(image_path).exists():
            return {"error": f"File not found: {image_path}"}

        with Session(self.engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                return {"error": f"Product {product_id} not found"}

            if is_primary:
                session.query(ProductImage).filter_by(
                    product_id=product_id, is_primary=True
                ).update({"is_primary": False})

            img = ProductImage(
                product_id=product_id,
                file_path=image_path,
                is_primary=is_primary,
            )
            session.add(img)
            session.flush()

            total = session.query(ProductImage).filter_by(product_id=product_id).count()

            log_action(
                session,
                "listing",
                "save_product_image",
                {"image_id": img.id, "file_path": image_path, "is_primary": is_primary},
                product_id=product_id,
            )
            session.commit()

            return {
                "image_id": img.id,
                "product_id": product_id,
                "file_path": image_path,
                "is_primary": is_primary,
                "total_images": total,
            }


def _validate_draft(
    listing_type: str,
    start_price: float | None,
    buy_it_now_price: float | None,
    duration_days: int | None,
) -> list[str]:
    """Validate draft listing fields. Returns list of error messages (empty = valid)."""
    errors = []

    if listing_type not in VALID_LISTING_TYPES:
        errors.append(f"listing_type must be one of: {', '.join(sorted(VALID_LISTING_TYPES))}")

    if listing_type == "auction":
        if start_price is None or start_price <= 0:
            errors.append("Auctions require a positive start_price")

    if listing_type == "buy_it_now":
        if buy_it_now_price is None or buy_it_now_price <= 0:
            errors.append("Buy-it-now listings require a positive buy_it_now_price")

    if duration_days is not None and duration_days not in VALID_DURATION_DAYS:
        errors.append(f"duration_days must be one of: {sorted(VALID_DURATION_DAYS)}")

    return errors


def _format_draft_preview(listing: PlatformListing, product: Product | None) -> str:
    """Format a human-readable preview of a draft listing."""
    lines = [
        f"📦 Produkt: {product.title if product else 'Okänd'} (#{listing.product_id})",
        f"📝 Titel: {listing.listing_title}",
        f"📋 Beskrivning: {listing.listing_description}",
        f"🏷️ Typ: {listing.listing_type}",
        f"🌐 Plattform: {listing.platform}",
    ]

    if listing.listing_type == "auction":
        lines.append(f"💰 Startpris: {listing.start_price} kr")
        if listing.buy_it_now_price:
            lines.append(f"🛒 Köp nu-pris: {listing.buy_it_now_price} kr")
    else:
        lines.append(f"🛒 Pris: {listing.buy_it_now_price} kr")

    lines.append(f"⏱️ Varaktighet: {listing.duration_days} dagar")

    if listing.tradera_category_id:
        lines.append(f"📂 Tradera-kategori: {listing.tradera_category_id}")

    if listing.details:
        opts = listing.details.get("shipping_options")
        if opts:
            lines.append(f"📦 Fraktalternativ: {len(opts)} st")
            for opt in opts:
                lines.append(f"  - {opt.get('name', 'Okänt')}: {opt.get('cost', '?')} kr")
        elif listing.details.get("shipping_cost") is not None:
            lines.append(f"📦 Fraktkostnad: {listing.details['shipping_cost']} kr")
        cond = listing.details.get("shipping_condition")
        if cond:
            lines.append(f"📋 Leveransvillkor: {cond}")

    return "\n".join(lines)
