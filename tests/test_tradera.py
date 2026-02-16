from unittest.mock import MagicMock, patch

import pytest
import requests

from storebot.tools.tradera import TraderaClient


@pytest.fixture
def client():
    with patch("storebot.tools.tradera.zeep.Client") as mock_zeep:
        c = TraderaClient(
            app_id="12345",
            app_key="testkey",
            sandbox=True,
            user_id="67890",
            user_token="usertoken",
        )
        # Force the lazy properties to use our mock
        c._search_client = mock_zeep.return_value
        c._order_client = MagicMock()
        c._public_client = MagicMock()
        c._restricted_client = MagicMock()
        yield c


def _make_search_item(**overrides):
    item = MagicMock()
    item.Id = overrides.get("Id", 100)
    item.ShortDescription = overrides.get("ShortDescription", "Antik stol")
    item.BuyItNowPrice = overrides.get("BuyItNowPrice", 500)
    item.MaxBid = overrides.get("MaxBid", 0)
    item.BidCount = overrides.get("BidCount", 3)
    item.ItemUrl = overrides.get("ItemUrl", "https://www.tradera.com/item/100")
    item.ThumbnailLink = overrides.get("ThumbnailLink", "https://img.tradera.com/100.jpg")
    item.ImageLinks = None
    item.EndDate = overrides.get("EndDate", "2026-03-01T12:00:00")
    item.SellerAlias = overrides.get("SellerAlias", "testuser")
    item.ItemType = overrides.get("ItemType", "Auction")
    for k, v in overrides.items():
        setattr(item, k, v)
    return item


def _make_response(items=None, total=None, total_pages=1, errors=None):
    resp = MagicMock()
    if items is None:
        items = []
    resp.TotalNumberOfItems = total if total is not None else len(items)
    resp.TotalNumberOfPages = total_pages
    resp.Errors = errors

    items_obj = MagicMock()
    items_obj.SearchItem = items
    resp.Items = items_obj
    return resp


class TestTraderaSearch:
    def test_search_returns_formatted_results(self, client):
        item1 = _make_search_item(Id=1, ShortDescription="Byrå", BuyItNowPrice=1200)
        item2 = _make_search_item(Id=2, ShortDescription="Lampa", MaxBid=350, BuyItNowPrice=0)
        response = _make_response(items=[item1, item2], total=2)
        client.search_client.service.SearchAdvanced.return_value = response

        result = client.search("möbler")

        assert result["total"] == 2
        assert result["page"] == 1
        assert result["total_pages"] == 1
        assert len(result["items"]) == 2

        assert result["items"][0]["id"] == 1
        assert result["items"][0]["title"] == "Byrå"
        assert result["items"][0]["price"] == 1200

        assert result["items"][1]["id"] == 2
        assert result["items"][1]["title"] == "Lampa"
        assert result["items"][1]["price"] == 350

    def test_search_empty_results(self, client):
        response = _make_response(items=[], total=0)
        client.search_client.service.SearchAdvanced.return_value = response

        result = client.search("nonexistent")

        assert result["total"] == 0
        assert result["items"] == []
        assert "error" not in result

    def test_search_passes_filters(self, client):
        response = _make_response()
        client.search_client.service.SearchAdvanced.return_value = response

        client.search("stol", category=344, max_price=500, page=2, items_per_page=25)

        call_kwargs = client.search_client.service.SearchAdvanced.call_args
        assert call_kwargs.kwargs["SearchWords"] == "stol"
        assert call_kwargs.kwargs["CategoryId"] == 344
        assert call_kwargs.kwargs["PriceMaximum"] == 500
        assert call_kwargs.kwargs["PageNumber"] == 2
        assert call_kwargs.kwargs["ItemsPerPage"] == 25

    def test_search_default_category_is_zero(self, client):
        response = _make_response()
        client.search_client.service.SearchAdvanced.return_value = response

        client.search("bord")

        call_kwargs = client.search_client.service.SearchAdvanced.call_args
        assert call_kwargs.kwargs["CategoryId"] == 0
        assert "PriceMaximum" not in call_kwargs.kwargs

    def test_search_handles_api_error(self, client):
        client.search_client.service.SearchAdvanced.side_effect = Exception("Connection refused")

        result = client.search("test")

        assert result["error"] == "Connection refused"
        assert result["total"] == 0
        assert result["items"] == []

    def test_search_handles_response_errors(self, client):
        response = _make_response(errors=["Invalid AppKey"])
        client.search_client.service.SearchAdvanced.return_value = response

        result = client.search("test")

        assert "error" in result
        assert result["total"] == 0

    def test_search_price_uses_max_of_buynow_and_maxbid(self, client):
        item = _make_search_item(BuyItNowPrice=200, MaxBid=300)
        response = _make_response(items=[item])
        client.search_client.service.SearchAdvanced.return_value = response

        result = client.search("test")

        assert result["items"][0]["price"] == 300

    def test_auth_headers_include_auth_and_config(self, client):
        auth_element = MagicMock()
        config_element = MagicMock()
        client.search_client.get_element.side_effect = [
            lambda **kw: auth_element,
            lambda **kw: config_element,
        ]

        headers = client._auth_headers(client.search_client)

        assert "_soapheaders" in headers
        assert len(headers["_soapheaders"]) == 2

    def test_lazy_client_not_created_on_init(self):
        with patch("storebot.tools.tradera.zeep.Client") as mock_zeep:
            c = TraderaClient(app_id="123", app_key="key")
            mock_zeep.assert_not_called()
            assert c._search_client is None


