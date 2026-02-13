import logging
import statistics

from sqlalchemy.orm import Session

from storebot.tools.helpers import log_action

logger = logging.getLogger(__name__)


class PricingService:
    """Compound tool that searches Tradera + Blocket and computes price analysis.

    Composes the existing TraderaClient and BlocketClient to provide
    a single price_check operation with aggregated stats and a suggested range.
    """

    def __init__(self, tradera, blocket, engine=None):
        self.tradera = tradera
        self.blocket = blocket
        self.engine = engine

    def price_check(
        self,
        query: str,
        product_id: int | None = None,
        category: str | None = None,
    ) -> dict:
        tradera_result = self._search_tradera(query, category)
        blocket_result = self._search_blocket(query, category)

        tradera_comparables = [
            _normalize_comparable(item, "tradera") for item in tradera_result.get("items", [])
        ]
        blocket_comparables = [
            _normalize_comparable(item, "blocket") for item in blocket_result.get("items", [])
        ]

        tradera_prices = [c["price"] for c in tradera_comparables if c["price"] > 0]
        blocket_prices = [c["price"] for c in blocket_comparables if c["price"] > 0]
        all_prices = tradera_prices + blocket_prices

        tradera_stats = _compute_stats(tradera_prices)
        blocket_stats = _compute_stats(blocket_prices)
        combined_stats = _compute_stats(all_prices)
        suggested_range = _compute_suggested_range(all_prices)

        all_comparables = tradera_comparables + blocket_comparables

        analysis = {
            "query": query,
            "product_id": product_id,
            "tradera": {
                "count": len(tradera_comparables),
                "stats": tradera_stats,
                "error": tradera_result.get("error"),
            },
            "blocket": {
                "count": len(blocket_comparables),
                "stats": blocket_stats,
                "error": blocket_result.get("error"),
            },
            "combined_stats": combined_stats,
            "suggested_range": suggested_range,
            "comparables": all_comparables,
        }

        # Strip None error fields for cleaner output
        if analysis["tradera"]["error"] is None:
            del analysis["tradera"]["error"]
        if analysis["blocket"]["error"] is None:
            del analysis["blocket"]["error"]

        if product_id is not None and self.engine is not None:
            _log_pricing_action(self.engine, product_id, analysis)

        return analysis

    def _search_tradera(self, query: str, category: str | None) -> dict:
        try:
            kwargs: dict = {"query": query}
            if category is not None:
                try:
                    kwargs["category"] = int(category)
                except (ValueError, TypeError):
                    pass  # Skip category filter if not convertible to int
            return self.tradera.search(**kwargs)
        except Exception as e:
            logger.exception("Tradera search failed in price_check")
            return {"error": str(e), "items": []}

    def _search_blocket(self, query: str, category: str | None) -> dict:
        try:
            kwargs: dict = {"query": query}
            if category is not None:
                kwargs["category"] = category
            return self.blocket.search(**kwargs)
        except Exception as e:
            logger.exception("Blocket search failed in price_check")
            return {"error": str(e), "items": []}


def _normalize_comparable(item: dict, source: str) -> dict:
    return {
        "source": source,
        "id": str(item.get("id", "")),
        "title": item.get("title", ""),
        "price": item.get("price", 0),
        "url": item.get("url", ""),
    }


def _compute_stats(prices: list[float]) -> dict:
    if not prices:
        return {"min": 0, "max": 0, "median": 0, "mean": 0, "count": 0}

    return {
        "min": min(prices),
        "max": max(prices),
        "median": statistics.median(prices),
        "mean": round(statistics.mean(prices), 2),
        "count": len(prices),
    }


def _compute_suggested_range(prices: list[float]) -> dict:
    if not prices:
        return {"low": 0, "high": 0}

    if len(prices) < 4:
        return {"low": min(prices), "high": max(prices)}

    sorted_prices = sorted(prices)
    q1 = statistics.median(sorted_prices[: len(sorted_prices) // 2])
    q3 = statistics.median(sorted_prices[(len(sorted_prices) + 1) // 2 :])
    return {"low": round(q1, 2), "high": round(q3, 2)}


def _log_pricing_action(engine, product_id: int, analysis: dict) -> None:
    try:
        with Session(engine) as session:
            log_action(session, "pricing", "price_check", analysis, product_id=product_id)
            session.commit()
    except Exception:
        logger.exception("Failed to log pricing agent action")
