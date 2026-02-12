import logging
from datetime import UTC, datetime, timedelta

import requests
import zeep
from zeep.transports import Transport

from storebot.retry import retry_on_transient

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
    RESTRICTED_WSDL = "https://api.tradera.com/v3/restrictedservice.asmx?WSDL"

    def __init__(
        self,
        app_id: str,
        app_key: str,
        sandbox: bool = True,
        user_id: str = "",
        user_token: str = "",
        timeout: int = 30,
    ):
        self.app_id = app_id
        self.app_key = app_key
        self.sandbox = sandbox
        self.user_id = user_id
        self.user_token = user_token
        self.timeout = timeout
        self._search_client = None
        self._order_client = None
        self._public_client = None
        self._restricted_client = None

    def _make_transport(self) -> Transport:
        session = requests.Session()
        session.timeout = self.timeout
        return Transport(session=session, timeout=self.timeout)

    @property
    def search_client(self) -> zeep.Client:
        if self._search_client is None:
            self._search_client = zeep.Client(
                wsdl=self.SEARCH_WSDL, transport=self._make_transport()
            )
        return self._search_client

    @property
    def order_client(self) -> zeep.Client:
        if self._order_client is None:
            self._order_client = zeep.Client(
                wsdl=self.ORDER_WSDL, transport=self._make_transport()
            )
        return self._order_client

    @property
    def public_client(self) -> zeep.Client:
        if self._public_client is None:
            self._public_client = zeep.Client(
                wsdl=self.PUBLIC_WSDL, transport=self._make_transport()
            )
        return self._public_client

    @property
    def restricted_client(self) -> zeep.Client:
        if self._restricted_client is None:
            self._restricted_client = zeep.Client(
                wsdl=self.RESTRICTED_WSDL, transport=self._make_transport()
            )
        return self._restricted_client

    def _auth_headers(self, client, include_authorization: bool = False) -> dict:
        auth = client.get_element("{http://api.tradera.com}AuthenticationHeader")(
            AppId=int(self.app_id), AppKey=self.app_key
        )
        config = client.get_element("{http://api.tradera.com}ConfigurationHeader")(
            Sandbox=int(self.sandbox), MaxResultAge=0
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

    @retry_on_transient()
    def _search_api_call(self, params, headers):
        return self.search_client.service.SearchAdvanced(**params, **headers)

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

            response = self._search_api_call(params, self._auth_headers(self.search_client))

            errors = getattr(response, "Errors", None)
            if errors:
                return {"error": str(list(errors)), "total": 0, "items": []}

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

    @retry_on_transient()
    def _create_listing_api_call(self, params, headers):
        return self.restricted_client.service.AddItem(**params, **headers)

    def create_listing(
        self,
        title: str,
        description: str,
        category_id: int,
        duration_days: int = 7,
        listing_type: str = "auction",
        start_price: float | None = None,
        buy_it_now_price: float | None = None,
        shipping_cost: float | None = None,
        accepting_returns: bool = False,
    ) -> dict:
        """Create a listing on Tradera via RestrictedService AddItem."""
        try:
            item_type = 2 if listing_type == "buy_it_now" else 1  # 1=Auction, 2=BuyItNow

            params = {
                "Title": title,
                "Description": description,
                "CategoryId": int(category_id),
                "Duration": int(duration_days),
                "ItemType": item_type,
                "AcceptingReturns": accepting_returns,
            }
            if start_price is not None:
                params["StartPrice"] = int(start_price)
            if buy_it_now_price is not None:
                params["BuyItNowPrice"] = int(buy_it_now_price)
            if shipping_cost is not None:
                params["ShippingCost"] = int(shipping_cost)

            response = self._create_listing_api_call(
                params,
                self._auth_headers(self.restricted_client, include_authorization=True),
            )

            item_id = getattr(response, "ItemId", None)
            if item_id is None:
                return {"error": "Tradera API response missing ItemId"}
            return {
                "item_id": item_id,
                "url": f"https://www.tradera.com/item/{item_id}",
            }

        except Exception as e:
            logger.exception("Tradera create_listing failed")
            return {"error": str(e)}

    @retry_on_transient()
    def _upload_images_api_call(self, item_id, image_objects, headers):
        return self.restricted_client.service.AddItemImages(
            ItemId=int(item_id), Images=image_objects, **headers
        )

    def upload_images(self, item_id: int, images: list[tuple[str, str]]) -> dict:
        """Upload images for a listing on Tradera.

        Args:
            item_id: Tradera item ID.
            images: List of (base64_data, media_type) tuples.
        """
        try:
            image_objects = [
                {"Data": base64_data, "MediaType": media_type}
                for base64_data, media_type in images
            ]

            self._upload_images_api_call(
                item_id,
                image_objects,
                self._auth_headers(self.restricted_client, include_authorization=True),
            )

            return {"item_id": item_id, "images_uploaded": len(images)}

        except Exception as e:
            logger.exception("Tradera upload_images failed")
            return {"error": str(e)}

    @retry_on_transient()
    def _get_categories_api_call(self, parent_id, headers):
        return self.public_client.service.GetCategories(ParentCategoryId=int(parent_id), **headers)

    def get_categories(self, parent_id: int = 0) -> dict:
        """Get Tradera categories, optionally under a parent category."""
        try:
            response = self._get_categories_api_call(
                parent_id, self._auth_headers(self.public_client)
            )

            categories_obj = getattr(response, "Categories", None)
            if categories_obj and hasattr(categories_obj, "Category"):
                raw_cats = categories_obj.Category or []
            else:
                raw_cats = []

            return {
                "categories": [
                    {
                        "id": getattr(cat, "Id", None),
                        "name": getattr(cat, "Name", None),
                    }
                    for cat in raw_cats
                ],
            }

        except Exception as e:
            logger.exception("Tradera get_categories failed")
            return {"error": str(e)}

    @retry_on_transient()
    def _fetch_token_api_call(self, secret_key, headers):
        return self.public_client.service.FetchToken(userId=0, secretKey=secret_key, **headers)

    def fetch_token(self, secret_key: str) -> dict:
        """Fetch user token after consent flow.

        Calls PublicService.FetchToken with the secret key generated
        during the authorization URL step.
        """
        try:
            response = self._fetch_token_api_call(
                secret_key, self._auth_headers(self.public_client)
            )

            user_id = getattr(response, "UserId", None)
            token = getattr(response, "Token", None)
            expires = getattr(response, "ExpirationDate", None)
            if expires is not None:
                expires = str(expires)

            if user_id is None or token is None:
                return {"error": "FetchToken response missing UserId or Token"}

            return {
                "user_id": user_id,
                "token": token,
                "expires": expires,
            }

        except Exception as e:
            logger.exception("Tradera fetch_token failed")
            return {"error": str(e)}

    @retry_on_transient()
    def _get_orders_api_call(self, from_dt, to_dt, headers):
        return self.order_client.service.GetSellerOrders(DateFrom=from_dt, DateTo=to_dt, **headers)

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

            response = self._get_orders_api_call(
                from_dt,
                to_dt,
                self._auth_headers(self.order_client, include_authorization=True),
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

    @retry_on_transient()
    def _get_item_api_call(self, item_id, headers):
        return self.public_client.service.GetItem(ItemId=int(item_id), **headers)

    def get_item(self, item_id: int) -> dict:
        try:
            response = self._get_item_api_call(item_id, self._auth_headers(self.public_client))

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

    @retry_on_transient()
    def _mark_order_shipped_api_call(self, order_id, headers):
        return self.order_client.service.SetSellerOrderAsShipped(OrderId=int(order_id), **headers)

    def mark_order_shipped(self, order_id: int) -> dict:
        try:
            self._mark_order_shipped_api_call(
                order_id,
                self._auth_headers(self.order_client, include_authorization=True),
            )
            return {"order_id": order_id, "status": "shipped"}
        except Exception as e:
            logger.exception("Tradera mark_order_shipped failed")
            return {"error": str(e)}
