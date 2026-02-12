import logging
from datetime import UTC, datetime, timedelta

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
    ORDER_WSDL = "https://api.tradera.com/v3/orderservice.asmx?WSDL"
    PUBLIC_WSDL = "https://api.tradera.com/v3/publicservice.asmx?WSDL"

    def __init__(
        self,
        app_id: str,
        app_key: str,
        sandbox: bool = True,
        user_id: str = "",
        user_token: str = "",
    ):
        self.app_id = app_id
        self.app_key = app_key
        self.sandbox = sandbox
        self.user_id = user_id
        self.user_token = user_token
        self._search_client = None
        self._order_client = None
        self._public_client = None

    @property
    def search_client(self) -> zeep.Client:
        if self._search_client is None:
            self._search_client = zeep.Client(wsdl=self.SEARCH_WSDL)
        return self._search_client

    @property
    def order_client(self) -> zeep.Client:
        if self._order_client is None:
            self._order_client = zeep.Client(wsdl=self.ORDER_WSDL)
        return self._order_client

    @property
    def public_client(self) -> zeep.Client:
        if self._public_client is None:
            self._public_client = zeep.Client(wsdl=self.PUBLIC_WSDL)
        return self._public_client

    def _soap_headers(self) -> dict:
        auth = self.search_client.get_element("{http://api.tradera.com}AuthenticationHeader")(
            AppId=int(self.app_id), AppKey=self.app_key
        )
        config = self.search_client.get_element("{http://api.tradera.com}ConfigurationHeader")(
            Sandbox=1 if self.sandbox else 0
        )
        return {"_soapheaders": [auth, config]}

    def _auth_headers(self, client, include_authorization: bool = False) -> dict:
        auth = client.get_element("{http://api.tradera.com}AuthenticationHeader")(
            AppId=int(self.app_id), AppKey=self.app_key
        )
        config = client.get_element("{http://api.tradera.com}ConfigurationHeader")(
            Sandbox=1 if self.sandbox else 0
        )
        headers = [auth, config]
        if include_authorization:
            authz = client.get_element("{http://api.tradera.com}AuthorizationHeader")(
                UserId=int(self.user_id), Token=self.user_token
            )
            headers.append(authz)
        return {"_soapheaders": headers}

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

    def get_orders(self, from_date: str | None = None, to_date: str | None = None) -> dict:
        try:
            if to_date:
                to_dt = datetime.fromisoformat(to_date)
            else:
                to_dt = datetime.now(UTC)
            if from_date:
                from_dt = datetime.fromisoformat(from_date)
            else:
                from_dt = to_dt - timedelta(days=30)

            response = self.order_client.service.GetSellerOrders(
                DateFrom=from_dt,
                DateTo=to_dt,
                **self._auth_headers(self.order_client, include_authorization=True),
            )

            orders_obj = getattr(response, "Orders", None)
            if orders_obj and hasattr(orders_obj, "SellerOrder"):
                raw_orders = orders_obj.SellerOrder or []
            else:
                raw_orders = []

            orders = []
            for order in raw_orders:
                items = []
                order_items = getattr(order, "Items", None)
                if order_items and hasattr(order_items, "SellerOrderItem"):
                    for item in order_items.SellerOrderItem or []:
                        items.append(
                            {
                                "item_id": getattr(item, "ItemId", None),
                                "title": getattr(item, "Title", None),
                                "price": getattr(item, "Price", 0),
                                "quantity": getattr(item, "Quantity", 1),
                            }
                        )

                payments = []
                order_payments = getattr(order, "Payments", None)
                if order_payments and hasattr(order_payments, "Payment"):
                    for payment in order_payments.Payment or []:
                        payments.append(
                            {
                                "type": getattr(payment, "PaymentType", None),
                                "amount": getattr(payment, "Amount", 0),
                            }
                        )

                orders.append(
                    {
                        "order_id": getattr(order, "OrderId", None),
                        "buyer_name": getattr(order, "BuyerName", None),
                        "buyer_address": getattr(order, "BuyerAddress", None),
                        "sub_total": getattr(order, "SubTotal", 0),
                        "shipping_cost": getattr(order, "ShippingCost", 0),
                        "items": items,
                        "payments": payments,
                    }
                )

            return {"orders": orders, "count": len(orders)}

        except Exception as e:
            logger.exception("Tradera get_orders failed")
            return {"error": str(e), "orders": [], "count": 0}

    def get_item(self, item_id: int) -> dict:
        try:
            response = self.public_client.service.GetItem(
                ItemId=int(item_id),
                **self._auth_headers(self.public_client),
            )

            end_date = getattr(response, "EndDate", None)
            if end_date is not None:
                end_date = str(end_date)

            return {
                "id": getattr(response, "Id", item_id),
                "title": getattr(response, "Title", None),
                "description": getattr(response, "Description", None),
                "price": getattr(response, "BuyItNowPrice", 0)
                or getattr(response, "MaxBid", 0)
                or 0,
                "status": getattr(response, "Status", None),
                "end_date": end_date,
                "url": getattr(response, "ItemUrl", None),
                "views": getattr(response, "TotalViews", 0) or 0,
                "watchers": getattr(response, "NumberOfWatchers", 0) or 0,
                "bid_count": getattr(response, "BidCount", 0) or 0,
            }

        except Exception as e:
            logger.exception("Tradera get_item failed")
            return {"error": str(e)}

    def mark_order_shipped(self, order_id: int) -> dict:
        try:
            self.order_client.service.SetSellerOrderAsShipped(
                OrderId=int(order_id),
                **self._auth_headers(self.order_client, include_authorization=True),
            )
            return {"order_id": order_id, "status": "shipped"}
        except Exception as e:
            logger.exception("Tradera mark_order_shipped failed")
            return {"error": str(e)}
