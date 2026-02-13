from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from storebot.db import (
    AgentAction,
    Base,
    Notification,
    Order,
    PlatformListing,
    Product,
)
from storebot.tools.accounting import AccountingService
from storebot.tools.order import OrderService


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def mock_tradera():
    return MagicMock()


@pytest.fixture
def accounting(engine, tmp_path):
    return AccountingService(engine=engine, export_path=str(tmp_path / "vouchers"))


@pytest.fixture
def service(engine, mock_tradera, accounting):
    return OrderService(engine=engine, tradera=mock_tradera, accounting=accounting)


def _create_product(engine, title="Antik byrå", status="listed") -> int:
    with Session(engine) as session:
        product = Product(title=title, status=status)
        session.add(product)
        session.commit()
        return product.id


def _create_listing(engine, product_id, external_id="12345", platform="tradera") -> int:
    with Session(engine) as session:
        listing = PlatformListing(
            product_id=product_id,
            platform=platform,
            external_id=external_id,
            status="active",
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
        )
        session.add(listing)
        session.commit()
        return listing.id


def _create_order(engine, product_id, external_order_id="99", sale_price=500.0, **kwargs) -> int:
    with Session(engine) as session:
        order = Order(
            product_id=product_id,
            platform="tradera",
            external_order_id=external_order_id,
            sale_price=sale_price,
            status=kwargs.get("status", "pending"),
            buyer_name=kwargs.get("buyer_name", "Test Köpare"),
            buyer_address=kwargs.get("buyer_address"),
            shipping_cost=kwargs.get("shipping_cost", 0),
            platform_fee=kwargs.get("platform_fee", 0),
            ordered_at=datetime.now(UTC),
        )
        session.add(order)
        session.commit()
        return order.id


def _make_tradera_order(order_id=99, item_id="12345", sub_total=500, shipping_cost=50):
    return {
        "order_id": order_id,
        "buyer_name": "Anna Svensson",
        "buyer_address": "Storgatan 1, 123 45 Stockholm",
        "sub_total": sub_total,
        "shipping_cost": shipping_cost,
        "items": [{"item_id": item_id, "title": "Antik byrå", "price": sub_total, "quantity": 1}],
        "payments": [{"type": "DirectPayment", "amount": sub_total + shipping_cost}],
    }


