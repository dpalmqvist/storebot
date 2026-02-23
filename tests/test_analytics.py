from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from storebot.db import (
    AgentAction,
    Base,
    Order,
    PlatformListing,
    Product,
)
from storebot.tools.analytics import AnalyticsService, _parse_period

# Fixed reference time for deterministic tests
FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0)


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def service(engine):
    return AnalyticsService(engine=engine)


def _create_product(
    engine, title="Test produkt", category="möbler", status="draft", **kwargs
) -> int:
    with Session(engine) as session:
        product = Product(title=title, category=category, status=status, **kwargs)
        session.add(product)
        session.commit()
        return product.id


def _create_listing(engine, product_id, status="active", listed_at=None, **kwargs) -> int:
    with Session(engine) as session:
        listing = PlatformListing(
            product_id=product_id,
            platform="tradera",
            status=status,
            listed_at=listed_at,
            listing_title=kwargs.pop("listing_title", "Test annons"),
            **kwargs,
        )
        session.add(listing)
        session.commit()
        return listing.id


def _create_order(engine, product_id, sale_price=500.0, ordered_at=None, **kwargs) -> int:
    with Session(engine) as session:
        order = Order(
            product_id=product_id,
            platform="tradera",
            sale_price=sale_price,
            ordered_at=ordered_at or FIXED_NOW,
            **kwargs,
        )
        session.add(order)
        session.commit()
        return order.id


# ---------------------------------------------------------------------------
# _parse_period
# ---------------------------------------------------------------------------


class TestParsePeriod:
    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_none_returns_current_month(self, _mock):
        start, end = _parse_period(None)
        assert start == datetime(2026, 6, 1)
        assert end == datetime(2026, 7, 1)

    def test_month_format(self):
        start, end = _parse_period("2026-01")
        assert start == datetime(2026, 1, 1)
        assert end == datetime(2026, 2, 1)

    def test_month_december(self):
        start, end = _parse_period("2026-12")
        assert start == datetime(2026, 12, 1)
        assert end == datetime(2027, 1, 1)

    def test_quarter_q1(self):
        start, end = _parse_period("2026-Q1")
        assert start == datetime(2026, 1, 1)
        assert end == datetime(2026, 4, 1)

    def test_quarter_q4(self):
        start, end = _parse_period("2026-Q4")
        assert start == datetime(2026, 10, 1)
        assert end == datetime(2027, 1, 1)

    def test_year_format(self):
        start, end = _parse_period("2026")
        assert start == datetime(2026, 1, 1)
        assert end == datetime(2027, 1, 1)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Okänt periodformat"):
            _parse_period("invalid")

    def test_invalid_quarter_raises(self):
        with pytest.raises(ValueError):
            _parse_period("2026-Q5")

    @patch("storebot.tools.analytics.naive_now", return_value=datetime(2026, 1, 15))
    def test_none_in_january(self, _mock):
        start, end = _parse_period(None)
        assert start == datetime(2026, 1, 1)
        assert end == datetime(2026, 2, 1)

    @patch("storebot.tools.analytics.naive_now", return_value=datetime(2026, 12, 10))
    def test_none_in_december(self, _mock):
        start, end = _parse_period(None)
        assert start == datetime(2026, 12, 1)
        assert end == datetime(2027, 1, 1)


# ---------------------------------------------------------------------------
# business_summary
# ---------------------------------------------------------------------------


