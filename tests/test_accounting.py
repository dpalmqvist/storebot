from pathlib import Path

import pytest
import sqlalchemy as sa

from storebot.db import Order, Product
from storebot.tools.accounting import AccountingService, BAS_ACCOUNTS


@pytest.fixture
def accounting(engine, tmp_path):
    return AccountingService(engine=engine, export_path=str(tmp_path / "vouchers"))


class TestCreateVoucher:
    def test_basic_voucher(self, accounting):
        result = accounting.create_voucher(
            description="Försäljning stol",
            rows=[
                {"account": 1930, "debit": 500, "credit": 0},
                {"account": 3001, "debit": 0, "credit": 400},
                {"account": 2611, "debit": 0, "credit": 100},
            ],
        )
        assert "error" not in result
        assert result["voucher_number"] == "V-001"
        assert result["description"] == "Försäljning stol"
        assert len(result["rows"]) == 3

    def test_voucher_numbering(self, accounting):
        rows = [
            {"account": 1930, "debit": 100, "credit": 0},
            {"account": 3001, "debit": 0, "credit": 100},
        ]
        r1 = accounting.create_voucher(description="First", rows=rows)
        r2 = accounting.create_voucher(description="Second", rows=rows)
        r3 = accounting.create_voucher(description="Third", rows=rows)
        assert r1["voucher_number"] == "V-001"
        assert r2["voucher_number"] == "V-002"
        assert r3["voucher_number"] == "V-003"

    def test_unbalanced_rows_rejected(self, accounting):
        result = accounting.create_voucher(
            description="Bad voucher",
            rows=[
                {"account": 1930, "debit": 500, "credit": 0},
                {"account": 3001, "debit": 0, "credit": 300},
            ],
        )
        assert "error" in result
        assert "balanserar" in result["error"]

    def test_with_order_id(self, accounting, engine):
        with sa.orm.Session(engine) as session:
            product = Product(title="Test product")
            session.add(product)
            session.flush()
            order = Order(product_id=product.id, platform="tradera")
            session.add(order)
            session.commit()
            order_id = order.id

        result = accounting.create_voucher(
            description="Sale with order",
            rows=[
                {"account": 1930, "debit": 100, "credit": 0},
                {"account": 3001, "debit": 0, "credit": 100},
            ],
            order_id=order_id,
        )
        assert result["order_id"] == order_id

    def test_with_transaction_date(self, accounting):
        result = accounting.create_voucher(
            description="Dated voucher",
            rows=[
                {"account": 1930, "debit": 100, "credit": 0},
                {"account": 3001, "debit": 0, "credit": 100},
            ],
            transaction_date="2026-01-15",
        )
        assert result["transaction_date"].startswith("2026-01-15")

    def test_account_name_from_bas(self, accounting):
        result = accounting.create_voucher(
            description="Auto name",
            rows=[
                {"account": 1930, "debit": 100, "credit": 0},
                {"account": 3001, "debit": 0, "credit": 100},
            ],
        )
        names = {r["account"]: r["account_name"] for r in result["rows"]}
        assert names[1930] == "Företagskonto"
        assert names[3001] == "Försäljning varor"

    def test_custom_account_name(self, accounting):
        result = accounting.create_voucher(
            description="Custom name",
            rows=[
                {"account": 1930, "account_name": "My Bank", "debit": 100, "credit": 0},
                {"account": 3001, "debit": 0, "credit": 100},
            ],
        )
        names = {r["account"]: r["account_name"] for r in result["rows"]}
        assert names[1930] == "My Bank"

    def test_unknown_account_gets_fallback_name(self, accounting):
        result = accounting.create_voucher(
            description="Unknown account",
            rows=[
                {"account": 9999, "debit": 100, "credit": 0},
                {"account": 3001, "debit": 0, "credit": 100},
            ],
        )
        names = {r["account"]: r["account_name"] for r in result["rows"]}
        assert names[9999] == "Konto 9999"


class TestGetVouchers:
    def test_empty(self, accounting):
        assert accounting.get_vouchers() == []

    def test_returns_all(self, accounting):
        rows = [
            {"account": 1930, "debit": 100, "credit": 0},
            {"account": 3001, "debit": 0, "credit": 100},
        ]
        accounting.create_voucher(description="A", rows=rows, transaction_date="2026-01-01")
        accounting.create_voucher(description="B", rows=rows, transaction_date="2026-02-01")
        result = accounting.get_vouchers()
        assert len(result) == 2

    def test_filter_by_date_range(self, accounting):
        rows = [
            {"account": 1930, "debit": 100, "credit": 0},
            {"account": 3001, "debit": 0, "credit": 100},
        ]
        accounting.create_voucher(description="Jan", rows=rows, transaction_date="2026-01-15")
        accounting.create_voucher(description="Feb", rows=rows, transaction_date="2026-02-15")
        accounting.create_voucher(description="Mar", rows=rows, transaction_date="2026-03-15")

        result = accounting.get_vouchers(from_date="2026-02-01", to_date="2026-02-28")
        assert len(result) == 1
        assert result[0]["description"] == "Feb"