def _make_seller_order(order_id=1, item_id=100, price=500, shipping=50):
    order = MagicMock()
    order.OrderId = order_id
    order.BuyerName = "Anna Svensson"
    order.BuyerAddress = "Storgatan 1"
    order.SubTotal = price
    order.ShippingCost = shipping

    item = MagicMock()
    item.ItemId = item_id
    item.Title = "Antik stol"
    item.Price = price
    item.Quantity = 1
    items_obj = MagicMock()
    items_obj.SellerOrderItem = [item]
    order.Items = items_obj

    payment = MagicMock()
    payment.PaymentType = "DirectPayment"
    payment.Amount = price + shipping
    payments_obj = MagicMock()
    payments_obj.Payment = [payment]
    order.Payments = payments_obj

    return order


def _make_orders_response(orders=None):
    resp = MagicMock()
    orders_obj = MagicMock()
    orders_obj.SellerOrder = orders or []
    resp.Orders = orders_obj
    return resp


class TestTraderaGetOrders:
    def test_returns_parsed_orders(self, client):
        order = _make_seller_order(order_id=42, item_id=100, price=500)
        response = _make_orders_response([order])
        client._order_client.service.GetSellerOrders.return_value = response

        result = client.get_orders()

        assert result["count"] == 1
        assert result["orders"][0]["order_id"] == 42
        assert result["orders"][0]["buyer_name"] == "Anna Svensson"
        assert result["orders"][0]["sub_total"] == 500
        assert len(result["orders"][0]["items"]) == 1
        assert result["orders"][0]["items"][0]["item_id"] == 100

    def test_empty_orders(self, client):
        response = _make_orders_response([])
        client._order_client.service.GetSellerOrders.return_value = response

        result = client.get_orders()

        assert result["count"] == 0
        assert result["orders"] == []

    def test_handles_api_error(self, client):
        client._order_client.service.GetSellerOrders.side_effect = Exception("Timeout")

        result = client.get_orders()

        assert result["error"] == "Timeout"
        assert result["count"] == 0

    def test_date_parameters_passed(self, client):
        response = _make_orders_response([])
        client._order_client.service.GetSellerOrders.return_value = response

        client.get_orders(from_date="2026-01-01", to_date="2026-01-31")

        request = client._order_client.service.GetSellerOrders.call_args.kwargs["request"]
        assert request["FromDate"].year == 2026
        assert request["FromDate"].month == 1
        assert request["ToDate"].month == 1
        assert request["ToDate"].day == 31
        assert request["QueryDateMode"] == "CreatedDate"