class TestBusinessSummary:
    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_empty_db(self, _mock, service):
        result = service.business_summary("2026-06")
        assert result["revenue"] == 0
        assert result["items_sold"] == 0
        assert result["gross_profit"] == 0
        assert result["margin_percent"] == 0.0
        assert result["avg_time_to_sale_days"] is None

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_with_sales(self, _mock, service, engine):
        pid = _create_product(engine, acquisition_cost=100.0, status="sold")
        _create_listing(engine, pid, listed_at=FIXED_NOW - timedelta(days=5))
        _create_order(engine, pid, sale_price=500.0, platform_fee=50.0, shipping_cost=30.0)

        result = service.business_summary("2026-06")

        assert result["revenue"] == 500.0
        assert result["acquisition_cost"] == 100.0
        assert result["platform_fees"] == 50.0
        assert result["shipping_cost"] == 30.0
        assert result["gross_profit"] == 320.0
        assert result["items_sold"] == 1

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_period_filter(self, _mock, service, engine):
        pid = _create_product(engine, acquisition_cost=100.0)
        _create_order(engine, pid, sale_price=500.0, ordered_at=datetime(2026, 5, 10))
        _create_order(engine, pid, sale_price=300.0, ordered_at=datetime(2026, 6, 10))

        result = service.business_summary("2026-06")
        assert result["items_sold"] == 1
        assert result["revenue"] == 300.0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_stock_count(self, _mock, service, engine):
        _create_product(engine, status="draft")
        _create_product(engine, status="listed")
        _create_product(engine, status="sold")

        result = service.business_summary("2026-06")
        assert result["stock_count"] == 2

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_time_to_sale(self, _mock, service, engine):
        pid = _create_product(engine, acquisition_cost=50.0)
        _create_listing(engine, pid, listed_at=FIXED_NOW - timedelta(days=10))
        _create_order(engine, pid, sale_price=200.0, ordered_at=FIXED_NOW)

        result = service.business_summary("2026-06")
        assert result["avg_time_to_sale_days"] == 10.0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_missing_acquisition_cost(self, _mock, service, engine):
        pid = _create_product(engine, acquisition_cost=None)
        _create_order(engine, pid, sale_price=500.0)

        result = service.business_summary("2026-06")
        assert result["acquisition_cost"] == 0
        assert result["gross_profit"] == 500.0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_logs_agent_action(self, _mock, service, engine):
        service.business_summary("2026-06")

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="business_summary").all()
            assert len(actions) == 1
            assert actions[0].agent_name == "analytics"

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_margin_calculation(self, _mock, service, engine):
        pid = _create_product(engine, acquisition_cost=200.0)
        _create_order(engine, pid, sale_price=1000.0, platform_fee=100.0, shipping_cost=50.0)

        result = service.business_summary("2026-06")
        # profit = 1000 - 200 - 100 - 50 = 650
        # margin = 650 / 1000 * 100 = 65.0
        assert result["margin_percent"] == 65.0


# ---------------------------------------------------------------------------
# profitability_report
# ---------------------------------------------------------------------------


class TestProfitabilityReport:
    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_empty_db(self, _mock, service):
        result = service.profitability_report("2026-06")
        assert result["total_products"] == 0
        assert result["top_5"] == []
        assert result["bottom_5"] == []

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_top_bottom_5(self, _mock, service, engine):
        for i in range(8):
            pid = _create_product(
                engine,
                title=f"Produkt {i}",
                category="möbler",
                acquisition_cost=100.0,
            )
            _create_order(engine, pid, sale_price=200.0 + i * 50)

        result = service.profitability_report("2026-06")

        assert result["total_products"] == 8
        assert len(result["top_5"]) == 5
        assert len(result["bottom_5"]) == 5
        assert result["top_5"][0]["profit"] >= result["top_5"][-1]["profit"]

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_by_category(self, _mock, service, engine):
        pid1 = _create_product(engine, category="möbler", acquisition_cost=100.0)
        pid2 = _create_product(engine, category="inredning", acquisition_cost=50.0)
        _create_order(engine, pid1, sale_price=500.0)
        _create_order(engine, pid2, sale_price=300.0)

        result = service.profitability_report("2026-06")

        assert "möbler" in result["by_category"]
        assert "inredning" in result["by_category"]
        assert result["by_category"]["möbler"]["profit"] == 400.0
        assert result["by_category"]["inredning"]["profit"] == 250.0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_by_source(self, _mock, service, engine):
        pid = _create_product(engine, source="loppis", acquisition_cost=50.0)
        _create_order(engine, pid, sale_price=300.0)

        result = service.profitability_report("2026-06")

        assert "loppis" in result["by_source"]
        assert result["by_source"]["loppis"]["count"] == 1

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_null_fields_default(self, _mock, service, engine):
        pid = _create_product(engine, category=None, source=None, acquisition_cost=None)
        _create_order(engine, pid, sale_price=300.0, platform_fee=None, shipping_cost=None)

        result = service.profitability_report("2026-06")

        assert "Okänd" in result["by_category"]
        assert "Okänd" in result["by_source"]
        assert result["top_5"][0]["acquisition_cost"] == 0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_logs_agent_action(self, _mock, service, engine):
        service.profitability_report("2026-06")

        with Session(engine) as session:
            actions = (
                session.query(AgentAction).filter_by(action_type="profitability_report").all()
            )
            assert len(actions) == 1


