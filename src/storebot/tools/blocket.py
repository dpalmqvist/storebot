import logging

import requests

from storebot.retry import retry_on_transient

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.blocket.se/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON"
AD_URL = "https://www.blocket.se/recommerce/forsale/search/api/item/{ad_id}"

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

    @retry_on_transient()
    def _get(self, url: str, headers: dict, params: dict | None = None) -> requests.Response:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code >= 500:
            raise requests.HTTPError(response=resp)
        return resp

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

    def _parse_ad_detail(self, data: dict) -> dict:
        """Parse full ad detail — extends _parse_item with description, images, seller, etc."""
        base = self._parse_item(data)
        del base["image_url"]  # replaced by images list

        images = data.get("images") or []
        if not images:
            image_obj = data.get("image") or {}
            if image_obj.get("url"):
                images = [image_obj]

        location = data.get("location") or ""
        seller = data.get("seller") or {}
        parameters = data.get("parameters") or []

        base.update(
            {
                "description": data.get("body", ""),
                "images": [img.get("url", "") for img in images if img.get("url")],
                "location": location if isinstance(location, str) else location.get("name", ""),
                "category": data.get("category", ""),
                "seller": {"name": seller.get("name", ""), "id": str(seller.get("id", ""))},
                "parameters": {
                    p.get("label", ""): p.get("value", "") for p in parameters if p.get("label")
                },
            }
        )
        return base

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

            resp = self._get(SEARCH_URL, self._headers(), params=params)

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

        except Exception as e:
            logger.exception("Blocket search failed")
            return {"error": str(e), "total": 0, "items": []}

    def get_ad(self, ad_id: str) -> dict:
        """Fetch full details for a single Blocket ad."""
        try:
            resp = self._get(AD_URL.format(ad_id=ad_id), self._headers())

            if resp.status_code == 401:
                return {"error": "Blocket bearer token expired or invalid (401)"}

            if resp.status_code == 404:
                return {"error": f"Ad {ad_id} not found (404)"}

            resp.raise_for_status()
            return self._parse_ad_detail(resp.json())

        except Exception as e:
            logger.exception("Blocket get_ad failed for %s", ad_id)
            return {"error": str(e)}
