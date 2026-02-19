import logging
from datetime import UTC, datetime, timedelta

import requests
import zeep
from lxml import etree
from zeep.plugins import HistoryPlugin
from zeep.transports import Transport

from storebot.retry import retry_on_transient

logger = logging.getLogger(__name__)


def _parse_int_config(value: str, name: str) -> int:
    """Parse a string config value as an integer, raising ValueError with a clear message."""
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be an integer, got: {value!r}")


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
        self._app_id = _parse_int_config(app_id, "TRADERA_APP_ID")
        self._user_id = _parse_int_config(user_id, "TRADERA_USER_ID") if user_id else 0
        self.app_key = app_key
        self.sandbox = sandbox
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
            AppId=self._app_id, AppKey=self.app_key
        )
        config = client.get_element("{http://api.tradera.com}ConfigurationHeader")(
            Sandbox=int(self.sandbox), MaxResultAge=0
        )
        headers = [auth, config]
        if include_authorization:
            authz = client.get_element("{http://api.tradera.com}AuthorizationHeader")(
                UserId=self._user_id, Token=self.user_token
            )
            headers.append(authz)
        return {"_soapheaders": headers}

    @staticmethod
    def _soap_list(container, attr: str) -> list:
        """Extract a list from a SOAP container object (e.g. Items.SearchItem)."""
        if container and hasattr(container, attr):
            return getattr(container, attr) or []
        return []

    def _parse_item(self, item) -> dict:
        buy_now = float(getattr(item, "BuyItNowPrice", 0) or 0)
        max_bid = float(getattr(item, "MaxBid", 0) or 0)
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
        return self.search_client.service.SearchAdvanced(request=params, **headers)

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

            raw_items = self._soap_list(getattr(response, "Items", None), "SearchItem")

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
        return self.restricted_client.service.AddItem(itemRequest=params, **headers)

    def create_listing(
        self,
        title: str,
        description: str,
        category_id: int,
        duration_days: int = 7,
        listing_type: str = "auction",
        start_price: float | None = None,
        buy_it_now_price: float | None = None,
        reserve_price: float | None = None,
        shipping_cost: float | None = None,
        shipping_options: list[dict] | None = None,
        shipping_condition: str | None = None,
        auto_commit: bool = True,
        item_attributes: list[int] | None = None,
        attribute_values: list[dict] | None = None,
        accepted_bidder_id: int = 1,
    ) -> dict:
        """Create a listing on Tradera via RestrictedService AddItem."""
        try:
            # GetItemTypes returns: 1=Auktion, 3=Endast Köp Nu, 4=Shop artikel
            item_type_id = 3 if listing_type == "buy_it_now" else 1

            params = {
                "Title": title,
                "Description": description,
                "CategoryId": int(category_id),
                "Duration": int(duration_days),
                "Restarts": 0,
                "ItemType": item_type_id,
                "AutoCommit": auto_commit,
                "AcceptedBidderId": int(accepted_bidder_id),
            }
            if start_price is not None:
                params["StartPrice"] = int(start_price)
            if reserve_price is not None:
                params["ReservePrice"] = int(reserve_price)
            if buy_it_now_price is not None:
                params["BuyItNowPrice"] = int(buy_it_now_price)
            if shipping_options:
                params["ShippingOptions"] = {
                    "ItemShipping": [self._build_shipping_option(opt) for opt in shipping_options]
                }
            elif shipping_cost is not None:
                params["ShippingOptions"] = {"ItemShipping": [{"Cost": int(shipping_cost)}]}

            if shipping_condition is not None:
                params["ShippingCondition"] = shipping_condition

            params["ItemAttributes"] = item_attributes or []
            if attribute_values:
                for av in attribute_values:
                    if "id" not in av or "values" not in av:
                        return {
                            "error": f"Invalid attribute_values entry: missing 'id' or 'values' in {av}"
                        }
                    if not isinstance(av["values"], list):
                        return {
                            "error": f"Invalid attribute_values: 'values' must be a list in {av}"
                        }
                term_vals = []
                number_vals = []
                for av in attribute_values:
                    entry = {
                        "Id": int(av["id"]),
                        "Name": av.get("name", ""),
                        "Values": av["values"],
                    }
                    if av.get("type") == "number":
                        number_vals.append(entry)
                    else:
                        term_vals.append(entry)
                av_params = {}
                if term_vals:
                    av_params["TermAttributeValues"] = term_vals
                if number_vals:
                    av_params["NumberAttributeValues"] = number_vals
                if av_params:
                    params["AttributeValues"] = av_params

            logger.debug(
                "AddItem params (pre-SOAP): %s",
                {k: v for k, v in params.items() if k != "Description"},
            )

            history = HistoryPlugin()
            self.restricted_client.plugins.append(history)
            try:
                response = self._create_listing_api_call(
                    params,
                    self._auth_headers(self.restricted_client, include_authorization=True),
                )
            finally:
                self.restricted_client.plugins.remove(history)
                self._log_soap_exchange(history, "AddItem")

            request_id = getattr(response, "RequestId", None)
            item_id = getattr(response, "ItemId", None)
            if item_id is None:
                return {"error": "Tradera API response missing ItemId"}
            return {
                "request_id": request_id,
                "item_id": item_id,
                "url": f"https://www.tradera.com/item/{item_id}",
            }

        except Exception as e:
            logger.exception("Tradera create_listing failed")
            return {"error": str(e)}

    @staticmethod
    def _soap_body_xml(envelope) -> str | None:
        """Extract the SOAP Body from an envelope, omitting auth headers."""
        body = envelope.find("{http://schemas.xmlsoap.org/soap/envelope/}Body")
        if body is None:
            return None
        return etree.tostring(body, pretty_print=True).decode()

    def _log_soap_exchange(self, history: HistoryPlugin, operation: str) -> None:
        """Log the SOAP Body (no auth headers) from a HistoryPlugin."""
        for label, attr in (("request", "last_sent"), ("response", "last_received")):
            try:
                env = getattr(history, attr, {}).get("envelope")
                if env is not None:
                    body_xml = self._soap_body_xml(env)
                    if body_xml:
                        logger.debug("%s SOAP %s:\n%s", operation, label, body_xml)
            except Exception:
                logger.debug("%s: could not extract %s XML", operation, label)

    _MEDIA_TYPE_TO_FORMAT = {
        "image/jpeg": "Jpeg",
        "image/png": "Png",
        "image/gif": "Gif",
    }

    @retry_on_transient()
    def _upload_image_api_call(self, request_id, image_data, image_format, headers):
        return self.restricted_client.service.AddItemImage(
            requestId=int(request_id),
            imageData=image_data,
            imageFormat=image_format,
            hasMega=True,
            **headers,
        )

    def upload_images(self, request_id: int, images: list[tuple[str, str]]) -> dict:
        """Upload images for a listing on Tradera.

        Args:
            request_id: RequestId from AddItem response.
            images: List of (base64_data, media_type) tuples.
        """
        try:
            headers = self._auth_headers(self.restricted_client, include_authorization=True)
            for base64_data, media_type in images:
                image_format = self._MEDIA_TYPE_TO_FORMAT.get(media_type, "Jpeg")
                self._upload_image_api_call(request_id, base64_data, image_format, headers)

            return {"request_id": request_id, "images_uploaded": len(images)}

        except Exception as e:
            logger.exception("Tradera upload_images failed")
            return {"error": str(e)}

    @retry_on_transient()
    def _commit_listing_api_call(self, request_id, headers):
        return self.restricted_client.service.AddItemCommit(requestId=int(request_id), **headers)

    def commit_listing(self, request_id: int) -> dict:
        """Commit a listing after uploading images (required when AutoCommit=False)."""
        if request_id is None:
            return {"error": "request_id is required"}
        try:
            self._commit_listing_api_call(
                request_id,
                self._auth_headers(self.restricted_client, include_authorization=True),
            )
            return {"request_id": request_id, "committed": True}
        except Exception as e:
            logger.exception("Tradera commit_listing failed")
            return {"error": str(e)}

    @staticmethod
    def _flatten_categories(cats, parent_id=None, parent_path="", depth=0):
        """Recursively flatten a nested SOAP category tree into a list of dicts."""
        result = []
        for cat in cats or []:
            cat_id = getattr(cat, "Id", None)
            if cat_id is None:
                continue
            name = getattr(cat, "Name", None) or ""
            path = f"{parent_path} > {name}" if parent_path else name
            result.append(
                {
                    "tradera_id": cat_id,
                    "parent_tradera_id": parent_id,
                    "name": name,
                    "path": path,
                    "depth": depth,
                }
            )
            children = getattr(cat, "Category", None) or []
            if children:
                if not isinstance(children, list):
                    children = [children]
                result.extend(TraderaClient._flatten_categories(children, cat_id, path, depth + 1))
        return result

    @retry_on_transient()
    def _get_categories_api_call(self, headers):
        return self.public_client.service.GetCategories(**headers)

    def get_categories(self) -> dict:
        """Get full Tradera category hierarchy as a flat list with paths."""
        try:
            response = self._get_categories_api_call(self._auth_headers(self.public_client))

            raw_cats = self._soap_list(getattr(response, "Categories", None), "Category")

            return {
                "categories": self._flatten_categories(raw_cats),
            }

        except Exception as e:
            logger.exception("Tradera get_categories failed")
            return {"error": str(e)}

    def sync_categories_to_db(self, engine) -> int:
        """Fetch full category tree and upsert into tradera_categories. Returns count."""
        from sqlalchemy.orm import Session

        from storebot.db import TraderaCategory

        result = self.get_categories()
        if "error" in result:
            raise RuntimeError(result["error"])

        categories = result["categories"]
        now = datetime.now(UTC)
        with Session(engine) as session:
            # Chunk the IN() query to stay within SQLite's 999-parameter limit
            incoming_ids = [c["tradera_id"] for c in categories]
            existing_by_id: dict[int, TraderaCategory] = {}
            for chunk_start in range(0, len(incoming_ids), 900):
                chunk = incoming_ids[chunk_start : chunk_start + 900]
                for r in session.query(TraderaCategory).filter(
                    TraderaCategory.tradera_id.in_(chunk)
                ):
                    existing_by_id[r.tradera_id] = r
            for cat in categories:
                row = existing_by_id.get(cat["tradera_id"]) or TraderaCategory(
                    tradera_id=cat["tradera_id"]
                )
                row.parent_tradera_id = cat["parent_tradera_id"]
                row.name = cat["name"]
                row.path = cat["path"]
                row.depth = cat["depth"]
                row.synced_at = now
                # NB: description is intentionally NOT touched here — it's
                # populated separately by generate_category_descriptions().
                if cat["tradera_id"] not in existing_by_id:
                    session.add(row)
            session.commit()
        return len(categories)

    @retry_on_transient()
    def _get_attribute_definitions_api_call(self, category_id, headers):
        return self.public_client.service.GetAttributeDefinitions(
            categoryId=int(category_id), **headers
        )

    def get_attribute_definitions(self, category_id: int) -> dict:
        """Get attribute definitions for a Tradera category.

        Returns required and optional attributes (e.g. material, era, condition)
        that can be set when creating a listing in this category.
        """
        try:
            response = self._get_attribute_definitions_api_call(
                category_id, self._auth_headers(self.public_client)
            )

            raw_attrs = self._soap_list(response, "AttributeDefinition")

            attributes = []
            for attr in raw_attrs:
                possible = getattr(attr, "PossibleTermValues", None)
                if possible is not None:
                    # zeep may expose ArrayOfString as object with .string attr or as list
                    values = getattr(possible, "string", None)
                    if values is None:
                        values = list(possible) if hasattr(possible, "__iter__") else []
                    else:
                        values = list(values)
                else:
                    values = []

                attributes.append(
                    {
                        "id": getattr(attr, "Id", None),
                        "name": getattr(attr, "Name", None),
                        "description": getattr(attr, "Description", None),
                        "key": getattr(attr, "Key", None),
                        "min_values": getattr(attr, "MinNumberOfValues", 0) or 0,
                        "max_values": getattr(attr, "MaxNumberOfValues", 0) or 0,
                        "possible_values": values,
                    }
                )

            return {"category_id": int(category_id), "attributes": attributes}

        except Exception as e:
            logger.exception("Tradera get_attribute_definitions failed")
            return {"error": str(e)}

    @retry_on_transient()
    def _get_shipping_options_api_call(self, request, headers):
        return self.public_client.service.GetShippingOptions(request=request, **headers)

    def get_shipping_options(
        self, weight_grams: int | None = None, from_country: str = "SE"
    ) -> dict:
        """Get available shipping options from Tradera.

        If weight_grams is provided, filters to options that support the given weight.
        """
        try:
            request = {"FromCountryCodes": [from_country]}
            response = self._get_shipping_options_api_call(
                request, self._auth_headers(self.public_client)
            )

            spans = getattr(response, "ProductsPerWeightSpan", None)
            if not spans:
                return {"shipping_options": []}

            options = []
            # ArrayOfProductsPerWeightSpan → ProductsPerWeightSpan elements
            span_list = getattr(spans, "ProductsPerWeightSpan", None) or spans
            if not hasattr(span_list, "__iter__"):
                span_list = [span_list]
            for span in span_list:
                # Weight is decimal kg in the WSDL; convert to grams
                weight_kg = getattr(span, "Weight", None)
                weight_limit = int(weight_kg * 1000) if weight_kg is not None else None
                products = getattr(span, "Products", None)
                if not products:
                    continue
                # ArrayOfProduct → Product elements
                prod_list = getattr(products, "Product", None) or products
                if not hasattr(prod_list, "__iter__"):
                    prod_list = [prod_list]
                for prod in prod_list:
                    options.append(self._parse_shipping_product(prod, weight_limit))

            if weight_grams is not None:
                options = [
                    opt
                    for opt in options
                    if opt.get("weight_limit_grams") is None
                    or opt["weight_limit_grams"] >= weight_grams
                ]
                return {"shipping_options": options, "filtered_by_weight_grams": weight_grams}

            return {"shipping_options": options}

        except Exception as e:
            logger.exception("Tradera get_shipping_options failed")
            return {"error": str(e)}

    @staticmethod
    def _parse_shipping_product(prod, weight_limit: int | None) -> dict:
        """Parse a SOAP Product object into a shipping option dict.

        Output field names match ``_build_shipping_option`` input so the agent
        can pass a selected option directly to ``shipping_options`` in listing
        details.
        """
        pkg = getattr(prod, "PackageRequirements", None)
        delivery = getattr(prod, "DeliveryInformation", None)
        cost = getattr(prod, "Price", None)
        vat = getattr(prod, "VatPercent", None)
        max_l = getattr(pkg, "MaxLength", None) if pkg else None
        max_w = getattr(pkg, "MaxWidth", None) if pkg else None
        max_h = getattr(pkg, "MaxHeight", None) if pkg else None
        return {
            "shipping_product_id": getattr(prod, "Id", None),
            "shipping_provider_id": getattr(prod, "ShippingProviderId", None),
            "provider_name": getattr(prod, "ShippingProvider", None),
            "name": getattr(prod, "Name", None),
            "cost": float(cost) if cost is not None else None,
            "weight_limit_grams": weight_limit,
            "vat_percent": float(vat) if vat is not None else None,
            "from_country": getattr(prod, "FromCountry", None),
            "to_country": getattr(prod, "ToCountry", None),
            "max_length_cm": float(max_l) if max_l is not None else None,
            "max_width_cm": float(max_w) if max_w is not None else None,
            "max_height_cm": float(max_h) if max_h is not None else None,
            "service_point": getattr(delivery, "ServicePoint", None) if delivery else None,
            "traceable": getattr(delivery, "IsTraceable", None) if delivery else None,
        }

    _SHIPPING_OPTION_FIELDS = {
        "shipping_option_id": "ShippingOptionId",
        "shipping_product_id": "ShippingProductId",
        "shipping_provider_id": "ShippingProviderId",
    }

    @staticmethod
    def _build_shipping_option(opt: dict) -> dict:
        """Convert a shipping option dict to a SOAP-compatible dict."""
        soap_opt = {"Cost": int(opt["cost"])}
        for key, soap_key in TraderaClient._SHIPPING_OPTION_FIELDS.items():
            if opt.get(key) is not None:
                soap_opt[soap_key] = int(opt[key])
        if opt.get("shipping_weight") is not None:
            soap_opt["ShippingWeight"] = opt["shipping_weight"]
        return soap_opt

    @retry_on_transient()
    def _get_shipping_types_api_call(self, headers):
        return self.public_client.service.GetShippingTypes(**headers)

    def get_shipping_types(self) -> dict:
        """Get available shipping types from Tradera."""
        try:
            response = self._get_shipping_types_api_call(self._auth_headers(self.public_client))

            if not response:
                return {"shipping_types": []}

            items = getattr(response, "IdDescriptionPair", None) or response
            if not hasattr(items, "__iter__"):
                return {"shipping_types": []}

            return {
                "shipping_types": [
                    {
                        "id": getattr(item, "Id", None),
                        "description": getattr(item, "Description", None),
                        "value": getattr(item, "Value", None),
                    }
                    for item in items
                ]
            }

        except Exception as e:
            logger.exception("Tradera get_shipping_types failed")
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

            token = getattr(response, "AuthToken", None)
            expires = getattr(response, "HardExpirationTime", None)
            if expires is not None:
                expires = str(expires)

            if token is None:
                return {
                    "error": "FetchToken response missing AuthToken",
                    "response_repr": repr(response),
                }

            return {
                "token": token,
                "expires": expires,
            }

        except Exception as e:
            logger.exception("Tradera fetch_token failed")
            return {"error": str(e)}

    def _parse_order_items(self, order) -> list[dict]:
        """Parse order items from a SOAP SellerOrder object."""
        return [
            {
                "item_id": getattr(item, "ItemId", None),
                "title": getattr(item, "Title", None),
                "price": float(getattr(item, "Price", 0) or 0),
                "quantity": getattr(item, "Quantity", 1),
            }
            for item in self._soap_list(getattr(order, "Items", None), "SellerOrderItem")
        ]

    def _parse_order_payments(self, order) -> list[dict]:
        """Parse payments from a SOAP SellerOrder object."""
        return [
            {
                "type": getattr(payment, "PaymentType", None),
                "amount": float(getattr(payment, "Amount", 0) or 0),
            }
            for payment in self._soap_list(getattr(order, "Payments", None), "Payment")
        ]

    @retry_on_transient()
    def _get_orders_api_call(self, from_dt, to_dt, headers):
        return self.order_client.service.GetSellerOrders(
            request={
                "FromDate": from_dt,
                "ToDate": to_dt,
                "QueryDateMode": "CreatedDate",
            },
            **headers,
        )

    def get_orders(self, from_date: str | None = None, to_date: str | None = None) -> dict:
        try:
            to_dt = datetime.fromisoformat(to_date) if to_date else datetime.now(UTC)
            from_dt = (
                datetime.fromisoformat(from_date) if from_date else to_dt - timedelta(days=30)
            )

            response = self._get_orders_api_call(
                from_dt,
                to_dt,
                self._auth_headers(self.order_client, include_authorization=True),
            )

            raw_orders = self._soap_list(getattr(response, "Orders", None), "SellerOrder")

            orders = []
            for order in raw_orders:
                orders.append(
                    {
                        "order_id": getattr(order, "OrderId", None),
                        "buyer_name": getattr(order, "BuyerName", None),
                        "buyer_address": getattr(order, "BuyerAddress", None),
                        "sub_total": float(getattr(order, "SubTotal", 0) or 0),
                        "shipping_cost": float(getattr(order, "ShippingCost", 0) or 0),
                        "items": self._parse_order_items(order),
                        "payments": self._parse_order_payments(order),
                    }
                )

            return {"orders": orders, "count": len(orders)}

        except Exception as e:
            logger.exception("Tradera get_orders failed")
            return {"error": str(e), "orders": [], "count": 0}

    @retry_on_transient()
    def _get_item_api_call(self, item_id, headers):
        return self.public_client.service.GetItem(itemId=int(item_id), **headers)

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
                "price": float(
                    getattr(response, "BuyItNowPrice", 0) or getattr(response, "MaxBid", 0) or 0
                ),
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
        return self.order_client.service.SetSellerOrderAsShipped(
            request={"OrderId": int(order_id)}, **headers
        )

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

    @retry_on_transient()
    def _leave_feedback_api_call(self, order_number, comment, feedback_type, headers):
        return self.restricted_client.service.LeaveOrderFeedbackToBuyer(
            orderNumber=int(order_number), comment=comment, type=feedback_type, **headers
        )

    def leave_feedback(
        self, order_number: int, comment: str, feedback_type: str = "Positive"
    ) -> dict:
        """Leave feedback for a buyer on a completed order.

        Args:
            order_number: Tradera order number (external_order_id).
            comment: Feedback text (max 80 characters).
            feedback_type: "Positive" or "Negative".
        """
        if len(comment) > 80:
            return {"error": f"Comment too long ({len(comment)} chars, max 80)"}

        valid_types = ("Positive", "Negative")
        if feedback_type not in valid_types:
            return {
                "error": f"Invalid feedback type '{feedback_type}', must be one of {valid_types}"
            }

        try:
            result = self._leave_feedback_api_call(
                order_number,
                comment,
                feedback_type,
                self._auth_headers(self.restricted_client, include_authorization=True),
            )

            if result is False:
                return {
                    "error": "Tradera rejected the feedback (may already be submitted)",
                    "order_number": order_number,
                }

            return {
                "success": True,
                "order_number": order_number,
                "comment": comment,
                "feedback_type": feedback_type,
            }

        except Exception as e:
            logger.exception("Tradera leave_feedback failed")
            return {"error": str(e)}