# ---------------------------------------------------------------------------
# inventory_report
# ---------------------------------------------------------------------------


class TestInventoryReport:
    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_empty_db(self, _mock, service):
        result = service.inventory_report()
        assert result["total_products"] == 0
        assert result["stock_value"] == 0
        assert result["stale_items"] == []

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_stock_value(self, _mock, service, engine):
        _create_product(engine, status="draft", acquisition_cost=100.0)
        _create_product(engine, status="listed", acquisition_cost=200.0)
        _create_product(engine, status="sold", acquisition_cost=500.0)

        result = service.inventory_report()

        assert result["stock_value"] == 300.0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_status_distribution(self, _mock, service, engine):
        _create_product(engine, status="draft")
        _create_product(engine, status="draft")
        _create_product(engine, status="sold")

        result = service.inventory_report()

        assert result["status_distribution"]["draft"] == 2
        assert result["status_distribution"]["sold"] == 1

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_aging_buckets(self, _mock, service, engine):
        with Session(engine) as session:
            # 3 days old → 0-7d
            p1 = Product(title="New", status="draft", created_at=FIXED_NOW - timedelta(days=3))
            # 10 days old → 8-14d
            p2 = Product(
                title="Week old", status="listed", created_at=FIXED_NOW - timedelta(days=10)
            )
            # 20 days old → 15-30d
            p3 = Product(title="Older", status="draft", created_at=FIXED_NOW - timedelta(days=20))
            # 45 days old → 30+d
            p4 = Product(title="Stale", status="draft", created_at=FIXED_NOW - timedelta(days=45))
            session.add_all([p1, p2, p3, p4])
            session.commit()

        result = service.inventory_report()

        assert result["aging_counts"]["0-7d"] == 1
        assert result["aging_counts"]["8-14d"] == 1
        assert result["aging_counts"]["15-30d"] == 1
        assert result["aging_counts"]["30+d"] == 1

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_stale_items_limit(self, _mock, service, engine):
        with Session(engine) as session:
            for i in range(15):
                p = Product(
                    title=f"Old item {i}",
                    status="draft",
                    acquisition_cost=10.0,
                    created_at=FIXED_NOW - timedelta(days=31 + i),
                )
                session.add(p)
            session.commit()

        result = service.inventory_report()

        assert len(result["stale_items"]) == 10
        # Sorted by days_in_stock descending
        assert (
            result["stale_items"][0]["days_in_stock"] >= result["stale_items"][-1]["days_in_stock"]
        )

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_logs_agent_action(self, _mock, service, engine):
        service.inventory_report()

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="inventory_report").all()
            assert len(actions) == 1


# ---------------------------------------------------------------------------
# period_comparison
# ---------------------------------------------------------------------------