class TestCheckNewOrders:
    def test_detects_new_order(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        _create_listing(engine, product_id, external_id="12345")
        mock_tradera.get_orders.return_value = {
            "orders": [_make_tradera_order()],
            "count": 1,
        }

        result = service.check_new_orders()

        assert result["count"] == 1
        assert result["new_orders"][0]["product_id"] == product_id
        assert result["new_orders"][0]["sale_price"] == 500

    def test_deduplicates_existing_orders(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        _create_listing(engine, product_id, external_id="12345")
        _create_order(engine, product_id, external_order_id="99")
        mock_tradera.get_orders.return_value = {
            "orders": [_make_tradera_order(order_id=99)],
            "count": 1,
        }

        result = service.check_new_orders()

        assert result["count"] == 0
        assert result["new_orders"] == []

    def test_updates_listing_and_product_status(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        listing_id = _create_listing(engine, product_id, external_id="12345")
        mock_tradera.get_orders.return_value = {
            "orders": [_make_tradera_order()],
            "count": 1,
        }

        service.check_new_orders()

        with Session(engine) as session:
            listing = session.get(PlatformListing, listing_id)
            product = session.get(Product, product_id)
            assert listing.status == "sold"
            assert product.status == "sold"
            assert product.sold_price == 500

    def test_creates_notification(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        _create_listing(engine, product_id, external_id="12345")
        mock_tradera.get_orders.return_value = {
            "orders": [_make_tradera_order()],
            "count": 1,
        }

        service.check_new_orders()

        with Session(engine) as session:
            notifications = session.query(Notification).all()
            assert len(notifications) == 1
            assert "Ny order" in notifications[0].message_text
            assert notifications[0].type == "new_order"

    def test_logs_agent_action(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        _create_listing(engine, product_id, external_id="12345")
        mock_tradera.get_orders.return_value = {
            "orders": [_make_tradera_order()],
            "count": 1,
        }

        service.check_new_orders()

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="detect_new_order").all()
            assert len(actions) == 1
            assert actions[0].agent_name == "order"
            assert actions[0].product_id == product_id

    def test_unmatched_order_persisted(self, service, engine, mock_tradera):
        mock_tradera.get_orders.return_value = {
            "orders": [_make_tradera_order(item_id="99999")],
            "count": 1,
        }

        result = service.check_new_orders()

        assert result["count"] == 1
        assert result["new_orders"][0]["product_id"] is None
        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="unmatched_order").all()
            assert len(actions) == 1
            # Order should be persisted with null product_id
            order = session.query(Order).first()
            assert order is not None
            assert order.product_id is None
            assert order.external_order_id == "99"

    def test_tradera_error_propagated(self, service, mock_tradera):
        mock_tradera.get_orders.return_value = {"error": "Connection refused"}

        result = service.check_new_orders()

        assert result["error"] == "Connection refused"

    def test_no_tradera_client(self, engine, accounting):
        svc = OrderService(engine=engine, tradera=None, accounting=accounting)
        result = svc.check_new_orders()
        assert result["error"] == "Tradera client not available"

    def test_multiple_orders(self, service, engine, mock_tradera):
        p1 = _create_product(engine, title="Byrå")
        p2 = _create_product(engine, title="Lampa")
        _create_listing(engine, p1, external_id="111")
        _create_listing(engine, p2, external_id="222")
        mock_tradera.get_orders.return_value = {
            "orders": [
                _make_tradera_order(order_id=1, item_id="111", sub_total=500),
                _make_tradera_order(order_id=2, item_id="222", sub_total=300),
            ],
            "count": 2,
        }

        result = service.check_new_orders()

        assert result["count"] == 2


class TestGetOrder:
    def test_found(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id)

        result = service.get_order(order_id)

        assert result["order_id"] == order_id
        assert result["product_title"] == "Antik byrå"
        assert result["status"] == "pending"

    def test_not_found(self, service):
        result = service.get_order(999)
        assert result["error"] == "Order 999 not found"

    def test_includes_product_title(self, service, engine):
        product_id = _create_product(engine, title="Mässingsljusstake")
        order_id = _create_order(engine, product_id)

        result = service.get_order(order_id)

        assert result["product_title"] == "Mässingsljusstake"


class TestListOrders:
    def test_all_orders(self, service, engine):
        p1 = _create_product(engine)
        p2 = _create_product(engine, title="Lampa")
        _create_order(engine, p1, external_order_id="1")
        _create_order(engine, p2, external_order_id="2", status="shipped")

        result = service.list_orders()

        assert result["count"] == 2

    def test_filtered_by_status(self, service, engine):
        p1 = _create_product(engine)
        p2 = _create_product(engine, title="Lampa")
        _create_order(engine, p1, external_order_id="1", status="pending")
        _create_order(engine, p2, external_order_id="2", status="shipped")

        result = service.list_orders(status="pending")

        assert result["count"] == 1
        assert result["orders"][0]["status"] == "pending"

    def test_empty(self, service):
        result = service.list_orders()
        assert result["count"] == 0
        assert result["orders"] == []

    def test_ordered_by_id_desc(self, service, engine):
        p = _create_product(engine)
        id1 = _create_order(engine, p, external_order_id="1")
        id2 = _create_order(engine, p, external_order_id="2")

        result = service.list_orders()

        assert result["orders"][0]["order_id"] == id2
        assert result["orders"][1]["order_id"] == id1


class TestCreateSaleVoucher:
    def test_basic_voucher(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, sale_price=1000.0)

        result = service.create_sale_voucher(order_id)

        assert "error" not in result
        assert result["voucher_number"]

        # Verify VAT math: 1000 / 1.25 = 800 revenue, 200 VAT
        rows = result["rows"]
        bank_row = next(r for r in rows if r["account"] == 1930)
        revenue_row = next(r for r in rows if r["account"] == 3001)
        vat_row = next(r for r in rows if r["account"] == 2611)

        assert bank_row["debit"] == 1000.0
        assert revenue_row["credit"] == 800.0
        assert vat_row["credit"] == 200.0

    def test_with_platform_fee(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, sale_price=1000.0, platform_fee=50.0)

        result = service.create_sale_voucher(order_id)

        rows = result["rows"]
        bank_row = next(r for r in rows if r["account"] == 1930)
        fee_row = next(r for r in rows if r["account"] == 6570)

        # Bank deposit = 1000 + 0 - 50 = 950
        assert bank_row["debit"] == 950.0
        assert fee_row["debit"] == 50.0

    def test_with_shipping(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, sale_price=1000.0, shipping_cost=79.0)

        result = service.create_sale_voucher(order_id)

        rows = result["rows"]
        bank_row = next(r for r in rows if r["account"] == 1930)
        # Shipping credited as pass-through revenue on 3001
        revenue_rows = [r for r in rows if r["account"] == 3001]
        total_revenue_credit = sum(r["credit"] for r in revenue_rows)

        # Bank deposit = 1000 + 79 - 0 = 1079
        assert bank_row["debit"] == 1079.0
        # Revenue: 800 (excl VAT) + 79 (shipping pass-through) = 879
        assert total_revenue_credit == 879.0

    def test_order_not_found(self, service):
        result = service.create_sale_voucher(999)
        assert result["error"] == "Order 999 not found"

    def test_duplicate_voucher_rejected(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, sale_price=1000.0)

        service.create_sale_voucher(order_id)
        result = service.create_sale_voucher(order_id)

        assert "already has voucher" in result["error"]

    def test_zero_sale_price_rejected(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, sale_price=0)

        result = service.create_sale_voucher(order_id)

        assert "no valid sale price" in result["error"]

    def test_links_voucher_to_order(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, sale_price=500.0)

        result = service.create_sale_voucher(order_id)

        with Session(engine) as session:
            order = session.get(Order, order_id)
            assert order.voucher_id == result["voucher_id"]

    def test_logs_agent_action(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, sale_price=500.0)

        service.create_sale_voucher(order_id)

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="create_sale_voucher").all()
            assert len(actions) == 1
            assert actions[0].agent_name == "order"

    def test_unmatched_order_rejected(self, service, engine):
        with Session(engine) as session:
            order = Order(
                product_id=None,
                platform="tradera",
                external_order_id="unmatched",
                sale_price=500.0,
                status="pending",
            )
            session.add(order)
            session.commit()
            order_id = order.id

        result = service.create_sale_voucher(order_id)

        assert "no linked product" in result["error"]

    def test_no_accounting_service(self, engine, mock_tradera):
        svc = OrderService(engine=engine, tradera=mock_tradera, accounting=None)
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, sale_price=500.0)

        result = svc.create_sale_voucher(order_id)

        assert result["error"] == "AccountingService not available"

    def test_debit_credit_balance(self, service, engine):
        """Verify total debits == total credits in generated voucher."""
        product_id = _create_product(engine)
        order_id = _create_order(
            engine, product_id, sale_price=1250.0, shipping_cost=79.0, platform_fee=125.0
        )

        result = service.create_sale_voucher(order_id)

        rows = result["rows"]
        total_debit = sum(r["debit"] for r in rows)
        total_credit = sum(r["credit"] for r in rows)
        assert abs(total_debit - total_credit) < 0.01


class TestMarkShipped:
    def test_marks_shipped(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id)
        mock_tradera.mark_order_shipped.return_value = {"status": "shipped"}

        result = service.mark_shipped(order_id)

        assert result["status"] == "shipped"
        with Session(engine) as session:
            order = session.get(Order, order_id)
            assert order.status == "shipped"
            assert order.shipped_at is not None

    def test_sets_tracking_number(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id)
        mock_tradera.mark_order_shipped.return_value = {"status": "shipped"}

        result = service.mark_shipped(order_id, tracking_number="SE123456789")

        assert result["tracking_number"] == "SE123456789"

    def test_tradera_notification_failure_non_blocking(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id)
        mock_tradera.mark_order_shipped.side_effect = Exception("API error")

        result = service.mark_shipped(order_id)

        assert result["status"] == "shipped"
        assert result["tradera_status"] == "notification_failed"
        with Session(engine) as session:
            order = session.get(Order, order_id)
            assert order.status == "shipped"

    def test_order_not_found(self, service):
        result = service.mark_shipped(999)
        assert result["error"] == "Order 999 not found"

    def test_logs_agent_action(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id)
        mock_tradera.mark_order_shipped.return_value = {"status": "shipped"}

        service.mark_shipped(order_id)

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="mark_shipped").all()
            assert len(actions) == 1
            assert actions[0].agent_name == "order"


