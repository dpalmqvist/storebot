import logging

import requests

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.blocket.se/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


class BlocketClient:
    """Client for Blocket's unofficial REST API.

    Read-only — useful for price research and sourcing.
    Bearer token extracted from browser session (expires, needs manual renewal).
    """

    def __init__(self, bearer_token: str):
        self.bearer_token = bearer_token

    def _headers(self) -> dict:
        headers = {"User-Agent": USER_AGENT}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    def _parse_item(self, doc: dict) -> dict:
        price_obj = doc.get("price") or {}
        image_obj = doc.get("image") or {}
        return {
            "id": str(doc.get("ad_id", doc.get("id", ""))),
            "title": doc.get("heading", ""),
            "price": price_obj.get("amount", 0),
            "currency": price_obj.get("currency_code", "SEK"),
            "url": doc.get("canonical_url", ""),
            "image_url": image_obj.get("url", ""),
            "location": doc.get("location", ""),
            "published": doc.get("timestamp"),
            "trade_type": doc.get("trade_type", ""),
        }

    def search(
        self,
        query: str,
        category: str | None = None,
        region: str | None = None,
        page: int = 1,
        sort: str = "PUBLISHED_DESC",
    ) -> dict:
        try:
            params: dict = {"q": query, "page": page, "sort": sort}
            if category:
                params["category"] = category
            if region:
                params["location"] = region

            resp = requests.get(
                SEARCH_URL,
                params=params,
                headers=self._headers(),
                timeout=15,
            )

            if resp.status_code == 401:
                return {
                    "error": "Blocket bearer token expired or invalid (401)",
                    "total": 0,
                    "items": [],
                }

            resp.raise_for_status()
            data = resp.json()

            metadata = data.get("metadata") or {}
            result_size = metadata.get("result_size") or {}
            total = result_size.get("match_count", 0)
            paging = metadata.get("paging") or {}

            docs = data.get("docs") or []

            return {
                "total": total,
                "page": paging.get("current", page),
                "total_pages": paging.get("last", 1),
                "items": [self._parse_item(doc) for doc in docs],
            }

        except requests.RequestException as e:
            logger.exception("Blocket search failed")
            return {"error": str(e), "total": 0, "items": []}
        except Exception as e:
            logger.exception("Blocket search failed")
            return {"error": str(e), "total": 0, "items": []}

    def get_ad(self, ad_id: str):
        # TODO: Implement REST ad detail fetch
        raise NotImplementedError("BlocketClient.get_ad not yet implemented")