class TestPeriodComparison:
    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_two_periods(self, _mock, service, engine):
        pid1 = _create_product(engine, acquisition_cost=50.0)
        pid2 = _create_product(engine, acquisition_cost=50.0)
        _create_order(engine, pid1, sale_price=500.0, ordered_at=datetime(2026, 6, 5))
        _create_order(engine, pid2, sale_price=300.0, ordered_at=datetime(2026, 5, 5))

        result = service.period_comparison("2026-06", "2026-05")

        assert result["period_a"]["revenue"] == 500.0
        assert result["period_b"]["revenue"] == 300.0
        assert result["deltas"]["revenue"]["diff"] == 200.0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_defaults_current_vs_previous(self, _mock, service, engine):
        result = service.period_comparison()

        assert result["period_a"]["period"] == "2026-06"
        assert result["period_b"]["period"] == "2026-05"

    @patch("storebot.tools.analytics.naive_now", return_value=datetime(2026, 1, 15))
    def test_defaults_january(self, _mock, service, engine):
        result = service.period_comparison()

        assert result["period_a"]["period"] == "2026-01"
        assert result["period_b"]["period"] == "2025-12"

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_only_period_a_defaults_period_b_to_previous(self, _mock, service, engine):
        """When only period_a is given, period_b defaults to the month before it."""
        result = service.period_comparison(period_a="2025-06")

        assert result["period_a"]["period"] == "2025-06"
        assert result["period_b"]["period"] == "2025-05"

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_only_period_a_january_wraps_year(self, _mock, service, engine):
        result = service.period_comparison(period_a="2026-01")

        assert result["period_a"]["period"] == "2026-01"
        assert result["period_b"]["period"] == "2025-12"

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_division_by_zero(self, _mock, service, engine):
        """When period B has zero revenue, percent_change should be None."""
        pid = _create_product(engine, acquisition_cost=50.0)
        _create_order(engine, pid, sale_price=500.0, ordered_at=datetime(2026, 6, 5))

        result = service.period_comparison("2026-06", "2026-05")

        assert result["deltas"]["revenue"]["percent_change"] is None

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_deltas_negative(self, _mock, service, engine):
        pid1 = _create_product(engine, acquisition_cost=50.0)
        pid2 = _create_product(engine, acquisition_cost=50.0)
        _create_order(engine, pid1, sale_price=200.0, ordered_at=datetime(2026, 6, 5))
        _create_order(engine, pid2, sale_price=500.0, ordered_at=datetime(2026, 5, 5))

        result = service.period_comparison("2026-06", "2026-05")

        assert result["deltas"]["revenue"]["diff"] == -300.0
        assert result["deltas"]["revenue"]["percent_change"] == -60.0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_logs_agent_action(self, _mock, service, engine):
        service.period_comparison("2026-06", "2026-05")

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="period_comparison").all()
            assert len(actions) == 1


# ---------------------------------------------------------------------------
# sourcing_analysis
# ---------------------------------------------------------------------------