class TestMarkShippedTracking:
    def test_persists_tracking_number_on_order(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id)
        mock_tradera.mark_order_shipped.return_value = {"status": "shipped"}

        service.mark_shipped(order_id, tracking_number="SE123456789")

        with Session(engine) as session:
            order = session.get(Order, order_id)
            assert order.tracking_number == "SE123456789"


class TestGetOrderIncludesShippingFields:
    def test_includes_tracking_and_label(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id)

        result = service.get_order(order_id)

        assert "tracking_number" in result
        assert "label_path" in result


def _create_product_with_weight(engine, title="Antik byrå", weight_grams=2000):
    with Session(engine) as session:
        product = Product(title=title, status="listed", weight_grams=weight_grams)
        session.add(product)
        session.commit()
        return product.id


class TestCreateShippingLabel:
    def test_no_postnord_client(self, engine, mock_tradera, accounting):
        svc = OrderService(
            engine=engine, tradera=mock_tradera, accounting=accounting, postnord=None
        )
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id)

        result = svc.create_shipping_label(order_id)

        assert "error" in result
        assert "PostNord" in result["error"]

    def test_order_not_found(self, engine, mock_tradera, accounting):
        mock_postnord = MagicMock()
        svc = OrderService(
            engine=engine, tradera=mock_tradera, accounting=accounting, postnord=mock_postnord
        )

        result = svc.create_shipping_label(999)

        assert result["error"] == "Order 999 not found"

    def test_missing_buyer_address(self, engine, mock_tradera, accounting):
        mock_postnord = MagicMock()
        svc = OrderService(
            engine=engine, tradera=mock_tradera, accounting=accounting, postnord=mock_postnord
        )
        product_id = _create_product_with_weight(engine)
        order_id = _create_order(engine, product_id, buyer_address=None)

        result = svc.create_shipping_label(order_id)

        assert "saknar köparadress" in result["error"]

    def test_missing_weight(self, engine, mock_tradera, accounting):
        mock_postnord = MagicMock()
        svc = OrderService(
            engine=engine, tradera=mock_tradera, accounting=accounting, postnord=mock_postnord
        )
        product_id = _create_product(engine)  # no weight_grams
        order_id = _create_order(engine, product_id, buyer_address="Storgatan 1, 123 45 Stockholm")

        result = svc.create_shipping_label(order_id)

        assert "saknar vikt" in result["error"]

    def test_success_with_label(self, engine, mock_tradera, accounting, tmp_path):
        import base64

        mock_postnord = MagicMock()
        label_dir = str(tmp_path / "labels")
        svc = OrderService(
            engine=engine,
            tradera=mock_tradera,
            accounting=accounting,
            postnord=mock_postnord,
            label_export_path=label_dir,
        )
        product_id = _create_product_with_weight(engine, weight_grams=3000)
        order_id = _create_order(
            engine,
            product_id,
            buyer_name="Anna Svensson",
            buyer_address="Storgatan 1, 123 45 Stockholm",
        )

        mock_postnord.create_shipment.return_value = {
            "shipment_id": "SH-001",
            "tracking_number": "SE123456789",
            "label_base64": base64.b64encode(b"%PDF-1.4 test").decode(),
        }

        result = svc.create_shipping_label(order_id)

        assert result["tracking_number"] == "SE123456789"
        assert result["shipment_id"] == "SH-001"
        assert result["label_path"] is not None
        assert "order_" in result["label_path"]
        mock_postnord.save_label.assert_called_once()

        # Verify order updated in DB
        with Session(engine) as session:
            order = session.get(Order, order_id)
            assert order.tracking_number == "SE123456789"
            assert order.label_path is not None

    def test_duplicate_label_rejected(self, engine, mock_tradera, accounting):
        mock_postnord = MagicMock()
        svc = OrderService(
            engine=engine, tradera=mock_tradera, accounting=accounting, postnord=mock_postnord
        )
        product_id = _create_product_with_weight(engine)
        order_id = _create_order(engine, product_id, buyer_address="Storgatan 1, 123 45 Stockholm")

        # Set label_path to simulate existing label
        with Session(engine) as session:
            order = session.get(Order, order_id)
            order.label_path = "data/labels/order_1.pdf"
            session.commit()

        result = svc.create_shipping_label(order_id)

        assert "redan en fraktetikett" in result["error"]

    def test_postnord_error_handled(self, engine, mock_tradera, accounting):
        from storebot.tools.postnord import PostNordError

        mock_postnord = MagicMock()
        mock_postnord.create_shipment.side_effect = PostNordError("Bad request", status_code=400)
        svc = OrderService(
            engine=engine, tradera=mock_tradera, accounting=accounting, postnord=mock_postnord
        )
        product_id = _create_product_with_weight(engine)
        order_id = _create_order(engine, product_id, buyer_address="Storgatan 1, 123 45 Stockholm")

        result = svc.create_shipping_label(order_id)

        assert "PostNord API-fel" in result["error"]

    def test_logs_agent_action(self, engine, mock_tradera, accounting, tmp_path):
        import base64

        mock_postnord = MagicMock()
        label_dir = str(tmp_path / "labels")
        svc = OrderService(
            engine=engine,
            tradera=mock_tradera,
            accounting=accounting,
            postnord=mock_postnord,
            label_export_path=label_dir,
        )
        product_id = _create_product_with_weight(engine)
        order_id = _create_order(
            engine,
            product_id,
            buyer_address="Storgatan 1, 123 45 Stockholm",
        )

        mock_postnord.create_shipment.return_value = {
            "shipment_id": "SH-002",
            "tracking_number": "SE999",
            "label_base64": base64.b64encode(b"%PDF").decode(),
        }

        svc.create_shipping_label(order_id)

        with Session(engine) as session:
            actions = (
                session.query(AgentAction).filter_by(action_type="create_shipping_label").all()
            )
            assert len(actions) == 1
            assert actions[0].agent_name == "order"
            assert actions[0].details["tracking_number"] == "SE999"

    def test_success_without_inline_label(self, engine, mock_tradera, accounting, tmp_path):
        """When label_base64 is empty, get_label is called as fallback."""
        mock_postnord = MagicMock()
        label_dir = str(tmp_path / "labels")
        svc = OrderService(
            engine=engine,
            tradera=mock_tradera,
            accounting=accounting,
            postnord=mock_postnord,
            label_export_path=label_dir,
        )
        product_id = _create_product_with_weight(engine)
        order_id = _create_order(
            engine,
            product_id,
            buyer_address="Storgatan 1, 123 45 Stockholm",
        )

        mock_postnord.create_shipment.return_value = {
            "shipment_id": "SH-003",
            "tracking_number": "SE111",
            "label_base64": "",
        }
        mock_postnord.get_label.return_value = b"%PDF-1.4 fetched"

        result = svc.create_shipping_label(order_id)

        mock_postnord.get_label.assert_called_once_with("SH-003")
        assert result["tracking_number"] == "SE111"
        assert result["label_path"] is not None