class TestTraderaGetItem:
    def test_returns_item_details(self, client):
        item_resp = MagicMock()
        item_resp.Id = 42
        item_resp.Title = "Antik byrå"
        item_resp.Description = "Vacker byrå från 1920-talet"
        item_resp.BuyItNowPrice = 1500
        item_resp.MaxBid = 0
        item_resp.Status = "Ended"
        item_resp.EndDate = "2026-02-01T12:00:00"
        item_resp.ItemUrl = "https://www.tradera.com/item/42"
        client._public_client.service.GetItem.return_value = item_resp

        result = client.get_item(42)

        assert result["id"] == 42
        assert result["title"] == "Antik byrå"
        assert result["price"] == 1500

    def test_handles_api_error(self, client):
        client._public_client.service.GetItem.side_effect = Exception("Not found")

        result = client.get_item(999)

        assert result["error"] == "Not found"


class TestTraderaMarkOrderShipped:
    def test_success(self, client):
        client._order_client.service.SetSellerOrderAsShipped.return_value = None

        result = client.mark_order_shipped(42)

        assert result["order_id"] == 42
        assert result["status"] == "shipped"

    def test_handles_api_error(self, client):
        client._order_client.service.SetSellerOrderAsShipped.side_effect = Exception("Auth failed")

        result = client.mark_order_shipped(42)

        assert result["error"] == "Auth failed"


class TestAuthHeaders:
    def test_without_authorization(self, client):
        mock_client = MagicMock()
        mock_client.get_element.side_effect = [
            lambda **kw: MagicMock(),
            lambda **kw: MagicMock(),
        ]

        headers = client._auth_headers(mock_client, include_authorization=False)

        assert len(headers["_soapheaders"]) == 2

    def test_with_authorization(self, client):
        mock_client = MagicMock()
        mock_client.get_element.side_effect = [
            lambda **kw: MagicMock(),
            lambda **kw: MagicMock(),
            lambda **kw: MagicMock(),
        ]

        headers = client._auth_headers(mock_client, include_authorization=True)

        assert len(headers["_soapheaders"]) == 3