class TestSourcingAnalysis:
    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_empty_db(self, _mock, service):
        result = service.sourcing_analysis("2026-06")
        assert result["channels"] == {}
        assert result["best_channel"] is None
        assert result["worst_channel"] is None

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_multiple_channels(self, _mock, service, engine):
        pid1 = _create_product(engine, source="loppis", acquisition_cost=50.0)
        pid2 = _create_product(engine, source="dödsbo", acquisition_cost=100.0)
        _create_order(engine, pid1, sale_price=500.0)
        _create_order(engine, pid2, sale_price=300.0)

        result = service.sourcing_analysis("2026-06")

        assert "loppis" in result["channels"]
        assert "dödsbo" in result["channels"]
        assert result["channels"]["loppis"]["items_sold"] == 1
        assert result["channels"]["dödsbo"]["items_sold"] == 1

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_roi_calculation(self, _mock, service, engine):
        pid = _create_product(engine, source="loppis", acquisition_cost=100.0)
        _create_order(engine, pid, sale_price=500.0)

        result = service.sourcing_analysis("2026-06")

        # profit = 500 - 100 = 400, ROI = 400/100*100 = 400%
        assert result["channels"]["loppis"]["roi_percent"] == 400.0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_best_worst_channel(self, _mock, service, engine):
        pid1 = _create_product(engine, source="loppis", acquisition_cost=50.0)
        pid2 = _create_product(engine, source="dödsbo", acquisition_cost=200.0)
        _create_order(engine, pid1, sale_price=500.0)
        _create_order(engine, pid2, sale_price=250.0)

        result = service.sourcing_analysis("2026-06")

        # loppis profit=450, dödsbo profit=50
        assert result["best_channel"] == "loppis"
        assert result["worst_channel"] == "dödsbo"

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_period_filter(self, _mock, service, engine):
        pid1 = _create_product(engine, source="loppis", acquisition_cost=50.0)
        pid2 = _create_product(engine, source="loppis", acquisition_cost=50.0)
        _create_order(engine, pid1, sale_price=500.0, ordered_at=datetime(2026, 6, 5))
        _create_order(engine, pid2, sale_price=300.0, ordered_at=datetime(2026, 5, 5))

        result = service.sourcing_analysis("2026-06")

        assert result["channels"]["loppis"]["items_sold"] == 1
        assert result["channels"]["loppis"]["total_revenue"] == 500.0

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_items_sourced_count(self, _mock, service, engine):
        with Session(engine) as session:
            p = Product(
                title="Sourced item",
                source="loppis",
                status="draft",
                created_at=datetime(2026, 6, 10),
            )
            session.add(p)
            session.commit()

        result = service.sourcing_analysis("2026-06")

        assert result["channels"]["loppis"]["items_sourced"] == 1

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_logs_agent_action(self, _mock, service, engine):
        service.sourcing_analysis("2026-06")

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="sourcing_analysis").all()
            assert len(actions) == 1


# ---------------------------------------------------------------------------
# Format methods
# ---------------------------------------------------------------------------


class TestFormatSummary:
    def test_basic_output(self, service):
        data = {
            "period": "2026-06",
            "revenue": 5000.0,
            "acquisition_cost": 1000.0,
            "platform_fees": 500.0,
            "shipping_cost": 200.0,
            "gross_profit": 3300.0,
            "margin_percent": 66.0,
            "items_sold": 10,
            "stock_count": 5,
            "avg_time_to_sale_days": 7.5,
        }
        text = service._format_summary(data)
        assert "Affärssammanfattning" in text
        assert "5000 kr" in text
        assert "66.0%" in text
        assert "7.5 dagar" in text

    def test_empty_data(self, service):
        data = {
            "period": "2026-06",
            "revenue": 0,
            "acquisition_cost": 0,
            "platform_fees": 0,
            "shipping_cost": 0,
            "gross_profit": 0,
            "margin_percent": 0.0,
            "items_sold": 0,
            "stock_count": 0,
            "avg_time_to_sale_days": None,
        }
        text = service._format_summary(data)
        assert "Affärssammanfattning" in text
        assert "Snittid" not in text


class TestFormatProfitability:
    def test_basic_output(self, service):
        data = {
            "period": "2026-06",
            "total_products": 3,
            "top_5": [{"title": "Byrå", "profit": 400}],
            "bottom_5": [],
            "by_category": {"möbler": {"count": 2, "revenue": 1000, "profit": 800}},
            "by_source": {},
        }
        text = service._format_profitability(data)
        assert "Lönsamhetsrapport" in text
        assert "Byrå" in text
        assert "möbler" in text

    def test_empty_data(self, service):
        data = {
            "period": "2026-06",
            "total_products": 0,
            "top_5": [],
            "bottom_5": [],
            "by_category": {},
            "by_source": {},
        }
        text = service._format_profitability(data)
        assert "Analyserade produkter: 0" in text


