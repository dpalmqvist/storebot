import logging

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from storebot.db import ListingSnapshot, Order, PlatformListing
from storebot.tools.helpers import log_action, naive_now

logger = logging.getLogger(__name__)

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _listing_category(listing: PlatformListing) -> str:
    """Extract category from a listing's product, defaulting to 'Okänd'."""
    if listing.product and listing.product.category:
        return listing.product.category
    return "Okänd"


def _listing_summary(listing: PlatformListing) -> dict:
    """Summarize a listing for report output."""
    return {
        "listing_id": listing.id,
        "title": listing.listing_title,
        "views": listing.views or 0,
    }


class MarketingService:
    """Tracks listing performance, analyzes results, and generates recommendations."""

    def __init__(self, engine, tradera=None):
        self.engine = engine
        self.tradera = tradera

    def refresh_listing_stats(self, listing_id: int | None = None) -> dict:
        """Fetch current stats from Tradera for active listings and create snapshots."""
        with Session(self.engine) as session:
            q = session.query(PlatformListing).filter(
                PlatformListing.status == "active",
                PlatformListing.platform == "tradera",
                PlatformListing.external_id.isnot(None),
            )
            if listing_id is not None:
                q = q.filter(PlatformListing.id == listing_id)

            refreshed = []
            for listing in q.all():
                item_data = self._fetch_tradera_stats(listing.external_id)
                if item_data is None:
                    continue

                views = item_data.get("views", 0)
                watchers = item_data.get("watchers", 0)
                bids = item_data.get("bid_count", 0)
                current_price = item_data.get("price")

                listing.views = views
                listing.watchers = watchers

                snapshot = ListingSnapshot(
                    listing_id=listing.id,
                    views=views,
                    watchers=watchers,
                    bids=bids,
                    current_price=current_price,
                )
                session.add(snapshot)

                refreshed.append(
                    {
                        "listing_id": listing.id,
                        "external_id": listing.external_id,
                        "views": views,
                        "watchers": watchers,
                        "bids": bids,
                        "current_price": current_price,
                    }
                )

            log_action(
                session,
                "marketing",
                "refresh_stats",
                {"refreshed": len(refreshed), "listing_id": listing_id},
            )
            session.commit()

            return {"refreshed": len(refreshed), "listings": refreshed}

    def analyze_listing(self, listing_id: int) -> dict:
        """Analyze a single listing's performance metrics."""
        with Session(self.engine) as session:
            listing = session.get(PlatformListing, listing_id)
            if not listing:
                return {"error": f"Listing {listing_id} not found"}

            product = listing.product
            snapshots = (
                session.query(ListingSnapshot)
                .filter(ListingSnapshot.listing_id == listing_id)
                .order_by(ListingSnapshot.snapshot_at.desc())
                .all()
            )

            views = listing.views or 0
            watchers = listing.watchers or 0
            latest_bids = snapshots[0].bids if snapshots else 0

            watcher_rate = (watchers / views * 100) if views > 0 else 0.0
            bid_rate = (latest_bids / views * 100) if views > 0 else 0.0

            now = naive_now()
            days_active = (now - listing.listed_at).days if listing.listed_at else 0
            days_remaining = (listing.ends_at - now).days if listing.ends_at else None

            current_price = (
                snapshots[0].current_price
                if snapshots
                else (listing.buy_it_now_price or listing.start_price)
            )
            acquisition_cost = product.acquisition_cost if product else None
            potential_profit = None
            if current_price and acquisition_cost:
                potential_profit = current_price - acquisition_cost

            log_action(session, "marketing", "analyze_listing", {"listing_id": listing_id})
            session.commit()

            return {
                "listing_id": listing_id,
                "title": listing.listing_title,
                "status": listing.status,
                "views": views,
                "watchers": watchers,
                "bids": latest_bids,
                "watcher_rate": round(watcher_rate, 1),
                "bid_rate": round(bid_rate, 1),
                "trend": self._compute_trend(snapshots),
                "days_active": days_active,
                "days_remaining": days_remaining,
                "current_price": current_price,
                "acquisition_cost": acquisition_cost,
                "potential_profit": potential_profit,
                "snapshot_count": len(snapshots),
            }

    def get_performance_report(self) -> dict:
        """Aggregate performance report across all listings."""
        with Session(self.engine) as session:
            all_listings = (
                session.query(PlatformListing)
                .options(selectinload(PlatformListing.product))
                .filter(PlatformListing.status.in_(["active", "ended", "sold"]))
                .all()
            )
            active_listings = [lst for lst in all_listings if lst.status == "active"]
            sold_listings = [lst for lst in all_listings if lst.status == "sold"]

            total_views = sum((lst.views or 0) for lst in all_listings)
            total_watchers = sum((lst.watchers or 0) for lst in all_listings)

            best = (
                max(active_listings, key=lambda lst: lst.views or 0) if active_listings else None
            )
            worst = (
                min(active_listings, key=lambda lst: lst.views or 0) if active_listings else None
            )

            # Bulk-load orders for sold listings (first order per product wins)
            sold_product_ids = list({lst.product_id for lst in sold_listings})
            orders = (
                session.query(Order)
                .filter(Order.product_id.in_(sold_product_ids))
                .order_by(Order.id)
                .all()
            )
            order_by_product: dict[int, Order] = {}
            for o in orders:
                if o.product_id is not None:
                    order_by_product.setdefault(o.product_id, o)

            total_revenue = 0.0
            total_profit = 0.0
            sale_times = []
            for listing in sold_listings:
                order = order_by_product.get(listing.product_id)
                if order and order.sale_price:
                    total_revenue += order.sale_price
                    product = listing.product
                    if product and product.acquisition_cost:
                        total_profit += order.sale_price - product.acquisition_cost
                if listing.listed_at and listing.ends_at:
                    days = (listing.ends_at - listing.listed_at).days
                    if days > 0:
                        sale_times.append(days)

            avg_time_to_sale = round(sum(sale_times) / len(sale_times), 1) if sale_times else None

            categories: dict[str, dict] = {}
            for listing in all_listings:
                cat = _listing_category(listing)
                entry = categories.setdefault(cat, {"count": 0, "views": 0, "sold": 0})
                entry["count"] += 1
                entry["views"] += listing.views or 0
                if listing.status == "sold":
                    entry["sold"] += 1

            total_with_watchers = sum(1 for lst in all_listings if (lst.watchers or 0) > 0)
            # Single aggregate query for bid check
            listing_ids = [lst.id for lst in all_listings]
            ids_with_bids = {
                row[0]
                for row in session.query(ListingSnapshot.listing_id)
                .filter(
                    ListingSnapshot.listing_id.in_(listing_ids),
                    ListingSnapshot.bids > 0,
                )
                .distinct()
                .all()
            }
            total_with_bids = sum(1 for lst in all_listings if lst.id in ids_with_bids)

            log_action(
                session,
                "marketing",
                "performance_report",
                {"active": len(active_listings), "sold": len(sold_listings)},
            )
            session.commit()

            return {
                "active_count": len(active_listings),
                "total_views": total_views,
                "total_watchers": total_watchers,
                "best_listing": _listing_summary(best) if best else None,
                "worst_listing": _listing_summary(worst) if worst else None,
                "sales": {
                    "count": len(sold_listings),
                    "total_revenue": round(total_revenue, 2),
                    "total_profit": round(total_profit, 2),
                    "avg_time_to_sale_days": avg_time_to_sale,
                },
                "categories": categories,
                "funnel": {
                    "listed": len(all_listings),
                    "with_watchers": total_with_watchers,
                    "with_bids": total_with_bids,
                    "sold": len(sold_listings),
                },
            }

    def get_recommendations(self, listing_id: int | None = None) -> dict:
        """Generate rules-based recommendations for listings."""
        with Session(self.engine) as session:
            if listing_id is not None:
                listing = session.get(
                    PlatformListing,
                    listing_id,
                    options=[selectinload(PlatformListing.product)],
                )
                listings = [listing] if listing else []
            else:
                listings = (
                    session.query(PlatformListing)
                    .options(selectinload(PlatformListing.product))
                    .filter(PlatformListing.status.in_(["active", "ended"]))
                    .all()
                )

            category_avg_views = self._compute_category_avg_views(session)

            # Bulk-load latest snapshot per listing
            listing_ids = [lst.id for lst in listings]
            snaps_by_listing = self._bulk_recent_snapshots(session, listing_ids)

            recommendations = []
            for listing in listings:
                snaps = snaps_by_listing.get(listing.id, [])
                snapshot = snaps[0] if snaps else None
                recommendations.extend(
                    self._evaluate_listing(listing, category_avg_views, snapshot)
                )

            recommendations.sort(key=lambda r: PRIORITY_ORDER.get(r["priority"], 3))

            log_action(
                session,
                "marketing",
                "generate_recommendations",
                {"listing_id": listing_id, "recommendation_count": len(recommendations)},
            )
            session.commit()

            return {
                "recommendations": recommendations,
                "count": len(recommendations),
            }

    def get_listing_dashboard(self) -> dict:
        """Per-listing dashboard with daily deltas for all active Tradera listings."""
        now = naive_now()
        with Session(self.engine) as session:
            active = (
                session.query(PlatformListing)
                .filter(
                    PlatformListing.status == "active",
                    PlatformListing.platform == "tradera",
                )
                .all()
            )

            active_ids = [lst.id for lst in active]
            snaps_by_listing = self._bulk_recent_snapshots(session, active_ids, limit=3)

            listings = []
            for listing in active:
                snapshots = snaps_by_listing.get(listing.id, [])

                latest = snapshots[0] if snapshots else None
                previous = snapshots[1] if len(snapshots) >= 2 else None

                views = latest.views if latest else (listing.views or 0)
                bids = latest.bids if latest else 0  # PlatformListing has no bids column
                watchers = latest.watchers if latest else (listing.watchers or 0)
                current_price = latest.current_price if latest else None

                views_delta = (views - previous.views) if previous else None
                bids_delta = (bids - previous.bids) if previous else None
                watchers_delta = (watchers - previous.watchers) if previous else None

                watcher_rate = round(watchers / views * 100, 1) if views > 0 else 0.0
                bid_rate = round(bids / views * 100, 1) if views > 0 else 0.0
                days_remaining = (listing.ends_at - now).days if listing.ends_at else None
                trend = self._compute_trend(snapshots)

                listings.append(
                    {
                        "listing_id": listing.id,
                        "title": listing.listing_title,
                        "views": views,
                        "views_delta": views_delta,
                        "bids": bids,
                        "bids_delta": bids_delta,
                        "watchers": watchers,
                        "watchers_delta": watchers_delta,
                        "current_price": current_price,
                        "days_remaining": days_remaining,
                        "watcher_rate": watcher_rate,
                        "bid_rate": bid_rate,
                        "trend": trend,
                    }
                )

            listings.sort(
                key=lambda x: x["days_remaining"] if x["days_remaining"] is not None else 999
            )

            log_action(
                session,
                "marketing",
                "listing_dashboard",
                {"active_count": len(listings)},
            )
            session.commit()

            return {
                "date": now.strftime("%Y-%m-%d"),
                "listings": listings,
                "totals": {
                    "active_count": len(listings),
                    "total_views": sum(lst["views"] for lst in listings),
                    "total_bids": sum(lst["bids"] for lst in listings),
                    "total_watchers": sum(lst["watchers"] for lst in listings),
                },
            }

    def _format_report(self, report: dict) -> str:
        """Format a performance report as Swedish human-readable text."""
        lines = ["Marknadsföringsrapport\n"]

        lines.append(f"Aktiva annonser: {report['active_count']}")
        lines.append(f"Totala visningar: {report['total_views']}")
        lines.append(f"Totala bevakare: {report['total_watchers']}")

        best = report.get("best_listing")
        if best:
            lines.append(f"\nBäst presterande: {best['title']} ({best['views']} visningar)")

        worst = report.get("worst_listing")
        if worst and report["active_count"] > 1:
            lines.append(f"Sämst presterande: {worst['title']} ({worst['views']} visningar)")

        sales = report.get("sales", {})
        if sales.get("count", 0) > 0:
            lines.append("\nFörsäljning:")
            lines.append(f"  Antal sålda: {sales['count']}")
            lines.append(f"  Total intäkt: {sales['total_revenue']:.0f} kr")
            lines.append(f"  Total vinst: {sales['total_profit']:.0f} kr")
            if sales.get("avg_time_to_sale_days") is not None:
                lines.append(f"  Snittid till försäljning: {sales['avg_time_to_sale_days']} dagar")

        categories = report.get("categories", {})
        if categories:
            lines.append("\nKategorier:")
            for cat, data in categories.items():
                lines.append(
                    f"  {cat}: {data['count']} annonser, "
                    f"{data['views']} visningar, {data['sold']} sålda"
                )

        funnel = report.get("funnel", {})
        if funnel.get("listed", 0) > 0:
            lines.append("\nKonverteringstratt:")
            lines.append(f"  Annonserade: {funnel['listed']}")
            lines.append(f"  Med bevakare: {funnel['with_watchers']}")
            lines.append(f"  Med bud: {funnel['with_bids']}")
            lines.append(f"  Sålda: {funnel['sold']}")

        return "\n".join(lines)

    def _fetch_tradera_stats(self, external_id: str) -> dict | None:
        """Fetch item stats from Tradera."""
        if not self.tradera:
            return None
        try:
            result = self.tradera.get_item(int(external_id))
            if "error" in result:
                logger.warning(
                    "Failed to fetch stats for item %s: %s",
                    external_id,
                    result["error"],
                    extra={"job_name": "marketing_refresh"},
                )
                return None
            return result
        except Exception:
            logger.exception(
                "Failed to fetch Tradera stats for item %s",
                external_id,
                extra={"job_name": "marketing_refresh"},
            )
            return None

    def _compute_trend(self, snapshots: list[ListingSnapshot]) -> str:
        """Compute trend from last 3 snapshots."""
        if len(snapshots) < 2:
            return "insufficient_data"

        recent = snapshots[:3]
        view_deltas = [a.views - b.views for a, b in zip(recent, recent[1:])]
        avg_delta = sum(view_deltas) / len(view_deltas)

        if avg_delta > 5:
            return "improving"
        if avg_delta < -5:
            return "declining"
        return "stable"

    def _compute_category_avg_views(self, session: Session) -> dict[str, float]:
        """Compute average views per category for active listings."""
        listings = (
            session.query(PlatformListing)
            .options(selectinload(PlatformListing.product))
            .filter(PlatformListing.status == "active")
            .all()
        )

        category_views: dict[str, list[int]] = {}
        for listing in listings:
            cat = _listing_category(listing)
            category_views.setdefault(cat, []).append(listing.views or 0)

        return {cat: sum(views) / len(views) for cat, views in category_views.items()}

    @staticmethod
    def _bulk_recent_snapshots(
        session: Session, listing_ids: list[int], limit: int = 1
    ) -> dict[int, list[ListingSnapshot]]:
        """Load the N most recent snapshots per listing in a single query.

        Requires SQLite >= 3.25 (window functions).
        """
        if not listing_ids:
            return {}
        subq = (
            session.query(
                ListingSnapshot.id,
                func.row_number()
                .over(
                    partition_by=ListingSnapshot.listing_id,
                    order_by=[ListingSnapshot.snapshot_at.desc(), ListingSnapshot.id.desc()],
                )
                .label("rn"),
            )
            .filter(ListingSnapshot.listing_id.in_(listing_ids))
            .subquery()
        )
        snapshots = (
            session.query(ListingSnapshot)
            .join(subq, ListingSnapshot.id == subq.c.id)
            .filter(subq.c.rn <= limit)
            .all()
        )
        result: dict[int, list[ListingSnapshot]] = {}
        for s in snapshots:
            result.setdefault(s.listing_id, []).append(s)
        for snaps in result.values():
            snaps.sort(key=lambda s: s.snapshot_at, reverse=True)
        return result

    def _evaluate_listing(
        self,
        listing: PlatformListing,
        category_avg_views: dict[str, float],
        latest_snapshot: ListingSnapshot | None = None,
    ) -> list[dict]:
        """Evaluate a single listing and return applicable recommendations."""
        views = listing.views or 0
        watchers = listing.watchers or 0

        bids = latest_snapshot.bids if latest_snapshot else 0

        now = naive_now()
        days_active = (now - listing.listed_at).days if listing.listed_at else 0
        days_remaining = (listing.ends_at - now).days if listing.ends_at else None

        cat = _listing_category(listing)
        avg_views = category_avg_views.get(cat, 0)

        recs = []
        for check in (
            self._check_relist,
            self._check_reprice_lower,
            self._check_reprice_raise,
            self._check_improve_content,
            self._check_extend_duration,
            self._check_category_opportunity,
        ):
            rec = check(listing, views, watchers, bids, days_active, days_remaining, avg_views)
            if rec:
                recs.append(rec)
        return recs

    @staticmethod
    def _check_relist(listing, views, watchers, bids, days_active, days_remaining, avg_views):
        if listing.status == "ended" and watchers > 0:
            return {
                "listing_id": listing.id,
                "type": "relist",
                "priority": "high",
                "suggestion": "Lägg upp igen \u2014 annonsen hade bevakare men såldes inte.",
                "reason": f"{watchers} bevakare visar intresse.",
            }

    @staticmethod
    def _check_reprice_lower(
        listing, views, watchers, bids, days_active, days_remaining, avg_views
    ):
        if listing.status == "active" and views >= 20 and bids == 0:
            return {
                "listing_id": listing.id,
                "type": "reprice_lower",
                "priority": "medium",
                "suggestion": "Överväg att sänka priset \u2014 många visningar men inga bud.",
                "reason": f"{views} visningar, 0 bud.",
            }

    @staticmethod
    def _check_reprice_raise(
        listing, views, watchers, bids, days_active, days_remaining, avg_views
    ):
        if listing.status == "active" and views > 0:
            watcher_rate = watchers / views
            if watcher_rate > 0.1 and bids >= 3:
                return {
                    "listing_id": listing.id,
                    "type": "reprice_raise",
                    "priority": "low",
                    "suggestion": "Startpriset kan vara för lågt \u2014 högt intresse och flera bud.",
                    "reason": f"{watchers} bevakare ({watcher_rate:.0%} av visningar), {bids} bud.",
                }

    @staticmethod
    def _check_improve_content(
        listing, views, watchers, bids, days_active, days_remaining, avg_views
    ):
        if listing.status == "active" and days_active >= 3 and avg_views > 0:
            if views < avg_views * 0.5:
                return {
                    "listing_id": listing.id,
                    "type": "improve_content",
                    "priority": "medium",
                    "suggestion": "Förbättra titel eller bilder \u2014 visningarna ligger under snittet.",
                    "reason": f"{views} visningar vs kategorisnitt {avg_views:.0f}.",
                }

    @staticmethod
    def _check_extend_duration(
        listing, views, watchers, bids, days_active, days_remaining, avg_views
    ):
        if (
            listing.status == "active"
            and days_remaining is not None
            and days_remaining <= 1
            and watchers > 0
            and bids == 0
        ):
            return {
                "listing_id": listing.id,
                "type": "extend_duration",
                "priority": "high",
                "suggestion": "Förläng annonsen \u2014 den slutar snart och har bevakare.",
                "reason": f"Slutar om {days_remaining} dag(ar), {watchers} bevakare, 0 bud.",
            }

    @staticmethod
    def _check_category_opportunity(
        listing, views, watchers, bids, days_active, days_remaining, avg_views
    ):
        if listing.status == "active" and avg_views > 0 and views > avg_views * 2:
            return {
                "listing_id": listing.id,
                "type": "category_opportunity",
                "priority": "low",
                "suggestion": "Populär kategori \u2014 överväg att lägga upp fler liknande.",
                "reason": f"{views} visningar, kategorisnittet är {avg_views:.0f}.",
            }
