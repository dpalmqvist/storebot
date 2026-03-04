"""Proactive repricing service.

Generates price proposals from marketing recommendations, stores them
for human approval, and executes approved changes via Tradera SOAP.
"""

import logging
import math
from datetime import UTC, datetime

from sqlalchemy.orm import Session, selectinload

from storebot.db import PlatformListing, PriceProposal, Product
from storebot.tools.helpers import log_action

logger = logging.getLogger(__name__)

PROPOSAL_STATUSES = {"pending", "rejected", "executed", "failed"}
PROPOSAL_TYPES = {"reprice_lower", "reprice_raise"}


class RepricingService:
    """Generates, stores, and executes price proposals for active listings."""

    def __init__(self, engine, marketing=None, tradera=None):
        self.engine = engine
        self.marketing = marketing
        self.tradera = tradera

    def generate_proposals(self, skip_refresh: bool = False) -> dict:
        """Generate price proposals from marketing recommendations.

        Calls marketing.refresh_listing_stats() then marketing.get_recommendations(),
        filters for reprice_lower/reprice_raise, deduplicates, and creates proposals.

        Set *skip_refresh* to True when stats were already refreshed recently
        (e.g. by the daily listing report job) to avoid burning Tradera API quota.
        """
        if not self.marketing:
            return {"error": "MarketingService not available"}

        if not skip_refresh:
            try:
                self.marketing.refresh_listing_stats()
            except Exception:
                logger.exception("refresh_listing_stats failed during proposal generation")
                return {"error": "Failed to refresh listing stats"}
        recs_result = self.marketing.get_recommendations()
        recs = recs_result.get("recommendations", [])

        reprice_recs = [r for r in recs if r["type"] in ("reprice_lower", "reprice_raise")]
        if not reprice_recs:
            return {"new_proposals": 0, "proposals": []}

        with Session(self.engine) as session:
            # Find listings with existing pending proposals for dedup
            listing_ids = [r["listing_id"] for r in reprice_recs]
            pending_listing_ids = {
                row[0]
                for row in session.query(PriceProposal.listing_id)
                .filter(
                    PriceProposal.listing_id.in_(listing_ids),
                    PriceProposal.status == "pending",
                )
                .all()
            }

            # Bulk-load all candidate listings in one query (avoids N+1)
            candidate_ids = [
                r["listing_id"] for r in reprice_recs if r["listing_id"] not in pending_listing_ids
            ]
            listings_by_id = (
                {
                    lst.id: lst
                    for lst in session.query(PlatformListing)
                    .options(selectinload(PlatformListing.product))
                    .filter(
                        PlatformListing.id.in_(candidate_ids),
                        PlatformListing.status == "active",
                    )
                    .all()
                }
                if candidate_ids
                else {}
            )

            new_proposals = []
            for rec in reprice_recs:
                lid = rec["listing_id"]
                listing = listings_by_id.get(lid)
                if not listing:
                    continue

                # Use the price field that _execute_proposal will actually change
                if listing.listing_type == "buy_it_now":
                    current_price = listing.buy_it_now_price or 0
                else:
                    current_price = listing.start_price or 0
                if current_price <= 0:
                    continue

                product = listing.product
                suggested = self._compute_suggested_price(current_price, rec["type"], product)
                if suggested == int(current_price):
                    continue

                proposal = PriceProposal(
                    listing_id=lid,
                    proposal_type=rec["type"],
                    current_price=current_price,
                    suggested_price=float(suggested),
                    reason=rec.get("suggestion", ""),
                    status="pending",
                    details={
                        "recommendation": rec,
                        "listing_type": listing.listing_type,
                        "product_title": product.title if product else None,
                    },
                )
                session.add(proposal)
                new_proposals.append((proposal, listing, rec))

            # Single flush assigns IDs to all new proposals
            session.flush()
            proposals = [
                {
                    "proposal_id": p.id,
                    "listing_id": p.listing_id,
                    "listing_title": lst.listing_title,
                    "proposal_type": rec["type"],
                    "current_price": p.current_price,
                    "suggested_price": int(p.suggested_price),
                    "reason": p.reason,
                }
                for p, lst, rec in new_proposals
            ]

            log_action(
                session,
                "repricing",
                "generate_proposals",
                {"new_proposals": len(proposals)},
            )
            session.commit()

            return {"new_proposals": len(proposals), "proposals": proposals}

    def list_proposals(self, status: str | None = None) -> dict:
        """List price proposals, optionally filtered by status."""
        if status and status not in PROPOSAL_STATUSES:
            return {"error": f"Invalid status '{status}'. Valid: {sorted(PROPOSAL_STATUSES)}"}

        with Session(self.engine) as session:
            q = session.query(PriceProposal).options(
                selectinload(PriceProposal.listing).selectinload(PlatformListing.product)
            )
            if status:
                q = q.filter(PriceProposal.status == status)

            proposals = q.order_by(PriceProposal.created_at.desc()).all()

            return {
                "count": len(proposals),
                "proposals": [
                    {
                        "proposal_id": p.id,
                        "listing_id": p.listing_id,
                        "listing_title": p.listing.listing_title if p.listing else None,
                        "product_title": (
                            p.listing.product.title if p.listing and p.listing.product else None
                        ),
                        "proposal_type": p.proposal_type,
                        "current_price": p.current_price,
                        "suggested_price": p.suggested_price,
                        "reason": p.reason,
                        "status": p.status,
                        "created_at": p.created_at.isoformat() if p.created_at else None,
                        "decided_at": p.decided_at.isoformat() if p.decided_at else None,
                        "executed_at": p.executed_at.isoformat() if p.executed_at else None,
                        "execution_error": p.execution_error,
                    }
                    for p in proposals
                ],
            }

    def approve_proposal(self, proposal_id: int) -> dict:
        """Approve a pending proposal and immediately execute the price change."""
        with Session(self.engine) as session:
            proposal = session.get(
                PriceProposal, proposal_id, options=[selectinload(PriceProposal.listing)]
            )
            if proposal is None:
                return {"error": f"Proposal {proposal_id} not found"}

            if proposal.status != "pending":
                return {
                    "error": f"Cannot approve proposal with status '{proposal.status}', "
                    "must be 'pending'"
                }

            proposal.status = "approved"
            proposal.decided_at = datetime.now(UTC)

            result = self._execute_proposal(proposal, session)

            log_action(
                session,
                "repricing",
                "approve_proposal",
                {
                    "proposal_id": proposal_id,
                    "listing_id": proposal.listing_id,
                    "result": result,
                },
            )
            session.commit()

            return result

    def reject_proposal(self, proposal_id: int, reason: str | None = None) -> dict:
        """Reject a pending proposal."""
        with Session(self.engine) as session:
            proposal = session.get(PriceProposal, proposal_id)
            if proposal is None:
                return {"error": f"Proposal {proposal_id} not found"}

            if proposal.status != "pending":
                return {
                    "error": f"Cannot reject proposal with status '{proposal.status}', "
                    "must be 'pending'"
                }

            proposal.status = "rejected"
            proposal.decided_at = datetime.now(UTC)
            if reason:
                proposal.details = {**(proposal.details or {}), "rejection_reason": reason}

            log_action(
                session,
                "repricing",
                "reject_proposal",
                {"proposal_id": proposal_id, "reason": reason},
            )
            session.commit()

            return {
                "proposal_id": proposal_id,
                "status": "rejected",
                "reason": reason,
            }

    def _execute_proposal(self, proposal: PriceProposal, session: Session) -> dict:
        """Execute an approved price change via Tradera."""
        if not self.tradera:
            proposal.status = "failed"
            proposal.executed_at = datetime.now(UTC)
            proposal.execution_error = "Tradera client not configured"
            return {"error": proposal.execution_error}

        listing = proposal.listing
        if not listing or listing.status != "active":
            proposal.status = "failed"
            proposal.executed_at = datetime.now(UTC)
            proposal.execution_error = "Listing is no longer active"
            return {"error": proposal.execution_error}

        if not listing.external_id:
            proposal.status = "failed"
            proposal.executed_at = datetime.now(UTC)
            proposal.execution_error = "Listing has no external_id"
            return {"error": proposal.execution_error}

        # listing_type defaults to "auction" for older records without explicit type
        listing_type = listing.listing_type or "auction"
        suggested = int(proposal.suggested_price)

        if listing_type == "buy_it_now":
            tradera_result = self.tradera.set_prices(
                item_id=int(listing.external_id),
                listing_type="buy_it_now",
                buy_it_now_price=suggested,
            )
        else:
            tradera_result = self.tradera.set_prices(
                item_id=int(listing.external_id),
                listing_type="auction",
                start_price=suggested,
            )

        if "error" in tradera_result:
            proposal.status = "failed"
            proposal.execution_error = tradera_result["error"]
            proposal.executed_at = datetime.now(UTC)
            return {
                "proposal_id": proposal.id,
                "status": "failed",
                "error": tradera_result["error"],
            }

        # Success: update local listing prices
        proposal.status = "executed"
        proposal.executed_at = datetime.now(UTC)

        if listing_type == "buy_it_now":
            listing.buy_it_now_price = float(suggested)
        else:
            listing.start_price = float(suggested)

        return {
            "proposal_id": proposal.id,
            "listing_id": proposal.listing_id,
            "status": "executed",
            "old_price": proposal.current_price,
            "new_price": float(suggested),
        }

    @staticmethod
    def _compute_suggested_price(
        current_price: float,
        proposal_type: str,
        product: Product | None,
    ) -> int:
        """Compute a suggested price based on the proposal type.

        Lower: reduce 15%, round to nearest 10 kr, floor at acquisition_cost × 1.1.
        Raise: increase 20%, round to nearest 10 kr.
        """
        if proposal_type == "reprice_lower":
            raw = current_price * 0.85
            suggested = int(math.ceil(raw / 10) * 10)
            if product and product.acquisition_cost:
                # acquisition_cost is the gross (VAT-inclusive) purchase price
                floor = int(math.ceil(product.acquisition_cost * 1.1 / 10) * 10)
                suggested = max(suggested, floor)
        else:
            # reprice_raise
            raw = current_price * 1.20
            suggested = int(math.ceil(raw / 10) * 10)

        return max(suggested, 10)  # minimum 10 kr
