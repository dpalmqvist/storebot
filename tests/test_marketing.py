from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from storebot.db import (
    AgentAction,
    Base,
    ListingSnapshot,
    Order,
    PlatformListing,
    Product,
)
from storebot.tools.marketing import MarketingService

# Fixed reference time for deterministic tests
FIXED_NOW = datetime(2025, 6, 15, 12, 0, 0)


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def mock_tradera():
    return MagicMock()


@pytest.fixture
def service(engine, mock_tradera):
    return MarketingService(engine=engine, tradera=mock_tradera)


def _create_product(engine, title="Test produkt", category="möbler", **kwargs) -> int:
    with Session(engine) as session:
        product = Product(title=title, category=category, **kwargs)
        session.add(product)
        session.commit()
        return product.id


def _create_listing(
    engine,
    product_id,
    status="active",
    platform="tradera",
    external_id="12345",
    views=None,
    watchers=None,
    listed_at=None,
    ends_at=None,
    **kwargs,
) -> int:
    with Session(engine) as session:
        listing = PlatformListing(
            product_id=product_id,
            status=status,
            platform=platform,
            external_id=external_id,
            views=views,
            watchers=watchers,
            listed_at=listed_at,
            ends_at=ends_at,
            listing_title=kwargs.pop("listing_title", "Test annons"),
            **kwargs,
        )
        session.add(listing)
        session.commit()
        return listing.id


def _create_snapshot(
    engine, listing_id, views=0, watchers=0, bids=0, current_price=None, snapshot_at=None
) -> int:
    with Session(engine) as session:
        snapshot = ListingSnapshot(
            listing_id=listing_id,
            views=views,
            watchers=watchers,
            bids=bids,
            current_price=current_price,
            snapshot_at=snapshot_at or datetime.now(UTC),
        )
        session.add(snapshot)
        session.commit()
        return snapshot.id


def _create_order(engine, product_id, sale_price=500.0, **kwargs) -> int:
    with Session(engine) as session:
        order = Order(
            product_id=product_id,
            platform="tradera",
            sale_price=sale_price,
            **kwargs,
        )
        session.add(order)
        session.commit()
        return order.id


class TestRefreshListingStats:
    def test_refreshes_active_tradera_listing(self, service, engine, mock_tradera):
        pid = _create_product(engine)
        _create_listing(engine, pid, external_id="111")
        mock_tradera.get_item.return_value = {
            "id": 111,
            "views": 50,
            "watchers": 5,
            "bid_count": 2,
            "price": 300,
        }

        result = service.refresh_listing_stats()

        assert result["refreshed"] == 1
        assert result["listings"][0]["views"] == 50
        assert result["listings"][0]["watchers"] == 5
        assert result["listings"][0]["bids"] == 2

    def test_creates_snapshot(self, service, engine, mock_tradera):
        pid = _create_product(engine)
        _create_listing(engine, pid, external_id="111")
        mock_tradera.get_item.return_value = {
            "id": 111,
            "views": 50,
            "watchers": 5,
            "bid_count": 2,
            "price": 300,
        }

        service.refresh_listing_stats()

        with Session(engine) as session:
            snapshots = session.query(ListingSnapshot).all()
            assert len(snapshots) == 1
            assert snapshots[0].views == 50
            assert snapshots[0].watchers == 5
            assert snapshots[0].bids == 2

    def test_updates_listing_views_watchers(self, service, engine, mock_tradera):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid, external_id="111", views=0, watchers=0)
        mock_tradera.get_item.return_value = {
            "id": 111,
            "views": 100,
            "watchers": 10,
            "bid_count": 0,
            "price": 200,
        }

        service.refresh_listing_stats()

        with Session(engine) as session:
            listing = session.get(PlatformListing, lid)
            assert listing.views == 100
            assert listing.watchers == 10

    def test_single_listing_filter(self, service, engine, mock_tradera):
        pid = _create_product(engine)
        lid1 = _create_listing(engine, pid, external_id="111")
        _create_listing(engine, pid, external_id="222")
        mock_tradera.get_item.return_value = {
            "id": 111,
            "views": 50,
            "watchers": 5,
            "bid_count": 0,
            "price": 100,
        }

        result = service.refresh_listing_stats(listing_id=lid1)

        assert result["refreshed"] == 1
        mock_tradera.get_item.assert_called_once_with(111)

    def test_skips_non_tradera_listings(self, service, engine, mock_tradera):
        pid = _create_product(engine)
        _create_listing(engine, pid, platform="blocket", external_id="b1")

        result = service.refresh_listing_stats()

        assert result["refreshed"] == 0
        mock_tradera.get_item.assert_not_called()

    def test_skips_listings_without_external_id(self, service, engine, mock_tradera):
        pid = _create_product(engine)
        _create_listing(engine, pid, external_id=None)

        result = service.refresh_listing_stats()

        assert result["refreshed"] == 0

    def test_handles_tradera_error(self, service, engine, mock_tradera):
        pid = _create_product(engine)
        _create_listing(engine, pid, external_id="111")
        mock_tradera.get_item.return_value = {"error": "API error"}

        result = service.refresh_listing_stats()

        assert result["refreshed"] == 0

    def test_logs_agent_action(self, service, engine, mock_tradera):
        mock_tradera.get_item.return_value = {"error": "no items"}
        service.refresh_listing_stats()

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="refresh_stats").all()
            assert len(actions) == 1
            assert actions[0].agent_name == "marketing"

    def test_no_tradera_client(self, engine):
        svc = MarketingService(engine=engine, tradera=None)
        pid = _create_product(engine)
        _create_listing(engine, pid, external_id="111")

        result = svc.refresh_listing_stats()

        assert result["refreshed"] == 0