class TestFormatInventory:
    def test_basic_output(self, service):
        data = {
            "total_products": 10,
            "status_distribution": {"draft": 5, "listed": 3, "sold": 2},
            "stock_value": 5000.0,
            "aging_counts": {"0-7d": 3, "8-14d": 2, "15-30d": 2, "30+d": 1},
            "stale_items": [
                {"title": "Gammal byrå", "days_in_stock": 45, "acquisition_cost": 200.0}
            ],
        }
        text = service._format_inventory(data)
        assert "Lagerrapport" in text
        assert "5000 kr" in text
        assert "Gammal byrå" in text

    def test_empty_data(self, service):
        data = {
            "total_products": 0,
            "status_distribution": {},
            "stock_value": 0,
            "aging_counts": {"0-7d": 0, "8-14d": 0, "15-30d": 0, "30+d": 0},
            "stale_items": [],
        }
        text = service._format_inventory(data)
        assert "Totalt: 0 produkter" in text


class TestFormatComparison:
    def test_basic_output(self, service):
        data = {
            "period_a": {
                "period": "2026-06",
                "revenue": 5000.0,
                "gross_profit": 3000.0,
                "items_sold": 10,
                "margin_percent": 60.0,
            },
            "period_b": {
                "period": "2026-05",
                "revenue": 3000.0,
                "gross_profit": 1500.0,
                "items_sold": 5,
                "margin_percent": 50.0,
            },
            "deltas": {
                "revenue": {"diff": 2000.0, "percent_change": 66.7},
                "gross_profit": {"diff": 1500.0, "percent_change": 100.0},
                "items_sold": {"diff": 5, "percent_change": 100.0},
                "margin_percent": {"diff": 10.0, "percent_change": 20.0},
            },
        }
        text = service._format_comparison(data)
        assert "Periodjämförelse" in text
        assert "2026-06" in text
        assert "2026-05" in text


class TestFormatFullReport:
    def test_combined_fits_4000_chars(self, service):
        summary = {
            "period": "2026-06",
            "revenue": 5000.0,
            "acquisition_cost": 1000.0,
            "platform_fees": 500.0,
            "shipping_cost": 200.0,
            "gross_profit": 3300.0,
            "margin_percent": 66.0,
            "items_sold": 10,
            "stock_count": 5,
            "avg_time_to_sale_days": 7.5,
        }
        profitability = {
            "period": "2026-06",
            "total_products": 0,
            "top_5": [],
            "bottom_5": [],
            "by_category": {},
            "by_source": {},
        }
        inventory = {
            "total_products": 5,
            "status_distribution": {"draft": 3, "listed": 2},
            "stock_value": 500.0,
            "aging_counts": {"0-7d": 2, "8-14d": 1, "15-30d": 1, "30+d": 1},
            "stale_items": [],
        }

        text = service._format_full_report(summary, profitability, inventory)

        assert len(text) <= 4000
        assert "Affärssammanfattning" in text
        assert "Lönsamhetsrapport" in text
        assert "Lagerrapport" in text

    def test_truncates_long_report(self, service):
        summary = {
            "period": "2026-06",
            "revenue": 5000.0,
            "acquisition_cost": 1000.0,
            "platform_fees": 500.0,
            "shipping_cost": 200.0,
            "gross_profit": 3300.0,
            "margin_percent": 66.0,
            "items_sold": 10,
            "stock_count": 5,
            "avg_time_to_sale_days": 7.5,
        }
        profitability = {
            "period": "2026-06",
            "total_products": 100,
            "top_5": [{"title": f"Produkt {'X' * 200}", "profit": 100}] * 5,
            "bottom_5": [{"title": f"Produkt {'Y' * 200}", "profit": -100}] * 5,
            "by_category": {
                f"Kat {'Z' * 100}": {"count": 1, "revenue": 100, "profit": 50} for _ in range(20)
            },
            "by_source": {},
        }
        inventory = {
            "total_products": 50,
            "status_distribution": {"draft": 30, "listed": 20},
            "stock_value": 50000.0,
            "aging_counts": {"0-7d": 5, "8-14d": 5, "15-30d": 5, "30+d": 15},
            "stale_items": [
                {"title": f"Item {'A' * 100}", "days_in_stock": 40 + i, "acquisition_cost": 100.0}
                for i in range(10)
            ],
        }

        text = service._format_full_report(summary, profitability, inventory)

        assert len(text) <= 4000
        assert text.endswith("...avkortat")


