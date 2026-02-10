import logging

import zeep

logger = logging.getLogger(__name__)


class TraderaClient:
    """Client for Tradera SOAP API via zeep.

    Register at the Tradera Developer Program to get app_id and app_key.
    WSDL endpoints:
      - PublicService:     https://api.tradera.com/v3/publicservice.asmx?WSDL
      - RestrictedService: https://api.tradera.com/v3/restrictedservice.asmx?WSDL
      - SearchService:     https://api.tradera.com/v3/searchservice.asmx?WSDL
      - OrderService:      https://api.tradera.com/v3/orderservice.asmx?WSDL
    """

    SEARCH_WSDL = "https://api.tradera.com/v3/searchservice.asmx?WSDL"

    def __init__(self, app_id: str, app_key: str, sandbox: bool = True):
        self.app_id = app_id
        self.app_key = app_key
        self.sandbox = sandbox
        self._search_client = None

    @property
    def search_client(self) -> zeep.Client:
        if self._search_client is None:
            self._search_client = zeep.Client(wsdl=self.SEARCH_WSDL)
        return self._search_client

    def _soap_headers(self) -> dict:
        auth = self.search_client.get_element("{http://api.tradera.com}AuthenticationHeader")(
            AppId=int(self.app_id), AppKey=self.app_key
        )
        config = self.search_client.get_element("{http://api.tradera.com}ConfigurationHeader")(
            Sandbox=1 if self.sandbox else 0
        )
        return {"_soapheaders": [auth, config]}

    def _parse_item(self, item) -> dict:
        buy_now = getattr(item, "BuyItNowPrice", 0) or 0
        max_bid = getattr(item, "MaxBid", 0) or 0
        price = max(buy_now, max_bid)

        image_links = getattr(item, "ImageLinks", None)
        if image_links and hasattr(image_links, "string"):
            image_url = image_links.string[0] if image_links.string else None
        else:
            image_url = getattr(item, "ThumbnailLink", None)

        end_date = getattr(item, "EndDate", None)
        if end_date is not None:
            end_date = str(end_date)

        return {
            "id": item.Id,
            "title": item.ShortDescription,
            "price": price,
            "bid_count": getattr(item, "BidCount", 0) or 0,
            "url": getattr(item, "ItemUrl", None),
            "image_url": image_url,
            "end_date": end_date,
            "seller": getattr(item, "SellerAlias", None),
            "item_type": getattr(item, "ItemType", None),
        }

    def search(
        self,
        query: str,
        category: int | None = None,
        max_price: float | None = None,
        page: int = 1,
        items_per_page: int = 50,
    ) -> dict:
        try:
            params = {
                "SearchWords": query,
                "CategoryId": category or 0,
                "PageNumber": page,
                "ItemsPerPage": items_per_page,
                "OrderBy": "Relevance",
            }
            if max_price is not None:
                params["PriceMaximum"] = int(max_price)

            response = self.search_client.service.SearchAdvanced(
                **params,
                **self._soap_headers(),
            )

            errors = getattr(response, "Errors", None)
            if errors:
                error_list = list(errors) if errors else []
                if error_list:
                    return {"error": str(error_list), "total": 0, "items": []}

            items_obj = getattr(response, "Items", None)
            if items_obj and hasattr(items_obj, "SearchItem"):
                raw_items = items_obj.SearchItem or []
            else:
                raw_items = []

            return {
                "total": getattr(response, "TotalNumberOfItems", 0) or 0,
                "page": page,
                "total_pages": getattr(response, "TotalNumberOfPages", 0) or 0,
                "items": [self._parse_item(item) for item in raw_items],
            }

        except Exception as e:
            logger.exception("Tradera search failed")
            return {"error": str(e), "total": 0, "items": []}

    def create_listing(
        self,
        title: str,
        description: str,
        price: float,
        category_id: int | None = None,
        images: list[str] | None = None,
    ):
        # TODO: Implement via RestrictedService AddItem
        raise NotImplementedError("TraderaClient.create_listing not yet implemented")

    def get_orders(self, status: str | None = None):
        # TODO: Implement via OrderService
        raise NotImplementedError("TraderaClient.get_orders not yet implemented")

    def get_item(self, item_id: int):
        # TODO: Implement via PublicService GetItem
        raise NotImplementedError("TraderaClient.get_item not yet implemented")
