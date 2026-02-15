import logging
from copy import deepcopy
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

            if product.status == "archived":
                return {"error": f"Product {product_id} is archived — unarchive it first"}

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
                .join(Product, PlatformListing.product_id == Product.id)
                .filter(PlatformListing.status == status)
                .filter(Product.status != "archived")
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

    def revise_draft(self, listing_id: int, reason: str = "") -> dict:
        """Move an approved listing back to draft status for editing."""
        with Session(self.engine) as session:
            listing = session.get(PlatformListing, listing_id)
            if listing is None:
                return {"error": f"Listing {listing_id} not found"}
            if listing.status != "approved":
                return {
                    "error": f"Cannot revise listing with status '{listing.status}', "
                    "must be 'approved'"
                }
            listing.status = "draft"
            log_action(
                session,
                "listing",
                "revise_draft",
                {"listing_id": listing.id, "reason": reason},
                product_id=listing.product_id,
            )
            session.commit()
            return {"listing_id": listing.id, "status": "draft", "reason": reason}

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

            logger.info(
                "Published listing %s to Tradera (item_id=%s)",
                listing.id,
                external_id,
                extra={"listing_id": listing.id},
            )

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
        """Create listing on Tradera, upload images, and commit."""
        duration = listing.duration_days or 7
        details = listing.details or {}
        shipping_options = details.get("shipping_options")
        shipping_condition = details.get("shipping_condition")
        shipping_cost = None if shipping_options else details.get("shipping_cost")
        reserve_price = details.get("reserve_price") if listing.listing_type == "auction" else None

        create_result = self.tradera.create_listing(
            title=listing.listing_title,
            description=listing.listing_description,
            category_id=listing.tradera_category_id,
            duration_days=duration,
            listing_type=listing.listing_type,
            start_price=listing.start_price,
            buy_it_now_price=listing.buy_it_now_price,
            reserve_price=reserve_price,
            shipping_cost=shipping_cost,
            shipping_options=shipping_options,
            shipping_condition=shipping_condition,
            auto_commit=False,
        )

        if "error" in create_result:
            return create_result

        request_id = create_result.get("request_id")
        if request_id is None:
            return {"error": "Tradera API response missing RequestId, cannot commit listing"}

        # Image upload is non-fatal -- we still commit the listing
        upload_result = self.tradera.upload_images(
            request_id=request_id,
            images=encoded_images,
        )
        if "error" in upload_result:
            logger.warning(
                "Image upload failed for listing %s: %s",
                listing.id,
                upload_result["error"],
            )

        # Commit the listing (required when AutoCommit=False)
        commit_result = self.tradera.commit_listing(request_id)
        if "error" in commit_result:
            return {
                "error": f"Listing created (item_id={create_result['item_id']}) "
                f"but commit failed: {commit_result['error']}"
            }

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

    def search_products(
        self,
        query: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
    ) -> dict:
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
            elif not include_archived:
                q = q.filter(Product.status != "archived")

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

    _MISSING = object()

    def update_product(
        self,
        product_id: int,
        title: str | None = _MISSING,
        description: str | None = _MISSING,
        category: str | None = _MISSING,
        condition: str | None = _MISSING,
        materials: str | None = _MISSING,
        era: str | None = _MISSING,
        dimensions: str | None = _MISSING,
        source: str | None = _MISSING,
        acquisition_cost: float | None = _MISSING,
        weight_grams: int | None = _MISSING,
    ) -> dict:
        """Update fields on an existing product. Pass None to clear a field."""
        updatable = {
            "title",
            "description",
            "category",
            "condition",
            "materials",
            "era",
            "dimensions",
            "source",
            "acquisition_cost",
            "weight_grams",
        }
        updates = {k: v for k, v in locals().items() if k in updatable and v is not self._MISSING}

        if acquisition_cost is not self._MISSING and acquisition_cost is not None:
            if acquisition_cost < 0:
                return {"error": "acquisition_cost must be >= 0"}
        if weight_grams is not self._MISSING and weight_grams is not None:
            if weight_grams <= 0:
                return {"error": "weight_grams must be > 0"}

        with Session(self.engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                return {"error": f"Product {product_id} not found"}

            if not updates:
                return {
                    "product_id": product.id,
                    "title": product.title,
                    "status": product.status,
                    "updated_fields": [],
                }

            for key, value in updates.items():
                setattr(product, key, value)

            log_action(
                session,
                "listing",
                "update_product",
                {"updated_fields": list(updates.keys())},
                product_id=product_id,
            )
            session.commit()

            return {
                "product_id": product.id,
                "title": product.title,
                "status": product.status,
                "updated_fields": list(updates.keys()),
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

    def get_product_images(
        self,
        product_id: int | None = None,
        listing_id: int | None = None,
    ) -> dict:
        """Get product images for review. Accepts product_id or listing_id (resolves to product)."""
        from pathlib import Path

        if product_id is None and listing_id is None:
            return {"error": "Either product_id or listing_id is required"}

        with Session(self.engine) as session:
            if listing_id is not None and product_id is None:
                listing = session.get(PlatformListing, listing_id)
                if listing is None:
                    return {"error": f"Listing {listing_id} not found"}
                product_id = listing.product_id

            product = session.get(Product, product_id)
            if product is None:
                return {"error": f"Product {product_id} not found"}

            images = (
                session.query(ProductImage)
                .filter_by(product_id=product_id)
                .order_by(ProductImage.is_primary.desc(), ProductImage.id)
                .all()
            )

            if not images:
                return {
                    "product_id": product_id,
                    "product_title": product.title,
                    "image_count": 0,
                    "images": [],
                    "_display_images": [],
                }

            image_list = []
            display_images = []
            for i, img in enumerate(images):
                image_list.append(
                    {
                        "id": img.id,
                        "file_path": img.file_path,
                        "is_primary": img.is_primary,
                    }
                )
                if Path(img.file_path).exists():
                    label = "huvudbild" if img.is_primary else f"bild {i + 1}"
                    caption = f"Bild {i + 1} av {len(images)} ({label}) — {product.title}"
                    display_images.append({"path": img.file_path, "caption": caption})

            return {
                "product_id": product_id,
                "product_title": product.title,
                "image_count": len(images),
                "images": image_list,
                "_display_images": display_images,
            }

    def archive_product(self, product_id: int) -> dict:
        """Archive a product, hiding it from normal views."""
        with Session(self.engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                return {"error": f"Product {product_id} not found"}

            if product.status == "archived":
                return {"error": f"Product {product_id} is already archived"}

            active_count = (
                session.query(PlatformListing)
                .filter_by(product_id=product_id, status="active")
                .count()
            )
            if active_count:
                return {
                    "error": f"Cannot archive product {product_id}: "
                    f"it has {active_count} active listing(s)"
                }

            product.previous_status = product.status
            product.status = "archived"

            log_action(
                session,
                "listing",
                "archive_product",
                {"previous_status": product.previous_status},
                product_id=product_id,
            )
            session.commit()

            return {
                "product_id": product_id,
                "status": "archived",
                "previous_status": product.previous_status,
            }

    def unarchive_product(self, product_id: int) -> dict:
        """Restore an archived product to its previous status."""
        with Session(self.engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                return {"error": f"Product {product_id} not found"}

            if product.status != "archived":
                return {
                    "error": f"Product {product_id} is not archived (status: {product.status})"
                }

            restored_status = product.previous_status or "draft"
            product.status = restored_status
            product.previous_status = None

            log_action(
                session,
                "listing",
                "unarchive_product",
                {"restored_status": restored_status},
                product_id=product_id,
            )
            session.commit()

            return {
                "product_id": product_id,
                "status": restored_status,
            }

    def get_product(self, product_id: int) -> dict:
        """Get full details for a single product including image and listing counts."""
        with Session(self.engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                return {"error": f"Product {product_id} not found"}

            image_count = session.query(ProductImage).filter_by(product_id=product_id).count()
            active_listing_count = (
                session.query(PlatformListing)
                .filter_by(product_id=product_id, status="active")
                .count()
            )

            return {
                "product_id": product.id,
                "title": product.title,
                "description": product.description,
                "category": product.category,
                "status": product.status,
                "acquisition_cost": product.acquisition_cost,
                "listing_price": product.listing_price,
                "sold_price": product.sold_price,
                "source": product.source,
                "condition": product.condition,
                "dimensions": product.dimensions,
                "weight_grams": product.weight_grams,
                "materials": product.materials,
                "era": product.era,
                "image_count": image_count,
                "active_listing_count": active_listing_count,
                "created_at": product.created_at.isoformat() if product.created_at else None,
                "updated_at": product.updated_at.isoformat() if product.updated_at else None,
            }

    def relist_product(
        self,
        listing_id: int,
        listing_title: str | None = None,
        listing_description: str | None = None,
        listing_type: str | None = None,
        start_price: float | None = None,
        buy_it_now_price: float | None = None,
        duration_days: int | None = None,
        tradera_category_id: int | None = None,
        details: dict | None = None,
    ) -> dict:
        """Create a new draft listing by copying from an ended or sold listing."""
        with Session(self.engine) as session:
            source = session.get(PlatformListing, listing_id)
            if source is None:
                return {"error": f"Listing {listing_id} not found"}

            if source.status not in ("ended", "sold"):
                return {
                    "error": f"Cannot relist listing with status '{source.status}', "
                    "must be 'ended' or 'sold'"
                }

            product = session.get(Product, source.product_id)
            if product and product.status == "archived":
                return {"error": f"Product {source.product_id} is archived — unarchive it first"}

            new_type = listing_type or source.listing_type
            new_start = start_price if start_price is not None else source.start_price
            new_bin = buy_it_now_price if buy_it_now_price is not None else source.buy_it_now_price
            new_duration = duration_days if duration_days is not None else source.duration_days

            errors = _validate_draft(
                listing_type=new_type,
                start_price=new_start,
                buy_it_now_price=new_bin,
                duration_days=new_duration,
            )
            if errors:
                return {"error": "Validation failed", "details": errors}

            listing = PlatformListing(
                product_id=source.product_id,
                platform=source.platform,
                status="draft",
                listing_type=new_type,
                listing_title=listing_title or source.listing_title,
                listing_description=listing_description or source.listing_description,
                start_price=new_start,
                buy_it_now_price=new_bin,
                duration_days=new_duration,
                tradera_category_id=(
                    tradera_category_id
                    if tradera_category_id is not None
                    else source.tradera_category_id
                ),
                details=details if details is not None else deepcopy(source.details),
            )
            session.add(listing)
            session.flush()

            if product and product.status in ("sold", "listed"):
                other_active = (
                    session.query(PlatformListing)
                    .filter(
                        PlatformListing.product_id == source.product_id,
                        PlatformListing.status == "active",
                    )
                    .count()
                )
                if other_active == 0:
                    product.status = "draft"

            log_action(
                session,
                "listing",
                "relist_product",
                {"new_listing_id": listing.id, "source_listing_id": listing_id},
                product_id=source.product_id,
                requires_approval=True,
            )
            session.commit()

            preview = _format_draft_preview(listing, product)
            return {
                "listing_id": listing.id,
                "source_listing_id": listing_id,
                "status": "draft",
                "preview": preview,
            }

    def delete_product_image(self, image_id: int) -> dict:
        """Delete a product image record and its file."""
        from pathlib import Path

        with Session(self.engine) as session:
            image = session.get(ProductImage, image_id)
            if image is None:
                return {"error": f"Image {image_id} not found"}

            product_id = image.product_id
            file_path = image.file_path
            was_primary = image.is_primary

            session.delete(image)
            session.flush()

            if was_primary:
                next_image = (
                    session.query(ProductImage)
                    .filter_by(product_id=product_id)
                    .order_by(ProductImage.id)
                    .first()
                )
                if next_image:
                    next_image.is_primary = True

            log_action(
                session,
                "listing",
                "delete_product_image",
                {"image_id": image_id, "file_path": file_path, "was_primary": was_primary},
                product_id=product_id,
            )
            session.commit()

        if file_path:
            try:
                Path(file_path).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to delete image file %s: %s", file_path, exc)

        return {
            "image_id": image_id,
            "product_id": product_id,
            "deleted_file": file_path,
        }

    def cancel_listing(self, listing_id: int) -> dict:
        """Cancel an active listing locally. Tradera has no cancel API."""
        with Session(self.engine) as session:
            listing = session.get(PlatformListing, listing_id)
            if listing is None:
                return {"error": f"Listing {listing_id} not found"}

            if listing.status != "active":
                return {
                    "error": f"Cannot cancel listing with status '{listing.status}', "
                    "must be 'active'"
                }

            listing.status = "cancelled"

            other_active = (
                session.query(PlatformListing)
                .filter(
                    PlatformListing.product_id == listing.product_id,
                    PlatformListing.id != listing_id,
                    PlatformListing.status == "active",
                )
                .count()
            )

            product = session.get(Product, listing.product_id)
            if product and other_active == 0 and product.status == "listed":
                product.status = "draft"

            log_action(
                session,
                "listing",
                "cancel_listing",
                {
                    "listing_id": listing_id,
                    "note": "Local cancel only — Tradera listing may still be active on platform",
                },
                product_id=listing.product_id,
            )
            session.commit()

            return {
                "listing_id": listing_id,
                "status": "cancelled",
                "product_status": product.status if product else None,
                "warning": "Annulleringen gäller bara lokalt. "
                "Tradera har inget API för att avbryta en pågående annons — "
                "gör det manuellt på Tradera om det behövs.",
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