class TestLeaveFeedback:
    def test_success(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, status="shipped")
        mock_tradera.leave_feedback.return_value = {
            "success": True,
            "order_number": 99,
            "comment": "Tack för köpet!",
            "feedback_type": "Positive",
        }

        result = service.leave_feedback(order_id, comment="Tack för köpet!")

        assert result["success"] is True
        mock_tradera.leave_feedback.assert_called_once_with(
            order_number=99, comment="Tack för köpet!", feedback_type="Positive"
        )

        with Session(engine) as session:
            order = session.get(Order, order_id)
            assert order.feedback_left_at is not None

    def test_negative_feedback(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, status="shipped")
        mock_tradera.leave_feedback.return_value = {
            "success": True,
            "order_number": 99,
            "comment": "Betalade sent",
            "feedback_type": "Negative",
        }

        result = service.leave_feedback(
            order_id, comment="Betalade sent", feedback_type="Negative"
        )

        assert result["success"] is True

    def test_order_not_found(self, service):
        result = service.leave_feedback(999, comment="Tack!")
        assert result["error"] == "Order 999 not found"

    def test_already_left_feedback(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, status="shipped")

        with Session(engine) as session:
            order = session.get(Order, order_id)
            order.feedback_left_at = datetime.now(UTC)
            session.commit()

        result = service.leave_feedback(order_id, comment="Tack!")
        assert "already left" in result["error"]

    def test_not_shipped(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, status="pending")

        result = service.leave_feedback(order_id, comment="Tack!")
        assert "not shipped/delivered" in result["error"]

    def test_non_tradera_order(self, service, engine):
        product_id = _create_product(engine)
        with Session(engine) as session:
            order = Order(
                product_id=product_id,
                platform="blocket",
                external_order_id="123",
                status="shipped",
                ordered_at=datetime.now(UTC),
            )
            session.add(order)
            session.commit()
            order_id = order.id

        result = service.leave_feedback(order_id, comment="Tack!")
        assert "not a Tradera order" in result["error"]

    def test_no_external_order_id(self, service, engine):
        product_id = _create_product(engine)
        with Session(engine) as session:
            order = Order(
                product_id=product_id,
                platform="tradera",
                external_order_id=None,
                status="shipped",
                ordered_at=datetime.now(UTC),
            )
            session.add(order)
            session.commit()
            order_id = order.id

        result = service.leave_feedback(order_id, comment="Tack!")
        assert "no external order ID" in result["error"]

    def test_api_error_propagated(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, status="shipped")
        mock_tradera.leave_feedback.return_value = {"error": "API timeout"}

        result = service.leave_feedback(order_id, comment="Tack!")

        assert result["error"] == "API timeout"
        with Session(engine) as session:
            order = session.get(Order, order_id)
            assert order.feedback_left_at is None

    def test_logs_agent_action(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, status="shipped")
        mock_tradera.leave_feedback.return_value = {
            "success": True,
            "order_number": 99,
            "comment": "Tack!",
            "feedback_type": "Positive",
        }

        service.leave_feedback(order_id, comment="Tack!")

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="leave_feedback").all()
            assert len(actions) == 1
            assert actions[0].agent_name == "order"
            assert actions[0].details["comment"] == "Tack!"

    def test_no_tradera_client(self, engine, accounting):
        svc = OrderService(engine=engine, tradera=None, accounting=accounting)
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, status="shipped")

        result = svc.leave_feedback(order_id, comment="Tack!")
        assert result["error"] == "Tradera client not available"

    def test_delivered_order_allowed(self, service, engine, mock_tradera):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, status="delivered")
        mock_tradera.leave_feedback.return_value = {
            "success": True,
            "order_number": 99,
            "comment": "Tack!",
            "feedback_type": "Positive",
        }

        result = service.leave_feedback(order_id, comment="Tack!")
        assert result["success"] is True