class TestAnalyzeListing:
    @patch("storebot.tools.marketing.naive_now", return_value=FIXED_NOW)
    def test_basic_analysis(self, _mock_now, service, engine):
        pid = _create_product(engine, acquisition_cost=100.0)
        lid = _create_listing(
            engine,
            pid,
            views=100,
            watchers=10,
            listed_at=FIXED_NOW - timedelta(days=5),
            ends_at=FIXED_NOW + timedelta(days=2),
        )
        _create_snapshot(engine, lid, views=100, watchers=10, bids=3, current_price=250.0)

        result = service.analyze_listing(lid)

        assert result["listing_id"] == lid
        assert result["views"] == 100
        assert result["watchers"] == 10
        assert result["bids"] == 3
        assert result["watcher_rate"] == 10.0
        assert result["bid_rate"] == 3.0
        assert result["days_active"] == 5
        assert result["days_remaining"] == 2
        assert result["current_price"] == 250.0
        assert result["potential_profit"] == 150.0

    def test_not_found(self, service):
        result = service.analyze_listing(999)

        assert "error" in result

    def test_zero_views(self, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid, views=0, watchers=0)

        result = service.analyze_listing(lid)

        assert result["watcher_rate"] == 0.0
        assert result["bid_rate"] == 0.0

    def test_no_snapshots(self, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(
            engine,
            pid,
            views=10,
            watchers=1,
            start_price=100.0,
        )

        result = service.analyze_listing(lid)

        assert result["bids"] == 0
        assert result["trend"] == "insufficient_data"
        assert result["current_price"] == 100.0

    def test_logs_agent_action(self, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid)

        service.analyze_listing(lid)

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="analyze_listing").all()
            assert len(actions) == 1