class TestAgingBucketEdgeCases:
    def test_30_plus_bucket(self):
        from storebot.tools.analytics import _aging_bucket

        assert _aging_bucket(45) == "30+d"

    def test_boundary_30(self):
        from storebot.tools.analytics import _aging_bucket

        assert _aging_bucket(30) == "15-30d"


class TestProfitabilityReportNoProduct:
    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_order_without_product(self, _mock_now, service, engine):
        """Cover line 210: order.product is None → continue."""
        with Session(engine) as session:
            order = Order(
                product_id=None,
                platform="tradera",
                external_order_id="999",
                sale_price=100,
                status="shipped",
                ordered_at=FIXED_NOW - timedelta(days=1),
            )
            session.add(order)
            session.commit()

        result = service.profitability_report(period="2026-06")
        assert result["total_products"] == 0


class TestSourcingAnalysisEdgeCases:
    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_order_without_product_skipped(self, _mock_now, service, engine):
        """Cover line 365: order.product is None → continue."""
        with Session(engine) as session:
            order = Order(
                product_id=None,
                platform="tradera",
                external_order_id="888",
                sale_price=200,
                status="shipped",
                ordered_at=FIXED_NOW - timedelta(days=1),
            )
            session.add(order)
            session.commit()

        result = service.sourcing_analysis(period="2026-06")
        assert result["channels"] == {}

    @patch("storebot.tools.analytics.naive_now", return_value=FIXED_NOW)
    def test_sale_times_appended(self, _mock_now, service, engine):
        """Cover line 385: sale_times.append."""
        with Session(engine) as session:
            product = Product(
                title="Test",
                status="sold",
                source="tradera",
                acquisition_cost=100,
                created_at=FIXED_NOW - timedelta(days=10),
            )
            session.add(product)
            session.flush()
            listing = PlatformListing(
                product_id=product.id,
                platform="tradera",
                external_id="L1",
                status="sold",
                listing_type="auction",
                listing_title="T",
                listing_description="D",
                listed_at=FIXED_NOW - timedelta(days=5),
            )
            session.add(listing)
            order = Order(
                product_id=product.id,
                platform="tradera",
                external_order_id="O1",
                sale_price=200,
                status="shipped",
                ordered_at=FIXED_NOW - timedelta(days=1),
            )
            session.add(order)
            session.commit()

        result = service.sourcing_analysis(period="2026-06")
        ch = result["channels"]["tradera"]
        assert ch["avg_time_to_sale"] is not None


class TestTimeToSaleDaysNegative:
    def test_negative_days_returns_none(self, engine):
        from storebot.tools.analytics import _time_to_sale_days

        with Session(engine) as session:
            product = Product(title="Test", status="sold")
            session.add(product)
            session.flush()
            listing = PlatformListing(
                product_id=product.id,
                platform="tradera",
                external_id="X1",
                status="sold",
                listing_type="auction",
                listing_title="T",
                listing_description="D",
                listed_at=FIXED_NOW,
            )
            session.add(listing)
            order = Order(
                product_id=product.id,
                platform="tradera",
                external_order_id="O2",
                sale_price=100,
                status="shipped",
                ordered_at=FIXED_NOW - timedelta(days=2),
            )
            session.add(order)
            session.commit()

            result = _time_to_sale_days(session, order)
            assert result is None