class TestListOrdersPendingFeedback:
    def test_includes_shipped_without_feedback(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id, status="shipped")

        result = service.list_orders_pending_feedback()

        assert result["count"] == 1
        assert result["orders"][0]["order_id"] == order_id

    def test_excludes_feedback_given(self, service, engine):
        product_id = _create_product(engine)
        _create_order(engine, product_id, status="shipped")

        with Session(engine) as session:
            order = session.query(Order).first()
            order.feedback_left_at = datetime.now(UTC)
            session.commit()

        result = service.list_orders_pending_feedback()
        assert result["count"] == 0

    def test_excludes_pending_orders(self, service, engine):
        product_id = _create_product(engine)
        _create_order(engine, product_id, status="pending")

        result = service.list_orders_pending_feedback()
        assert result["count"] == 0

    def test_excludes_non_tradera(self, service, engine):
        product_id = _create_product(engine)
        with Session(engine) as session:
            order = Order(
                product_id=product_id,
                platform="blocket",
                status="shipped",
                ordered_at=datetime.now(UTC),
            )
            session.add(order)
            session.commit()

        result = service.list_orders_pending_feedback()
        assert result["count"] == 0

    def test_empty_list(self, service):
        result = service.list_orders_pending_feedback()
        assert result["count"] == 0
        assert result["orders"] == []

    def test_includes_product_title(self, service, engine):
        product_id = _create_product(engine, title="Mässingsljusstake")
        _create_order(engine, product_id, status="shipped")

        result = service.list_orders_pending_feedback()

        assert result["orders"][0]["product_title"] == "Mässingsljusstake"

    def test_includes_delivered_orders(self, service, engine):
        product_id = _create_product(engine)
        _create_order(engine, product_id, status="delivered")

        result = service.list_orders_pending_feedback()
        assert result["count"] == 1


class TestGetOrderIncludesFeedback:
    def test_includes_feedback_left_at(self, service, engine):
        product_id = _create_product(engine)
        order_id = _create_order(engine, product_id)

        result = service.get_order(order_id)

        assert "feedback_left_at" in result
        assert result["feedback_left_at"] is None