class TestComputeTrend:
    def test_improving(self, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid)
        now = datetime.now(UTC)
        _create_snapshot(engine, lid, views=100, snapshot_at=now - timedelta(hours=2))
        _create_snapshot(engine, lid, views=120, snapshot_at=now - timedelta(hours=1))
        _create_snapshot(engine, lid, views=150, snapshot_at=now)

        with Session(engine) as session:
            snaps = (
                session.query(ListingSnapshot)
                .filter(ListingSnapshot.listing_id == lid)
                .order_by(ListingSnapshot.snapshot_at.desc())
                .all()
            )
            assert service._compute_trend(snaps) == "improving"

    def test_declining(self, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid)
        now = datetime.now(UTC)
        _create_snapshot(engine, lid, views=150, snapshot_at=now - timedelta(hours=2))
        _create_snapshot(engine, lid, views=120, snapshot_at=now - timedelta(hours=1))
        _create_snapshot(engine, lid, views=100, snapshot_at=now)

        with Session(engine) as session:
            snaps = (
                session.query(ListingSnapshot)
                .filter(ListingSnapshot.listing_id == lid)
                .order_by(ListingSnapshot.snapshot_at.desc())
                .all()
            )
            assert service._compute_trend(snaps) == "declining"

    def test_stable(self, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid)
        now = datetime.now(UTC)
        _create_snapshot(engine, lid, views=100, snapshot_at=now - timedelta(hours=2))
        _create_snapshot(engine, lid, views=102, snapshot_at=now - timedelta(hours=1))
        _create_snapshot(engine, lid, views=101, snapshot_at=now)

        with Session(engine) as session:
            snaps = (
                session.query(ListingSnapshot)
                .filter(ListingSnapshot.listing_id == lid)
                .order_by(ListingSnapshot.snapshot_at.desc())
                .all()
            )
            assert service._compute_trend(snaps) == "stable"

    def test_insufficient_data(self, service):
        assert service._compute_trend([]) == "insufficient_data"
        assert service._compute_trend([MagicMock()]) == "insufficient_data"


class TestGetPerformanceReport:
    def test_empty_report(self, service):
        result = service.get_performance_report()

        assert result["active_count"] == 0
        assert result["total_views"] == 0
        assert result["best_listing"] is None
        assert result["worst_listing"] is None
        assert result["sales"]["count"] == 0

    def test_with_active_listings(self, service, engine):
        pid1 = _create_product(engine, title="Byrå", category="möbler")
        pid2 = _create_product(engine, title="Lampa", category="inredning")
        _create_listing(engine, pid1, views=100, watchers=10, external_id="1")
        _create_listing(engine, pid2, views=50, watchers=5, external_id="2")

        result = service.get_performance_report()

        assert result["active_count"] == 2
        assert result["total_views"] == 150
        assert result["total_watchers"] == 15
        assert result["best_listing"]["views"] == 100
        assert result["worst_listing"]["views"] == 50

    def test_with_sold_listings(self, service, engine):
        pid = _create_product(engine, acquisition_cost=100.0)
        now = datetime.now(UTC)
        _create_listing(
            engine,
            pid,
            status="sold",
            external_id="1",
            listed_at=now - timedelta(days=7),
            ends_at=now,
        )
        _create_order(engine, pid, sale_price=500.0)

        result = service.get_performance_report()

        assert result["sales"]["count"] == 1
        assert result["sales"]["total_revenue"] == 500.0
        assert result["sales"]["total_profit"] == 400.0
        assert result["sales"]["avg_time_to_sale_days"] == 7.0

    def test_category_breakdown(self, service, engine):
        pid1 = _create_product(engine, category="möbler")
        pid2 = _create_product(engine, category="möbler")
        _create_listing(engine, pid1, views=50, external_id="1")
        _create_listing(engine, pid2, views=30, external_id="2")

        result = service.get_performance_report()

        assert "möbler" in result["categories"]
        assert result["categories"]["möbler"]["count"] == 2
        assert result["categories"]["möbler"]["views"] == 80

    def test_funnel(self, service, engine):
        pid1 = _create_product(engine)
        pid2 = _create_product(engine)
        lid1 = _create_listing(engine, pid1, views=50, watchers=5, external_id="1")
        _create_listing(engine, pid2, views=20, watchers=0, external_id="2")
        _create_snapshot(engine, lid1, bids=2)

        result = service.get_performance_report()

        assert result["funnel"]["listed"] == 2
        assert result["funnel"]["with_watchers"] == 1
        assert result["funnel"]["with_bids"] == 1
        assert result["funnel"]["sold"] == 0

    def test_bulk_loading_multiple_sold_listings(self, service, engine):
        """Verify bulk-loaded orders and eager-loaded products work across multiple sold listings."""
        pid1 = _create_product(engine, title="Stol", category="möbler", acquisition_cost=50.0)
        pid2 = _create_product(engine, title="Bord", category="möbler", acquisition_cost=200.0)
        pid3 = _create_product(engine, title="Lampa", category="inredning", acquisition_cost=30.0)
        now = datetime.now(UTC)
        _create_listing(
            engine,
            pid1,
            status="sold",
            external_id="1",
            listed_at=now - timedelta(days=5),
            ends_at=now,
        )
        _create_listing(
            engine,
            pid2,
            status="sold",
            external_id="2",
            listed_at=now - timedelta(days=10),
            ends_at=now,
        )
        lid3 = _create_listing(
            engine, pid3, status="active", views=40, watchers=3, external_id="3"
        )
        _create_order(engine, pid1, sale_price=150.0)
        _create_order(engine, pid2, sale_price=800.0)
        _create_snapshot(engine, lid3, bids=1)

        result = service.get_performance_report()

        assert result["sales"]["count"] == 2
        assert result["sales"]["total_revenue"] == 950.0
        assert result["sales"]["total_profit"] == 700.0  # (150-50) + (800-200)
        assert result["categories"]["möbler"]["count"] == 2
        assert result["categories"]["möbler"]["sold"] == 2
        assert result["categories"]["inredning"]["count"] == 1
        assert result["funnel"]["with_bids"] == 1

    def test_logs_agent_action(self, service, engine):
        service.get_performance_report()

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="performance_report").all()
            assert len(actions) == 1