class TestExportVoucherPdf:
    def test_single_voucher_pdf(self, accounting):
        result = accounting.create_voucher(
            description="Test PDF",
            rows=[
                {"account": 1930, "debit": 250, "credit": 0},
                {"account": 3001, "debit": 0, "credit": 200},
                {"account": 2611, "debit": 0, "credit": 50},
            ],
        )
        path = accounting.export_voucher_pdf(result["voucher_id"])
        assert Path(path).exists()
        assert path.endswith(".pdf")
        assert "V-001" in path

    def test_nonexistent_voucher_raises(self, accounting):
        with pytest.raises(ValueError, match="hittades inte"):
            accounting.export_voucher_pdf(999)


class TestExportVouchersPdf:
    def test_batch_pdf(self, accounting):
        rows = [
            {"account": 1930, "debit": 100, "credit": 0},
            {"account": 3001, "debit": 0, "credit": 100},
        ]
        accounting.create_voucher(description="V1", rows=rows, transaction_date="2026-03-01")
        accounting.create_voucher(description="V2", rows=rows, transaction_date="2026-03-15")

        result = accounting.export_vouchers_pdf("2026-03-01", "2026-03-31")
        assert Path(result["pdf_path"]).exists()
        assert result["pdf_path"].endswith(".pdf")

    def test_no_vouchers_in_range_raises(self, accounting):
        with pytest.raises(ValueError, match="Inga verifikationer"):
            accounting.export_vouchers_pdf("2099-01-01", "2099-12-31")


class TestListVouchers:
    def test_empty(self, accounting):
        result = accounting.list_vouchers()
        assert result["count"] == 0
        assert result["vouchers"] == []

    def test_returns_wrapped_dict(self, accounting):
        rows = [
            {"account": 1930, "debit": 100, "credit": 0},
            {"account": 3001, "debit": 0, "credit": 100},
        ]
        accounting.create_voucher(description="A", rows=rows, transaction_date="2026-01-01")
        accounting.create_voucher(description="B", rows=rows, transaction_date="2026-02-01")

        result = accounting.list_vouchers()
        assert result["count"] == 2
        assert len(result["vouchers"]) == 2
        assert result["vouchers"][0]["description"] == "A"
        assert result["vouchers"][1]["description"] == "B"

    def test_date_filtering(self, accounting):
        rows = [
            {"account": 1930, "debit": 100, "credit": 0},
            {"account": 3001, "debit": 0, "credit": 100},
        ]
        accounting.create_voucher(description="Jan", rows=rows, transaction_date="2026-01-15")
        accounting.create_voucher(description="Feb", rows=rows, transaction_date="2026-02-15")
        accounting.create_voucher(description="Mar", rows=rows, transaction_date="2026-03-15")

        result = accounting.list_vouchers(from_date="2026-02-01", to_date="2026-02-28")
        assert result["count"] == 1
        assert result["vouchers"][0]["description"] == "Feb"


class TestBasAccounts:
    def test_all_expected_accounts_present(self):
        expected = [1910, 1930, 2611, 2640, 3001, 4010, 6250, 6570]
        for account in expected:
            assert account in BAS_ACCOUNTS


class TestVoucherPdfWithOrderId:
    def test_voucher_with_order_id(self, accounting, engine):
        """Cover _build_voucher_story when voucher.order_id is set (line 133)."""
        from sqlalchemy.orm import Session

        # Create a product and order so we have valid references
        with Session(engine) as session:
            product = Product(title="Test", status="sold")
            session.add(product)
            session.flush()
            order = Order(
                product_id=product.id,
                platform="tradera",
                external_order_id="42",
                sale_price=500,
                status="shipped",
            )
            session.add(order)
            session.commit()
            order_id = order.id

        result = accounting.create_voucher(
            description="Försäljning med order",
            rows=[
                {"account": 1930, "debit": 500, "credit": 0},
                {"account": 3001, "debit": 0, "credit": 400},
                {"account": 2611, "debit": 0, "credit": 100},
            ],
            order_id=order_id,
        )
        assert "error" not in result

        pdf_path = accounting.export_voucher_pdf(result["voucher_id"])
        assert Path(pdf_path).exists()
