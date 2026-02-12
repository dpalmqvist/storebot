import base64
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from storebot.db import AgentAction, Notification, Order, PlatformListing, Product
from storebot.tools.postnord import PostNordError, parse_buyer_address

logger = logging.getLogger(__name__)


class OrderService:
    """Manages orders: detection, voucher creation, shipping coordination.

    Polls Tradera for new sales, creates local order records, handles
    accounting vouchers, and coordinates shipping.
    """

    def __init__(
        self, engine, tradera=None, accounting=None, postnord=None, label_export_path="data/labels"
    ):
        self.engine = engine
        self.tradera = tradera
        self.accounting = accounting
        self.postnord = postnord
        self.label_export_path = label_export_path

    def check_new_orders(self) -> dict:
        """Poll Tradera for new orders and import them locally."""
        if not self.tradera:
            return {"error": "Tradera client not available"}

        result = self.tradera.get_orders()
        if "error" in result:
            return result

        new_orders = []
        with Session(self.engine) as session:
            for order_data in result.get("orders", []):
                ext_id = str(order_data["order_id"])

                existing = session.query(Order).filter(Order.external_order_id == ext_id).first()
                if existing:
                    continue

                # Match Tradera items to local listings
                product_id = None
                sale_price = order_data.get("sub_total", 0)
                for item in order_data.get("items", []):
                    item_id = str(item.get("item_id", ""))
                    listing = (
                        session.query(PlatformListing)
                        .filter(
                            PlatformListing.external_id == item_id,
                            PlatformListing.platform == "tradera",
                        )
                        .first()
                    )
                    if listing:
                        product_id = listing.product_id
                        listing.status = "sold"
                        product = session.get(Product, listing.product_id)
                        if product:
                            product.status = "sold"
                            product.sold_price = sale_price
                        break

                if product_id is None:
                    # Unmatched order — log but still create record
                    logger.warning("No local listing found for Tradera order %s", ext_id)
                    # We need a product_id for the FK — skip unmatched orders
                    action = AgentAction(
                        agent_name="order",
                        action_type="unmatched_order",
                        details={
                            "external_order_id": ext_id,
                            "buyer_name": order_data.get("buyer_name"),
                            "items": order_data.get("items", []),
                        },
                        executed_at=datetime.now(UTC),
                    )
                    session.add(action)
                    session.commit()
                    continue

                order = Order(
                    product_id=product_id,
                    platform="tradera",
                    external_order_id=ext_id,
                    buyer_name=order_data.get("buyer_name"),
                    buyer_address=order_data.get("buyer_address"),
                    sale_price=sale_price,
                    shipping_cost=order_data.get("shipping_cost", 0),
                    status="pending",
                    ordered_at=datetime.now(UTC),
                )
                session.add(order)
                session.flush()

                notification = Notification(
                    type="new_order",
                    product_id=product_id,
                    message_text=(
                        f"Ny order! #{order.id} — "
                        f"{order_data.get('buyer_name', 'Okänd köpare')} "
                        f"köpte produkt #{product_id} för {sale_price} kr"
                    ),
                )
                session.add(notification)

                action = AgentAction(
                    agent_name="order",
                    action_type="detect_new_order",
                    product_id=product_id,
                    details={
                        "order_id": order.id,
                        "external_order_id": ext_id,
                        "sale_price": sale_price,
                    },
                    executed_at=datetime.now(UTC),
                )
                session.add(action)

                session.commit()

                new_orders.append(
                    {
                        "order_id": order.id,
                        "external_order_id": ext_id,
                        "product_id": product_id,
                        "buyer_name": order_data.get("buyer_name"),
                        "sale_price": sale_price,
                    }
                )

        return {"new_orders": new_orders, "count": len(new_orders)}

    def get_order(self, order_id: int) -> dict:
        """Return order details including product title."""
        with Session(self.engine) as session:
            order = session.get(Order, order_id)
            if not order:
                return {"error": f"Order {order_id} not found"}

            product = session.get(Product, order.product_id)
            return {
                "order_id": order.id,
                "product_id": order.product_id,
                "product_title": product.title if product else None,
                "platform": order.platform,
                "external_order_id": order.external_order_id,
                "buyer_name": order.buyer_name,
                "buyer_address": order.buyer_address,
                "sale_price": order.sale_price,
                "platform_fee": order.platform_fee,
                "shipping_cost": order.shipping_cost,
                "status": order.status,
                "voucher_id": order.voucher_id,
                "ordered_at": order.ordered_at.isoformat() if order.ordered_at else None,
                "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
                "tracking_number": order.tracking_number,
                "label_path": order.label_path,
                "feedback_left_at": (
                    order.feedback_left_at.isoformat() if order.feedback_left_at else None
                ),
            }

    def list_orders(self, status: str | None = None) -> dict:
        """List orders, optionally filtered by status."""
        with Session(self.engine) as session:
            query = session.query(Order)
            if status:
                query = query.filter(Order.status == status)
            query = query.order_by(Order.id.desc())
            orders = query.all()

            return {
                "count": len(orders),
                "orders": [
                    {
                        "order_id": o.id,
                        "product_id": o.product_id,
                        "platform": o.platform,
                        "buyer_name": o.buyer_name,
                        "sale_price": o.sale_price,
                        "status": o.status,
                        "ordered_at": o.ordered_at.isoformat() if o.ordered_at else None,
                        "feedback_left_at": (
                            o.feedback_left_at.isoformat() if o.feedback_left_at else None
                        ),
                    }
                    for o in orders
                ],
            }

    def create_sale_voucher(self, order_id: int) -> dict:
        """Create an accounting voucher for a sale order.

        Accounts used (BAS-kontoplan):
          1930 — Bank (debit: money received)
          3001 — Revenue excl. VAT (credit)
          2611 — Outgoing VAT 25% (credit)
          6570 — Bank fees / platform fee (debit, if any)
          6250 — Shipping costs (debit, pass-through)
        """
        if not self.accounting:
            return {"error": "AccountingService not available"}

        with Session(self.engine) as session:
            order = session.get(Order, order_id)
            if not order:
                return {"error": f"Order {order_id} not found"}

            if order.voucher_id:
                return {"error": f"Order {order_id} already has voucher #{order.voucher_id}"}

            if not order.sale_price or order.sale_price <= 0:
                return {"error": f"Order {order_id} has no valid sale price"}

            sale_price = order.sale_price
            shipping_cost = order.shipping_cost or 0
            platform_fee = order.platform_fee or 0

            # VAT calculation: 25% VAT is included in sale_price
            revenue_excl_vat = round(sale_price / 1.25, 2)
            vat = round(sale_price - revenue_excl_vat, 2)

            # Bank deposit = sale + shipping - platform fee
            bank_deposit = round(sale_price + shipping_cost - platform_fee, 2)

            rows = [
                {"account": 1930, "debit": bank_deposit, "credit": 0},
                {"account": 3001, "debit": 0, "credit": revenue_excl_vat},
                {"account": 2611, "debit": 0, "credit": vat},
            ]

            if platform_fee > 0:
                rows.append({"account": 6570, "debit": platform_fee, "credit": 0})

            if shipping_cost > 0:
                # Shipping received from buyer — credited as pass-through revenue.
                # Actual shipping expense (6250 debit) is recorded when paying the carrier.
                rows.append({"account": 3001, "debit": 0, "credit": shipping_cost})

            product = session.get(Product, order.product_id)
            product_title = product.title if product else f"Produkt #{order.product_id}"

            result = self.accounting.create_voucher(
                description=f"Försäljning: {product_title} (Order #{order.id})",
                rows=rows,
                order_id=order.id,
            )

            if "error" in result:
                return result

            order.voucher_id = result["voucher_id"]
            session.commit()

            action = AgentAction(
                agent_name="order",
                action_type="create_sale_voucher",
                product_id=order.product_id,
                details={
                    "order_id": order.id,
                    "voucher_id": result["voucher_id"],
                    "sale_price": sale_price,
                    "vat": vat,
                    "revenue_excl_vat": revenue_excl_vat,
                },
                executed_at=datetime.now(UTC),
            )
            session.add(action)
            session.commit()

        return result

    def mark_shipped(self, order_id: int, tracking_number: str | None = None) -> dict:
        """Mark an order as shipped and notify Tradera."""
        with Session(self.engine) as session:
            order = session.get(Order, order_id)
            if not order:
                return {"error": f"Order {order_id} not found"}

            order.status = "shipped"
            order.shipped_at = datetime.now(UTC)
            if tracking_number:
                order.tracking_number = tracking_number

            # Try to notify Tradera (non-blocking on failure)
            tradera_status = None
            if self.tradera and order.external_order_id:
                try:
                    tradera_result = self.tradera.mark_order_shipped(int(order.external_order_id))
                    tradera_status = tradera_result.get("status", "unknown")
                except Exception:
                    logger.exception(
                        "Failed to notify Tradera about shipment for order %s",
                        order_id,
                    )
                    tradera_status = "notification_failed"

            action = AgentAction(
                agent_name="order",
                action_type="mark_shipped",
                product_id=order.product_id,
                details={
                    "order_id": order.id,
                    "tracking_number": tracking_number,
                    "tradera_status": tradera_status,
                },
                executed_at=datetime.now(UTC),
            )
            session.add(action)
            session.commit()

        return {
            "order_id": order_id,
            "status": "shipped",
            "tracking_number": tracking_number,
            "tradera_status": tradera_status,
        }

    def _get_label_data(self, shipment_result: dict) -> bytes | None:
        """Extract label PDF bytes from shipment result, falling back to get_label API call."""
        if shipment_result.get("label_base64"):
            return base64.b64decode(shipment_result["label_base64"])

        try:
            return self.postnord.get_label(shipment_result["shipment_id"])
        except PostNordError as e:
            logger.error(
                "Failed to retrieve label for shipment %s: %s",
                shipment_result["shipment_id"],
                e,
            )
            return None

    def create_shipping_label(self, order_id: int, service_code: str = "19") -> dict:
        """Create a PostNord shipping label for an order.

        Service codes:
          19 = MyPack Collect (default)
          17 = MyPack Home
          18 = Postpaket
        """
        if not self.postnord:
            return {"error": "PostNord-klient är inte konfigurerad. Ange POSTNORD_API_KEY i .env."}

        with Session(self.engine) as session:
            order = session.get(Order, order_id)
            if not order:
                return {"error": f"Order {order_id} not found"}

            if order.label_path:
                return {"error": f"Order {order_id} har redan en fraktetikett: {order.label_path}"}

            if not order.buyer_address:
                return {"error": f"Order {order_id} saknar köparadress"}

            product = session.get(Product, order.product_id)
            if not product or not product.weight_grams:
                return {"error": f"Produkt för order {order_id} saknar vikt (weight_grams)"}

            try:
                recipient = parse_buyer_address(order.buyer_name or "", order.buyer_address)
            except ValueError as e:
                return {"error": f"Kunde inte tolka köparadressen: {e}"}

            try:
                result = self.postnord.create_shipment(
                    recipient=recipient,
                    weight_grams=product.weight_grams,
                    reference=f"Order #{order.id}",
                    service_code=service_code,
                )
            except PostNordError as e:
                logger.error("PostNord shipment creation failed for order %s: %s", order_id, e)
                return {"error": f"PostNord API-fel: {e}"}

            # Obtain label PDF: prefer inline base64, fall back to separate fetch
            label_data = self._get_label_data(result)

            label_path = None
            if label_data:
                label_path = str(Path(self.label_export_path) / f"order_{order.id}.pdf")
                self.postnord.save_label(label_data, label_path)

            # Update order
            order.tracking_number = result["tracking_number"]
            if label_path:
                order.label_path = label_path

            action = AgentAction(
                agent_name="order",
                action_type="create_shipping_label",
                product_id=order.product_id,
                details={
                    "order_id": order.id,
                    "shipment_id": result["shipment_id"],
                    "tracking_number": result["tracking_number"],
                    "service_code": service_code,
                    "label_path": label_path,
                },
                executed_at=datetime.now(UTC),
            )
            session.add(action)
            session.commit()

        return {
            "order_id": order_id,
            "shipment_id": result["shipment_id"],
            "tracking_number": result["tracking_number"],
            "label_path": label_path,
            "service_code": service_code,
        }

    def leave_feedback(self, order_id: int, comment: str, feedback_type: str = "Positive") -> dict:
        """Leave feedback for the buyer on a completed Tradera order."""
        if not self.tradera:
            return {"error": "Tradera client not available"}

        with Session(self.engine) as session:
            order = session.get(Order, order_id)
            if not order:
                return {"error": f"Order {order_id} not found"}

            if order.platform != "tradera":
                return {"error": f"Order {order_id} is not a Tradera order"}

            if not order.external_order_id:
                return {"error": f"Order {order_id} has no external order ID"}

            if order.status not in ("shipped", "delivered"):
                return {
                    "error": f"Order {order_id} is not shipped/delivered (status: {order.status})"
                }

            if order.feedback_left_at is not None:
                return {
                    "error": f"Feedback already left for order {order_id} at {order.feedback_left_at.isoformat()}"
                }

            result = self.tradera.leave_feedback(
                order_number=int(order.external_order_id),
                comment=comment,
                feedback_type=feedback_type,
            )

            if "error" in result:
                return result

            order.feedback_left_at = datetime.now(UTC)

            action = AgentAction(
                agent_name="order",
                action_type="leave_feedback",
                product_id=order.product_id,
                details={
                    "order_id": order.id,
                    "external_order_id": order.external_order_id,
                    "comment": comment,
                    "feedback_type": feedback_type,
                },
                executed_at=datetime.now(UTC),
            )
            session.add(action)
            session.commit()

        return result

    def list_orders_pending_feedback(self) -> dict:
        """List Tradera orders that have been shipped but lack feedback."""
        with Session(self.engine) as session:
            orders = (
                session.query(Order)
                .filter(
                    Order.platform == "tradera",
                    Order.status.in_(["shipped", "delivered"]),
                    Order.feedback_left_at.is_(None),
                )
                .order_by(Order.id.desc())
                .all()
            )

            result_orders = []
            for o in orders:
                product = session.get(Product, o.product_id)
                result_orders.append(
                    {
                        "order_id": o.id,
                        "product_id": o.product_id,
                        "product_title": product.title if product else None,
                        "buyer_name": o.buyer_name,
                        "sale_price": o.sale_price,
                        "status": o.status,
                        "shipped_at": o.shipped_at.isoformat() if o.shipped_at else None,
                    }
                )

            return {"count": len(result_orders), "orders": result_orders}