class TestGetRecommendations:
    def test_relist_ended_with_watchers(self, service, engine):
        pid = _create_product(engine)
        _create_listing(engine, pid, status="ended", watchers=5)

        result = service.get_recommendations()

        assert result["count"] == 1
        assert result["recommendations"][0]["type"] == "relist"
        assert result["recommendations"][0]["priority"] == "high"

    def test_reprice_lower_high_views_no_bids(self, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid, views=50, watchers=2)
        _create_snapshot(engine, lid, bids=0)

        result = service.get_recommendations()

        types = [r["type"] for r in result["recommendations"]]
        assert "reprice_lower" in types

    def test_reprice_raise_high_interest(self, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid, views=100, watchers=15)
        _create_snapshot(engine, lid, bids=5)

        result = service.get_recommendations()

        types = [r["type"] for r in result["recommendations"]]
        assert "reprice_raise" in types

    def test_improve_content_below_avg(self, service, engine):
        pid1 = _create_product(engine, category="möbler")
        pid2 = _create_product(engine, category="möbler")
        now = datetime.now(UTC)
        _create_listing(
            engine,
            pid1,
            views=100,
            external_id="1",
            listed_at=now - timedelta(days=5),
        )
        _create_listing(
            engine,
            pid2,
            views=10,
            external_id="2",
            listed_at=now - timedelta(days=5),
        )

        result = service.get_recommendations()

        types = [r["type"] for r in result["recommendations"]]
        assert "improve_content" in types

    def test_extend_duration_ending_soon(self, service, engine):
        pid = _create_product(engine)
        now = datetime.now(UTC)
        lid = _create_listing(
            engine,
            pid,
            views=30,
            watchers=3,
            listed_at=now - timedelta(days=6),
            ends_at=now + timedelta(hours=12),
        )
        _create_snapshot(engine, lid, bids=0)

        result = service.get_recommendations()

        types = [r["type"] for r in result["recommendations"]]
        assert "extend_duration" in types

    def test_category_opportunity(self, service, engine):
        pid1 = _create_product(engine, category="möbler")
        pid2 = _create_product(engine, category="möbler")
        pid3 = _create_product(engine, category="möbler")
        _create_listing(engine, pid1, views=10, external_id="1")
        _create_listing(engine, pid2, views=10, external_id="2")
        _create_listing(engine, pid3, views=100, external_id="3")

        result = service.get_recommendations()

        types = [r["type"] for r in result["recommendations"]]
        assert "category_opportunity" in types

    def test_no_recommendations(self, service, engine):
        pid = _create_product(engine)
        _create_listing(engine, pid, views=5, watchers=0)

        result = service.get_recommendations()

        assert result["count"] == 0

    def test_single_listing_filter(self, service, engine):
        pid = _create_product(engine)
        lid1 = _create_listing(engine, pid, status="ended", watchers=5, external_id="1")
        _create_listing(engine, pid, status="ended", watchers=5, external_id="2")

        result = service.get_recommendations(listing_id=lid1)

        assert all(r["listing_id"] == lid1 for r in result["recommendations"])

    def test_priority_sorting(self, service, engine):
        pid = _create_product(engine)
        # High priority: ended with watchers (relist)
        _create_listing(engine, pid, status="ended", watchers=5, external_id="1")
        # Lower priority: active with views but no bids (reprice_lower)
        lid2 = _create_listing(
            engine,
            pid,
            views=50,
            watchers=2,
            external_id="2",
        )
        _create_snapshot(engine, lid2, bids=0)

        result = service.get_recommendations()

        assert result["count"] >= 2
        priorities = [r["priority"] for r in result["recommendations"]]
        assert priorities[0] == "high"

    def test_logs_agent_action(self, service, engine):
        service.get_recommendations()

        with Session(engine) as session:
            actions = (
                session.query(AgentAction).filter_by(action_type="generate_recommendations").all()
            )
            assert len(actions) == 1

    def test_not_found_listing(self, service):
        result = service.get_recommendations(listing_id=999)

        assert result["count"] == 0