class TestTraderaCreateListing:
    def test_auction_listing(self, client):
        response = MagicMock()
        response.ItemId = 12345
        response.RequestId = 99001
        client._restricted_client.service.AddItem.return_value = response

        result = client.create_listing(
            title="Antik byrå",
            description="Vacker byrå från 1920-talet",
            category_id=344,
            duration_days=7,
            listing_type="auction",
            start_price=500,
        )

        assert result["item_id"] == 12345
        assert result["request_id"] == 99001
        assert result["url"] == "https://www.tradera.com/item/12345"

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert item_req["Title"] == "Antik byrå"
        assert item_req["CategoryId"] == 344
        assert item_req["Duration"] == 7
        assert item_req["ItemType"] == 1
        assert item_req["StartPrice"] == 500
        assert item_req["AutoCommit"] is True

    def test_buy_it_now_listing(self, client):
        response = MagicMock()
        response.ItemId = 99999
        response.RequestId = 99002
        client._restricted_client.service.AddItem.return_value = response

        result = client.create_listing(
            title="Mässingsljusstake",
            description="Fin ljusstake",
            category_id=200,
            listing_type="buy_it_now",
            buy_it_now_price=800,
        )

        assert result["item_id"] == 99999
        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert item_req["ItemType"] == 3
        assert item_req["BuyItNowPrice"] == 800

    def test_with_shipping_cost_converts_to_shipping_options(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 99003
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(
            title="Test",
            description="Test",
            category_id=100,
            shipping_cost=99,
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert "ShippingCost" not in item_req
        assert item_req["ShippingOptions"] == [{"Cost": 99}]

    def test_auto_commit_false(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 99004
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(title="Test", description="Test", category_id=100, auto_commit=False)

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert item_req["AutoCommit"] is False

    def test_uses_authorization_headers(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 99005
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(title="Test", description="Test", category_id=100)

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        assert "_soapheaders" in call_kwargs

    def test_api_error(self, client):
        client._restricted_client.service.AddItem.side_effect = Exception("Auth failed")

        result = client.create_listing(title="Test", description="Test", category_id=100)

        assert result["error"] == "Auth failed"

    def test_missing_item_id_in_response(self, client):
        response = MagicMock(spec=[])  # no ItemId attribute
        client._restricted_client.service.AddItem.return_value = response

        result = client.create_listing(title="Test", description="Test", category_id=100)

        assert result["error"] == "Tradera API response missing ItemId"


class TestCreateListingAttributes:
    def test_with_item_attributes_and_attribute_values(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 90001
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(
            title="Antik byrå",
            description="Vacker byrå",
            category_id=344,
            start_price=500,
            item_attributes=[101, 102],
            attribute_values=[
                {"id": 101, "name": "Material", "values": ["Trä"]},
                {"id": 102, "name": "Epok", "values": ["1920-tal"]},
            ],
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert item_req["ItemAttributes"] == [101, 102]
        assert "TermAttributeValues" in item_req["AttributeValues"]
        term_vals = item_req["AttributeValues"]["TermAttributeValues"]
        assert len(term_vals) == 2
        assert term_vals[0]["Id"] == 101
        assert term_vals[0]["Name"] == "Material"
        assert term_vals[0]["Values"] == ["Trä"]

    def test_number_attribute_values(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 90002
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(
            title="Test",
            description="Test",
            category_id=100,
            attribute_values=[
                {"id": 201, "name": "Vikt", "values": ["3500"], "type": "number"},
            ],
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert "NumberAttributeValues" in item_req["AttributeValues"]
        assert "TermAttributeValues" not in item_req["AttributeValues"]
        num_vals = item_req["AttributeValues"]["NumberAttributeValues"]
        assert num_vals[0]["Id"] == 201
        assert num_vals[0]["Values"] == ["3500"]

    def test_attributes_omitted_when_none(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 90003
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(
            title="Test",
            description="Test",
            category_id=100,
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert item_req["ItemAttributes"] == []
        assert "AttributeValues" not in item_req

    def test_rejects_attribute_missing_id(self, client):
        result = client.create_listing(
            title="Test",
            description="Test",
            category_id=100,
            attribute_values=[{"name": "Material", "values": ["Trä"]}],
        )
        assert "error" in result
        assert "missing 'id' or 'values'" in result["error"]

    def test_rejects_attribute_values_not_list(self, client):
        result = client.create_listing(
            title="Test",
            description="Test",
            category_id=100,
            attribute_values=[{"id": 101, "values": "Trä"}],
        )
        assert "error" in result
        assert "'values' must be a list" in result["error"]


class TestTraderaUploadImages:
    def test_success(self, client):
        client._restricted_client.service.AddItemImage.return_value = None

        images = [("base64data1", "image/jpeg"), ("base64data2", "image/png")]
        result = client.upload_images(request_id=12345, images=images)

        assert result["request_id"] == 12345
        assert result["images_uploaded"] == 2
        assert client._restricted_client.service.AddItemImage.call_count == 2

        # Check first call (JPEG)
        call1 = client._restricted_client.service.AddItemImage.call_args_list[0].kwargs
        assert call1["requestId"] == 12345
        assert call1["imageData"] == "base64data1"
        assert call1["imageFormat"] == "Jpeg"
        assert call1["hasMega"] is True

        # Check second call (PNG)
        call2 = client._restricted_client.service.AddItemImage.call_args_list[1].kwargs
        assert call2["requestId"] == 12345
        assert call2["imageData"] == "base64data2"
        assert call2["imageFormat"] == "Png"

    def test_api_error(self, client):
        client._restricted_client.service.AddItemImage.side_effect = Exception("Upload failed")

        result = client.upload_images(request_id=1, images=[("data", "image/jpeg")])

        assert result["error"] == "Upload failed"

    def test_empty_list(self, client):
        result = client.upload_images(request_id=1, images=[])

        assert result["images_uploaded"] == 0

    def test_unknown_media_type_defaults_to_jpeg(self, client):
        client._restricted_client.service.AddItemImage.return_value = None

        result = client.upload_images(request_id=1, images=[("data", "image/webp")])

        assert result["images_uploaded"] == 1
        call_kwargs = client._restricted_client.service.AddItemImage.call_args.kwargs
        assert call_kwargs["imageFormat"] == "Jpeg"


class TestCommitListing:
    def test_success(self, client):
        client._restricted_client.service.AddItemCommit.return_value = None

        result = client.commit_listing(request_id=99001)

        assert result["request_id"] == 99001
        assert result["committed"] is True

        call_kwargs = client._restricted_client.service.AddItemCommit.call_args.kwargs
        assert call_kwargs["requestId"] == 99001

    def test_api_error(self, client):
        client._restricted_client.service.AddItemCommit.side_effect = Exception("Commit failed")

        result = client.commit_listing(request_id=99001)

        assert result["error"] == "Commit failed"


class TestTraderaGetCategories:
    def test_success(self, client):
        cat1 = MagicMock()
        cat1.Id = 100
        cat1.Name = "Möbler"
        cat2 = MagicMock()
        cat2.Id = 200
        cat2.Name = "Inredning"

        response = MagicMock()
        cats_obj = MagicMock()
        cats_obj.Category = [cat1, cat2]
        response.Categories = cats_obj
        client._public_client.service.GetCategories.return_value = response

        result = client.get_categories()

        assert len(result["categories"]) == 2
        assert result["categories"][0] == {"id": 100, "name": "Möbler"}
        assert result["categories"][1] == {"id": 200, "name": "Inredning"}

    def test_api_error(self, client):
        client._public_client.service.GetCategories.side_effect = Exception("Timeout")

        result = client.get_categories()

        assert result["error"] == "Timeout"

    def test_empty_categories(self, client):
        response = MagicMock()
        cats_obj = MagicMock()
        cats_obj.Category = []
        response.Categories = cats_obj
        client._public_client.service.GetCategories.return_value = response

        result = client.get_categories()

        assert result["categories"] == []


class TestGetAttributeDefinitions:
    def test_returns_parsed_definitions(self, client):
        attr1 = MagicMock()
        attr1.Id = 101
        attr1.Name = "Material"
        attr1.Description = "Materialtyp"
        attr1.Key = "material"
        attr1.MinNumberOfValues = 1
        attr1.MaxNumberOfValues = 3
        terms1 = MagicMock()
        terms1.string = ["Trä", "Metall", "Glas"]
        attr1.PossibleTermValues = terms1

        attr2 = MagicMock()
        attr2.Id = 102
        attr2.Name = "Epok"
        attr2.Description = "Tidsperiod"
        attr2.Key = "era"
        attr2.MinNumberOfValues = 0
        attr2.MaxNumberOfValues = 1
        attr2.PossibleTermValues = None

        response = MagicMock()
        response.AttributeDefinition = [attr1, attr2]
        client._public_client.service.GetAttributeDefinitions.return_value = response

        result = client.get_attribute_definitions(344)

        assert result["category_id"] == 344
        assert len(result["attributes"]) == 2

        a1 = result["attributes"][0]
        assert a1["id"] == 101
        assert a1["name"] == "Material"
        assert a1["key"] == "material"
        assert a1["min_values"] == 1
        assert a1["max_values"] == 3
        assert a1["possible_values"] == ["Trä", "Metall", "Glas"]

        a2 = result["attributes"][1]
        assert a2["id"] == 102
        assert a2["name"] == "Epok"
        assert a2["min_values"] == 0
        assert a2["possible_values"] == []

    def test_empty_response(self, client):
        response = MagicMock()
        response.AttributeDefinition = []
        client._public_client.service.GetAttributeDefinitions.return_value = response

        result = client.get_attribute_definitions(999)

        assert result["category_id"] == 999
        assert result["attributes"] == []

    def test_api_error(self, client):
        client._public_client.service.GetAttributeDefinitions.side_effect = Exception(
            "Category not found"
        )

        result = client.get_attribute_definitions(999)

        assert result["error"] == "Category not found"

    def test_possible_values_as_list(self, client):
        """Test when zeep exposes PossibleTermValues as a direct list (no .string attr)."""
        attr = MagicMock(spec=[])
        attr.Id = 103
        attr.Name = "Skick"
        attr.Description = None
        attr.Key = "condition"
        attr.MinNumberOfValues = 1
        attr.MaxNumberOfValues = 1
        # Simulate direct list (no .string attribute)
        attr.PossibleTermValues = ["Nytt", "Bra skick", "Slitage"]

        response = MagicMock()
        response.AttributeDefinition = [attr]
        client._public_client.service.GetAttributeDefinitions.return_value = response

        result = client.get_attribute_definitions(100)

        assert result["attributes"][0]["possible_values"] == ["Nytt", "Bra skick", "Slitage"]


class TestGetShippingOptions:
    def test_returns_parsed_options(self, client):
        prod1 = MagicMock()
        prod1.Id = 10
        prod1.ProviderName = "PostNord"
        prod1.ProviderId = 1
        prod1.Name = "MyPack Collect"
        prod1.PriceInSek = 59.0
        prod1.VatInPercent = 25
        prod1.FromCountryCode = "SE"
        prod1.ToCountryCode = "SE"
        prod1.MaxLengthInCm = 60
        prod1.MaxWidthInCm = 40
        prod1.MaxHeightInCm = 30
        prod1.ServicePoint = True
        prod1.Traceable = True

        products_obj = MagicMock()
        products_obj.ShippingProduct = [prod1]

        span = MagicMock()
        span.WeightInGrams = 2000
        span.Products = products_obj

        spans_obj = MagicMock()
        spans_obj.ShippingOptionsPerWeightSpan = [span]

        response = MagicMock()
        response.ProductsPerWeightSpan = spans_obj
        client._public_client.service.GetShippingOptions.return_value = response

        result = client.get_shipping_options()

        assert len(result["shipping_options"]) == 1
        opt = result["shipping_options"][0]
        assert opt["id"] == 10
        assert opt["provider_name"] == "PostNord"
        assert opt["name"] == "MyPack Collect"
        assert opt["weight_limit_grams"] == 2000
        assert opt["price_sek"] == 59.0
        assert opt["service_point"] is True

    def test_empty_response(self, client):
        response = MagicMock()
        response.ProductsPerWeightSpan = None
        client._public_client.service.GetShippingOptions.return_value = response

        result = client.get_shipping_options()

        assert result["shipping_options"] == []

    def test_api_error(self, client):
        client._public_client.service.GetShippingOptions.side_effect = Exception("Timeout")

        result = client.get_shipping_options()

        assert result["error"] == "Timeout"

    def test_passes_country_code(self, client):
        response = MagicMock()
        response.ProductsPerWeightSpan = None
        client._public_client.service.GetShippingOptions.return_value = response

        client.get_shipping_options(from_country="NO")

        call_kwargs = client._public_client.service.GetShippingOptions.call_args.kwargs
        assert call_kwargs["request"] == {"FromCountryCodes": ["NO"]}


class TestGetShippingTypes:
    def test_returns_types(self, client):
        type1 = MagicMock()
        type1.Id = 1
        type1.Description = "Brev"
        type1.Value = "letter"
        type2 = MagicMock()
        type2.Id = 2
        type2.Description = "Paket"
        type2.Value = "package"

        response = MagicMock()
        response.IdDescriptionPair = [type1, type2]
        response.__iter__ = MagicMock(return_value=iter([type1, type2]))
        client._public_client.service.GetShippingTypes.return_value = response

        result = client.get_shipping_types()

        assert len(result["shipping_types"]) == 2
        assert result["shipping_types"][0] == {"id": 1, "description": "Brev", "value": "letter"}
        assert result["shipping_types"][1] == {"id": 2, "description": "Paket", "value": "package"}

    def test_api_error(self, client):
        client._public_client.service.GetShippingTypes.side_effect = Exception("Auth failed")

        result = client.get_shipping_types()

        assert result["error"] == "Auth failed"


class TestCreateListingReservePrice:
    def test_reserve_price_sent_as_api_field(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 87001
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(
            title="Antik stol",
            description="Vacker stol",
            category_id=344,
            listing_type="auction",
            start_price=500,
            reserve_price=1500,
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert item_req["ReservePrice"] == 1500

    def test_reserve_price_omitted_when_none(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 87002
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(
            title="Antik stol",
            description="Vacker stol",
            category_id=344,
            listing_type="auction",
            start_price=500,
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert "ReservePrice" not in item_req


class TestCreateListingShipping:
    def test_structured_shipping_options(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 88001
        client._restricted_client.service.AddItem.return_value = response

        shipping_options = [
            {
                "cost": 59,
                "shipping_product_id": 10,
                "shipping_provider_id": 1,
                "shipping_weight": 2000,
            },
        ]
        client.create_listing(
            title="Test",
            description="Test",
            category_id=100,
            shipping_options=shipping_options,
            shipping_condition="PostBefordran",
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert "ShippingOptions" in item_req
        assert "ShippingCost" not in item_req
        assert item_req["ShippingCondition"] == "PostBefordran"
        soap_opt = item_req["ShippingOptions"][0]
        assert soap_opt["Cost"] == 59
        assert soap_opt["ShippingProductId"] == 10
        assert soap_opt["ShippingProviderId"] == 1
        assert soap_opt["ShippingWeight"] == 2000

    def test_structured_options_override_flat_cost(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 88002
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(
            title="Test",
            description="Test",
            category_id=100,
            shipping_cost=99,
            shipping_options=[{"cost": 59, "shipping_product_id": 10}],
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert "ShippingOptions" in item_req
        assert "ShippingCost" not in item_req

    def test_flat_shipping_cost_converts_to_shipping_options(self, client):
        response = MagicMock()
        response.ItemId = 1
        response.RequestId = 88003
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(
            title="Test",
            description="Test",
            category_id=100,
            shipping_cost=49,
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        item_req = call_kwargs["itemRequest"]
        assert "ShippingCost" not in item_req
        assert item_req["ShippingOptions"] == [{"Cost": 49}]


class TestTraderaLeaveFeedback:
    def test_success(self, client):
        client._restricted_client.service.LeaveOrderFeedbackToBuyer.return_value = True

        result = client.leave_feedback(order_number=42, comment="Snabb betalning, tack!")

        assert result["success"] is True
        assert result["order_number"] == 42
        assert result["comment"] == "Snabb betalning, tack!"
        assert result["feedback_type"] == "Positive"

        call_kwargs = client._restricted_client.service.LeaveOrderFeedbackToBuyer.call_args.kwargs
        assert call_kwargs["orderNumber"] == 42
        assert call_kwargs["comment"] == "Snabb betalning, tack!"
        assert call_kwargs["type"] == "Positive"

    def test_negative_feedback(self, client):
        client._restricted_client.service.LeaveOrderFeedbackToBuyer.return_value = True

        result = client.leave_feedback(
            order_number=42, comment="Betalade sent", feedback_type="Negative"
        )

        assert result["success"] is True
        assert result["feedback_type"] == "Negative"

    def test_comment_too_long(self, client):
        result = client.leave_feedback(order_number=42, comment="A" * 81)

        assert "error" in result
        assert "too long" in result["error"]
        client._restricted_client.service.LeaveOrderFeedbackToBuyer.assert_not_called()

    def test_invalid_feedback_type(self, client):
        result = client.leave_feedback(order_number=42, comment="Tack!", feedback_type="Neutral")

        assert "error" in result
        assert "Invalid feedback type" in result["error"]
        client._restricted_client.service.LeaveOrderFeedbackToBuyer.assert_not_called()

    def test_api_returns_false(self, client):
        client._restricted_client.service.LeaveOrderFeedbackToBuyer.return_value = False

        result = client.leave_feedback(order_number=42, comment="Tack!")

        assert "error" in result
        assert "rejected" in result["error"]

    def test_api_error(self, client):
        client._restricted_client.service.LeaveOrderFeedbackToBuyer.side_effect = Exception(
            "Auth failed"
        )

        result = client.leave_feedback(order_number=42, comment="Tack!")

        assert result["error"] == "Auth failed"


class TestTraderaRetry:
    @patch("storebot.retry.time.sleep")
    def test_search_retries_on_connection_error(self, mock_sleep, client):
        response = _make_response(items=[], total=0)
        client.search_client.service.SearchAdvanced.side_effect = [
            requests.ConnectionError("refused"),
            response,
        ]

        result = client.search("test")

        assert "error" not in result
        assert result["total"] == 0
        assert mock_sleep.call_count == 1

    @patch("storebot.retry.time.sleep")
    def test_search_no_retry_on_auth_error(self, mock_sleep, client):
        import zeep.exceptions

        client.search_client.service.SearchAdvanced.side_effect = zeep.exceptions.TransportError(
            status_code=401, message="Unauthorized"
        )

        result = client.search("test")

        assert "error" in result
        mock_sleep.assert_not_called()
