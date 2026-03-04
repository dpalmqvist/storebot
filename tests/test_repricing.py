"""Tests for RepricingService."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from storebot.db import PlatformListing, PriceProposal, Product
from storebot.tools.repricing import PROPOSAL_STATUSES, PROPOSAL_TYPES, RepricingService


@pytest.fixture
def product(engine):
    with Session(engine) as session:
        p = Product(
            title="Antik vas",
            status="listed",
            acquisition_cost=100.0,
        )
        session.add(p)
        session.commit()
        return p.id


@pytest.fixture
def active_listing(engine, product):
    with Session(engine) as session:
        listing = PlatformListing(
            product_id=product,
            platform="tradera",
            status="active",
            listing_type="auction",
            listing_title="Antik vas 1920-tal",
            start_price=500.0,
            external_id="12345",
        )
        session.add(listing)
        session.commit()
        return listing.id


@pytest.fixture
def bin_listing(engine, product):
    with Session(engine) as session:
        listing = PlatformListing(
            product_id=product,
            platform="tradera",
            status="active",
            listing_type="buy_it_now",
            listing_title="Antik vas köp nu",
            buy_it_now_price=800.0,
            external_id="67890",
        )
        session.add(listing)
        session.commit()
        return listing.id


@pytest.fixture
def marketing():
    m = MagicMock()
    m.refresh_listing_stats.return_value = {"refreshed": 0}
    return m


@pytest.fixture
def tradera():
    t = MagicMock()
    t.set_prices.return_value = {"item_id": 12345, "updated": True}
    return t


@pytest.fixture
def service(engine, marketing, tradera):
    return RepricingService(engine=engine, marketing=marketing, tradera=tradera)


class TestGenerateProposals:
    def test_creates_proposals_from_recommendations(self, service, marketing, active_listing):
        marketing.get_recommendations.return_value = {
            "recommendations": [
                {
                    "listing_id": active_listing,
                    "type": "reprice_lower",
                    "priority": "medium",
                    "suggestion": "Sänk priset — många visningar men inga bud.",
                    "reason": "20 visningar, 0 bud.",
                },
            ],
        }

        result = service.generate_proposals()

        assert "error" not in result
        assert result["new_proposals"] == 1
        assert len(result["proposals"]) == 1
        assert result["proposals"][0]["proposal_type"] == "reprice_lower"
        assert result["proposals"][0]["suggested_price"] < 500

    def test_skips_non_reprice_recommendations(self, service, marketing, active_listing):
        marketing.get_recommendations.return_value = {
            "recommendations": [
                {
                    "listing_id": active_listing,
                    "type": "relist",
                    "priority": "high",
                    "suggestion": "Lägg upp igen.",
                },
            ],
        }

        result = service.generate_proposals()
        assert result["new_proposals"] == 0

    def test_dedup_skips_existing_pending(self, service, marketing, engine, active_listing):
        # Create an existing pending proposal
        with Session(engine) as session:
            session.add(
                PriceProposal(
                    listing_id=active_listing,
                    proposal_type="reprice_lower",
                    current_price=500.0,
                    suggested_price=430.0,
                    reason="existing",
                    status="pending",
                )
            )
            session.commit()

        marketing.get_recommendations.return_value = {
            "recommendations": [
                {
                    "listing_id": active_listing,
                    "type": "reprice_lower",
                    "priority": "medium",
                    "suggestion": "Sänk priset.",
                },
            ],
        }

        result = service.generate_proposals()
        assert result["new_proposals"] == 0

    def test_no_marketing_returns_error(self, engine, tradera):
        service = RepricingService(engine=engine, marketing=None, tradera=tradera)
        result = service.generate_proposals()
        assert "error" in result

    def test_empty_recommendations(self, service, marketing):
        marketing.get_recommendations.return_value = {"recommendations": []}
        result = service.generate_proposals()
        assert result["new_proposals"] == 0

    def test_skip_refresh(self, service, marketing, active_listing):
        marketing.get_recommendations.return_value = {"recommendations": []}
        service.generate_proposals(skip_refresh=True)
        marketing.refresh_listing_stats.assert_not_called()

    def test_refresh_failure_returns_error(self, service, marketing):
        marketing.refresh_listing_stats.side_effect = RuntimeError("Tradera down")
        result = service.generate_proposals()
        assert "error" in result


class TestListProposals:
    def test_lists_all_proposals(self, service, engine, active_listing):
        with Session(engine) as session:
            session.add(
                PriceProposal(
                    listing_id=active_listing,
                    proposal_type="reprice_lower",
                    current_price=500.0,
                    suggested_price=430.0,
                    reason="test",
                    status="pending",
                )
            )
            session.commit()

        result = service.list_proposals()
        assert result["count"] == 1
        assert result["proposals"][0]["status"] == "pending"

    def test_filters_by_status(self, service, engine, active_listing):
        with Session(engine) as session:
            session.add(
                PriceProposal(
                    listing_id=active_listing,
                    proposal_type="reprice_lower",
                    current_price=500.0,
                    suggested_price=430.0,
                    reason="test",
                    status="pending",
                )
            )
            session.add(
                PriceProposal(
                    listing_id=active_listing,
                    proposal_type="reprice_raise",
                    current_price=500.0,
                    suggested_price=600.0,
                    reason="test2",
                    status="executed",
                )
            )
            session.commit()

        result = service.list_proposals(status="pending")
        assert result["count"] == 1
        assert result["proposals"][0]["status"] == "pending"

    def test_invalid_status_returns_error(self, service):
        result = service.list_proposals(status="INVALID")
        assert "error" in result


class TestApproveProposal:
    def test_approves_and_executes(self, service, engine, active_listing, tradera):
        with Session(engine) as session:
            proposal = PriceProposal(
                listing_id=active_listing,
                proposal_type="reprice_lower",
                current_price=500.0,
                suggested_price=430.0,
                reason="test",
                status="pending",
            )
            session.add(proposal)
            session.commit()
            pid = proposal.id

        result = service.approve_proposal(pid)

        assert "error" not in result
        assert result["status"] == "executed"
        tradera.set_prices.assert_called_once()

        # Verify DB state
        with Session(engine) as session:
            p = session.get(PriceProposal, pid)
            assert p.status == "executed"
            assert p.decided_at is not None
            assert p.executed_at is not None

    def test_approve_buy_it_now(self, service, engine, bin_listing, tradera):
        with Session(engine) as session:
            proposal = PriceProposal(
                listing_id=bin_listing,
                proposal_type="reprice_lower",
                current_price=800.0,
                suggested_price=680.0,
                reason="test",
                status="pending",
                details={"listing_type": "buy_it_now"},
            )
            session.add(proposal)
            session.commit()
            pid = proposal.id

        result = service.approve_proposal(pid)
        assert "error" not in result
        tradera.set_prices.assert_called_once_with(
            item_id=67890,
            listing_type="buy_it_now",
            buy_it_now_price=680,
        )

    def test_not_found(self, service):
        result = service.approve_proposal(9999)
        assert "error" in result

    def test_not_pending(self, service, engine, active_listing):
        with Session(engine) as session:
            proposal = PriceProposal(
                listing_id=active_listing,
                proposal_type="reprice_lower",
                current_price=500.0,
                suggested_price=430.0,
                reason="test",
                status="executed",
            )
            session.add(proposal)
            session.commit()
            pid = proposal.id

        result = service.approve_proposal(pid)
        assert "error" in result

    def test_listing_deactivated_after_proposal_created(self, service, engine, active_listing):
        """Listing became inactive between proposal creation and approval."""
        with Session(engine) as session:
            proposal = PriceProposal(
                listing_id=active_listing,
                proposal_type="reprice_lower",
                current_price=500.0,
                suggested_price=430.0,
                reason="test",
                status="pending",
            )
            session.add(proposal)
            session.commit()
            pid = proposal.id

        # Deactivate the listing
        with Session(engine) as session:
            listing = session.get(PlatformListing, active_listing)
            listing.status = "ended"
            session.commit()

        result = service.approve_proposal(pid)
        assert "error" in result
        assert "no longer active" in result["error"]

        with Session(engine) as session:
            p = session.get(PriceProposal, pid)
            assert p.status == "failed"
            assert p.executed_at is not None

    def test_tradera_error_marks_failed(self, service, engine, active_listing, tradera):
        tradera.set_prices.return_value = {"error": "Auction has bids"}

        with Session(engine) as session:
            proposal = PriceProposal(
                listing_id=active_listing,
                proposal_type="reprice_lower",
                current_price=500.0,
                suggested_price=430.0,
                reason="test",
                status="pending",
            )
            session.add(proposal)
            session.commit()
            pid = proposal.id

        result = service.approve_proposal(pid)
        assert result["status"] == "failed"

        with Session(engine) as session:
            p = session.get(PriceProposal, pid)
            assert p.status == "failed"
            assert p.execution_error == "Auction has bids"


class TestRejectProposal:
    def test_rejects_with_reason(self, service, engine, active_listing):
        with Session(engine) as session:
            proposal = PriceProposal(
                listing_id=active_listing,
                proposal_type="reprice_lower",
                current_price=500.0,
                suggested_price=430.0,
                reason="test",
                status="pending",
            )
            session.add(proposal)
            session.commit()
            pid = proposal.id

        result = service.reject_proposal(pid, reason="Vill inte sänka")
        assert result["status"] == "rejected"
        assert result["reason"] == "Vill inte sänka"

        with Session(engine) as session:
            p = session.get(PriceProposal, pid)
            assert p.status == "rejected"
            assert p.decided_at is not None

    def test_not_found(self, service):
        result = service.reject_proposal(9999)
        assert "error" in result

    def test_not_pending(self, service, engine, active_listing):
        with Session(engine) as session:
            proposal = PriceProposal(
                listing_id=active_listing,
                proposal_type="reprice_lower",
                current_price=500.0,
                suggested_price=430.0,
                reason="test",
                status="rejected",
            )
            session.add(proposal)
            session.commit()
            pid = proposal.id

        result = service.reject_proposal(pid)
        assert "error" in result


class TestComputeSuggestedPrice:
    def test_lower_reduces_15_percent(self):
        product = MagicMock(acquisition_cost=None)
        result = RepricingService._compute_suggested_price(1000, "reprice_lower", product)
        assert result == 850

    def test_lower_rounds_to_nearest_10(self):
        product = MagicMock(acquisition_cost=None)
        result = RepricingService._compute_suggested_price(333, "reprice_lower", product)
        # 333 * 0.85 = 283.05 → ceil(283.05 / 10) * 10 = 290
        assert result == 290

    def test_lower_floor_at_acquisition_cost(self):
        product = MagicMock(acquisition_cost=400.0)
        # 500 * 0.85 = 425, ceil(425/10)*10 = 430
        # floor = ceil(400 * 1.1 / 10) * 10 = 450 (float rounding: 400*1.1=440.00...06)
        result = RepricingService._compute_suggested_price(500, "reprice_lower", product)
        assert result == 450

    def test_raise_increases_20_percent(self):
        product = MagicMock(acquisition_cost=None)
        result = RepricingService._compute_suggested_price(1000, "reprice_raise", product)
        assert result == 1200

    def test_raise_rounds_to_nearest_10(self):
        product = MagicMock(acquisition_cost=None)
        result = RepricingService._compute_suggested_price(333, "reprice_raise", product)
        # 333 * 1.20 = 399.6 → ceil(399.6 / 10) * 10 = 400
        assert result == 400

    def test_minimum_10_kr(self):
        product = MagicMock(acquisition_cost=None)
        result = RepricingService._compute_suggested_price(5, "reprice_lower", product)
        assert result >= 10

    def test_no_product_for_lower(self):
        result = RepricingService._compute_suggested_price(1000, "reprice_lower", None)
        assert result == 850


class TestConstants:
    def test_proposal_statuses(self):
        assert PROPOSAL_STATUSES == {"pending", "approved", "rejected", "executed", "failed"}

    def test_proposal_types(self):
        assert PROPOSAL_TYPES == {"reprice_lower", "reprice_raise"}