class TestFormatReport:
    def test_basic_format(self, service):
        report = {
            "active_count": 3,
            "total_views": 200,
            "total_watchers": 20,
            "best_listing": {"listing_id": 1, "title": "Fin byrå", "views": 100},
            "worst_listing": {"listing_id": 2, "title": "Gammal lampa", "views": 10},
            "sales": {
                "count": 1,
                "total_revenue": 500.0,
                "total_profit": 300.0,
                "avg_time_to_sale_days": 5.0,
            },
            "categories": {
                "möbler": {"count": 2, "views": 150, "sold": 1},
            },
            "funnel": {
                "listed": 3,
                "with_watchers": 2,
                "with_bids": 1,
                "sold": 1,
            },
        }

        text = service._format_report(report)

        assert "Marknadsföringsrapport" in text
        assert "Aktiva annonser: 3" in text
        assert "Fin byrå" in text
        assert "500 kr" in text
        assert "möbler" in text
        assert "Konverteringstratt" in text

    def test_empty_report(self, service):
        report = {
            "active_count": 0,
            "total_views": 0,
            "total_watchers": 0,
            "best_listing": None,
            "worst_listing": None,
            "sales": {
                "count": 0,
                "total_revenue": 0,
                "total_profit": 0,
                "avg_time_to_sale_days": None,
            },
            "categories": {},
            "funnel": {"listed": 0, "with_watchers": 0, "with_bids": 0, "sold": 0},
        }

        text = service._format_report(report)

        assert "Aktiva annonser: 0" in text
        assert "Fin byrå" not in text

    def test_single_active_hides_worst(self, service):
        report = {
            "active_count": 1,
            "total_views": 50,
            "total_watchers": 5,
            "best_listing": {"listing_id": 1, "title": "Byrå", "views": 50},
            "worst_listing": {"listing_id": 1, "title": "Byrå", "views": 50},
            "sales": {
                "count": 0,
                "total_revenue": 0,
                "total_profit": 0,
                "avg_time_to_sale_days": None,
            },
            "categories": {},
            "funnel": {"listed": 1, "with_watchers": 1, "with_bids": 0, "sold": 0},
        }

        text = service._format_report(report)

        assert "Bäst presterande" in text
        assert "Sämst presterande" not in text


