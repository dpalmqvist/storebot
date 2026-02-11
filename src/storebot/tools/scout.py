import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from storebot.db import AgentAction, Notification, SavedSearch, SeenItem

logger = logging.getLogger(__name__)

VALID_PLATFORMS = {"tradera", "blocket", "both"}
MAX_DIGEST_ITEMS_PER_SEARCH = 5


class ScoutService:
    """Scheduled sourcing searches with deduplication and digest delivery.

    Saves search criteria, runs them against Tradera/Blocket, tracks
    previously seen items, and produces a daily digest of new finds.
    """

    def __init__(self, engine, tradera=None, blocket=None):
        self.engine = engine
        self.tradera = tradera
        self.blocket = blocket

    def create_search(
        self,
        query: str,
        platform: str = "both",
        category: str | None = None,
        max_price: float | None = None,
        region: str | None = None,
        details: dict | None = None,
    ) -> dict:
        """Save a new search."""
        if platform not in VALID_PLATFORMS:
            return {
                "error": f"Invalid platform '{platform}'. Must be one of: {', '.join(sorted(VALID_PLATFORMS))}"
            }

        with Session(self.engine) as session:
            search = SavedSearch(
                query=query,
                platform=platform,
                category=category,
                max_price=max_price,
                region=region,
                details=details,
            )
            session.add(search)
            session.flush()

            action = AgentAction(
                agent_name="scout",
                action_type="create_search",
                details={"search_id": search.id, "query": query, "platform": platform},
                executed_at=datetime.now(UTC),
            )
            session.add(action)
            session.commit()

            return {
                "search_id": search.id,
                "query": search.query,
                "platform": search.platform,
                "category": search.category,
                "max_price": search.max_price,
                "region": search.region,
            }

    def list_searches(self, include_inactive: bool = False) -> dict:
        """List saved searches, ordered by created_at desc."""
        with Session(self.engine) as session:
            q = session.query(SavedSearch)
            if not include_inactive:
                q = q.filter(SavedSearch.is_active.is_(True))
            q = q.order_by(SavedSearch.created_at.desc())
            searches = q.all()

            return {
                "count": len(searches),
                "searches": [
                    {
                        "search_id": s.id,
                        "query": s.query,
                        "platform": s.platform,
                        "category": s.category,
                        "max_price": s.max_price,
                        "region": s.region,
                        "is_active": s.is_active,
                        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                    }
                    for s in searches
                ],
            }

    def update_search(self, search_id: int, **fields) -> dict:
        """Update allowed fields on a saved search."""
        allowed = {"query", "platform", "category", "max_price", "region", "details"}
        unknown = set(fields.keys()) - allowed
        if unknown:
            return {"error": f"Unknown fields: {', '.join(sorted(unknown))}"}

        if "platform" in fields and fields["platform"] not in VALID_PLATFORMS:
            return {
                "error": f"Invalid platform '{fields['platform']}'. Must be one of: {', '.join(sorted(VALID_PLATFORMS))}"
            }

        with Session(self.engine) as session:
            search = session.get(SavedSearch, search_id)
            if not search:
                return {"error": f"Search {search_id} not found"}

            for key, value in fields.items():
                setattr(search, key, value)

            action = AgentAction(
                agent_name="scout",
                action_type="update_search",
                details={"search_id": search_id, "fields": list(fields.keys())},
                executed_at=datetime.now(UTC),
            )
            session.add(action)
            session.commit()

            return {
                "search_id": search.id,
                "query": search.query,
                "platform": search.platform,
                "category": search.category,
                "max_price": search.max_price,
                "region": search.region,
            }

    def delete_search(self, search_id: int) -> dict:
        """Soft delete — sets is_active=False."""
        with Session(self.engine) as session:
            search = session.get(SavedSearch, search_id)
            if not search:
                return {"error": f"Search {search_id} not found"}

            search.is_active = False

            action = AgentAction(
                agent_name="scout",
                action_type="delete_search",
                details={"search_id": search_id, "query": search.query},
                executed_at=datetime.now(UTC),
            )
            session.add(action)
            session.commit()

            return {"search_id": search_id, "status": "deleted"}

    def run_search(self, search_id: int) -> dict:
        """Run a single saved search, deduplicate, return new items."""
        with Session(self.engine) as session:
            search = session.get(SavedSearch, search_id)
            if not search:
                return {"error": f"Search {search_id} not found"}

            if not search.is_active:
                return {"error": f"Search {search_id} is inactive"}

            seen_keys = {(item.platform, item.external_id) for item in search.seen_items}
            new_items = []

            platform_searches = []
            if search.platform in ("tradera", "both"):
                platform_searches.append(("tradera", self._search_tradera(search)))
            if search.platform in ("blocket", "both"):
                platform_searches.append(("blocket", self._search_blocket(search)))

            for platform, items in platform_searches:
                for item in items:
                    key = (platform, str(item["id"]))
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    session.add(
                        SeenItem(
                            saved_search_id=search.id,
                            platform=platform,
                            external_id=str(item["id"]),
                            title=item.get("title"),
                            price=item.get("price"),
                            url=item.get("url"),
                        )
                    )
                    new_items.append({**item, "platform": platform})

            search.last_run_at = datetime.now(UTC)
            session.commit()

            return {
                "search_id": search_id,
                "query": search.query,
                "new_items": new_items,
                "count": len(new_items),
            }

    def run_all_searches(self) -> dict:
        """Run all active searches and produce a digest."""
        with Session(self.engine) as session:
            searches = (
                session.query(SavedSearch)
                .filter(SavedSearch.is_active.is_(True))
                .order_by(SavedSearch.id)
                .all()
            )

            if not searches:
                return {"message": "Inga sparade sökningar", "results": [], "total_new": 0}

        results = []
        total_new = 0
        for search in searches:
            result = self.run_search(search.id)
            if "error" not in result:
                results.append(result)
                total_new += result["count"]

        digest = self._format_digest(results)

        if total_new > 0:
            with Session(self.engine) as session:
                notification = Notification(
                    type="scout_digest",
                    message_text=digest,
                )
                session.add(notification)
                session.commit()

        return {
            "results": results,
            "total_new": total_new,
            "digest": digest,
        }

    def _search_tradera(self, search: SavedSearch) -> list[dict]:
        """Search Tradera, return normalized items."""
        if not self.tradera:
            return []

        try:
            kwargs: dict = {"query": search.query}
            if search.category is not None:
                try:
                    kwargs["category"] = int(search.category)
                except (ValueError, TypeError):
                    pass
            if search.max_price is not None:
                kwargs["max_price"] = search.max_price

            result = self.tradera.search(**kwargs)
            return result.get("items", [])
        except Exception:
            logger.exception("Scout: Tradera search failed for query '%s'", search.query)
            return []

    def _search_blocket(self, search: SavedSearch) -> list[dict]:
        """Search Blocket, return normalized items."""
        if not self.blocket:
            return []

        try:
            kwargs: dict = {"query": search.query}
            if search.category is not None:
                kwargs["category"] = search.category
            if search.region is not None:
                kwargs["region"] = search.region

            result = self.blocket.search(**kwargs)
            return result.get("items", [])
        except Exception:
            logger.exception("Scout: Blocket search failed for query '%s'", search.query)
            return []

    def _format_digest(self, results: list[dict]) -> str:
        """Format a human-readable Swedish digest."""
        if not results or all(r["count"] == 0 for r in results):
            return "Inga nya fynd idag."

        lines = ["Dagens scoutrapport:\n"]
        for result in results:
            if result["count"] == 0:
                continue
            lines.append(f'Sökning: "{result["query"]}" — {result["count"]} nya')
            for item in result["new_items"][:MAX_DIGEST_ITEMS_PER_SEARCH]:
                platform = item.get("platform", "")
                title = item.get("title", "Okänd")
                price = item.get("price")
                price_str = f" — {price:.0f} kr" if price else ""
                url = item.get("url", "")
                url_str = f"\n  {url}" if url else ""
                lines.append(f"  [{platform}] {title}{price_str}{url_str}")
            if result["count"] > MAX_DIGEST_ITEMS_PER_SEARCH:
                remaining = result["count"] - MAX_DIGEST_ITEMS_PER_SEARCH
                lines.append(f"  ...och {remaining} till")
            lines.append("")

        return "\n".join(lines).strip()