class TestGetListingDashboard:
    @patch("storebot.tools.marketing.naive_now", return_value=FIXED_NOW)
    def test_no_active_listings(self, _mock_now, service):
        result = service.get_listing_dashboard()

        assert result["listings"] == []
        assert result["totals"]["active_count"] == 0
        assert result["date"] == "2025-06-15"

    @patch("storebot.tools.marketing.naive_now", return_value=FIXED_NOW)
    def test_with_listings_and_deltas(self, _mock_now, service, engine):
        pid = _create_product(engine, title="Ekfåtölj 1950-tal")
        lid = _create_listing(
            engine,
            pid,
            views=45,
            watchers=8,
            listing_title="Ekfåtölj 1950-tal",
            ends_at=FIXED_NOW + timedelta(days=4),
        )
        now = datetime.now(UTC)
        _create_snapshot(
            engine,
            lid,
            views=33,
            watchers=6,
            bids=2,
            current_price=1000.0,
            snapshot_at=now - timedelta(hours=24),
        )
        _create_snapshot(
            engine,
            lid,
            views=45,
            watchers=8,
            bids=3,
            current_price=1200.0,
            snapshot_at=now,
        )

        result = service.get_listing_dashboard()

        assert len(result["listings"]) == 1
        lst = result["listings"][0]
        assert lst["listing_id"] == lid
        assert lst["title"] == "Ekfåtölj 1950-tal"
        assert lst["views"] == 45
        assert lst["views_delta"] == 12
        assert lst["bids"] == 3
        assert lst["bids_delta"] == 1
        assert lst["watchers"] == 8
        assert lst["watchers_delta"] == 2
        assert lst["current_price"] == 1200.0
        assert lst["days_remaining"] == 4
        assert lst["watcher_rate"] == 17.8
        assert lst["bid_rate"] == 6.7

        assert result["totals"]["active_count"] == 1
        assert result["totals"]["total_views"] == 45

    @patch("storebot.tools.marketing.naive_now", return_value=FIXED_NOW)
    def test_first_day_deltas_are_none(self, _mock_now, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid, views=20, watchers=3)
        _create_snapshot(engine, lid, views=20, watchers=3, bids=1, current_price=500.0)

        result = service.get_listing_dashboard()

        lst = result["listings"][0]
        assert lst["views_delta"] is None
        assert lst["bids_delta"] is None
        assert lst["watchers_delta"] is None

    @patch("storebot.tools.marketing.naive_now", return_value=FIXED_NOW)
    def test_trend_from_snapshots(self, _mock_now, service, engine):
        pid = _create_product(engine)
        lid = _create_listing(engine, pid, views=150, watchers=10)
        now = datetime.now(UTC)
        _create_snapshot(engine, lid, views=100, snapshot_at=now - timedelta(hours=2))
        _create_snapshot(engine, lid, views=120, snapshot_at=now - timedelta(hours=1))
        _create_snapshot(engine, lid, views=150, snapshot_at=now)

        result = service.get_listing_dashboard()

        assert result["listings"][0]["trend"] == "improving"

    @patch("storebot.tools.marketing.naive_now", return_value=FIXED_NOW)
    def test_logs_agent_action(self, _mock_now, service, engine):
        service.get_listing_dashboard()

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="listing_dashboard").all()
            assert len(actions) == 1
            assert actions[0].agent_name == "marketing"

    @patch("storebot.tools.marketing.naive_now", return_value=FIXED_NOW)
    def test_excludes_non_tradera(self, _mock_now, service, engine):
        pid = _create_product(engine)
        _create_listing(engine, pid, platform="blocket", external_id="b1")

        result = service.get_listing_dashboard()

        assert result["totals"]["active_count"] == 0
