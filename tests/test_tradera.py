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

        call_kwargs = client._order_client.service.GetSellerOrders.call_args
        assert call_kwargs.kwargs["DateFrom"].year == 2026
        assert call_kwargs.kwargs["DateFrom"].month == 1
        assert call_kwargs.kwargs["DateTo"].month == 1
        assert call_kwargs.kwargs["DateTo"].day == 31


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
        assert result["url"] == "https://www.tradera.com/item/12345"

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        assert call_kwargs["Title"] == "Antik byrå"
        assert call_kwargs["CategoryId"] == 344
        assert call_kwargs["Duration"] == 7
        assert call_kwargs["ItemType"] == 1  # Auction
        assert call_kwargs["StartPrice"] == 500

    def test_buy_it_now_listing(self, client):
        response = MagicMock()
        response.ItemId = 99999
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
        assert call_kwargs["ItemType"] == 2  # BuyItNow
        assert call_kwargs["BuyItNowPrice"] == 800

    def test_with_shipping_and_returns(self, client):
        response = MagicMock()
        response.ItemId = 1
        client._restricted_client.service.AddItem.return_value = response

        client.create_listing(
            title="Test",
            description="Test",
            category_id=100,
            shipping_cost=99,
            accepting_returns=True,
        )

        call_kwargs = client._restricted_client.service.AddItem.call_args.kwargs
        assert call_kwargs["ShippingCost"] == 99
        assert call_kwargs["AcceptingReturns"] is True

    def test_uses_authorization_headers(self, client):
        response = MagicMock()
        response.ItemId = 1
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


class TestTraderaUploadImages:
    def test_success(self, client):
        client._restricted_client.service.AddItemImages.return_value = None

        images = [("base64data1", "image/jpeg"), ("base64data2", "image/png")]
        result = client.upload_images(item_id=12345, images=images)

        assert result["item_id"] == 12345
        assert result["images_uploaded"] == 2

        call_kwargs = client._restricted_client.service.AddItemImages.call_args.kwargs
        assert call_kwargs["ItemId"] == 12345
        assert len(call_kwargs["Images"]) == 2
        assert call_kwargs["Images"][0]["Data"] == "base64data1"
        assert call_kwargs["Images"][0]["MediaType"] == "image/jpeg"

    def test_api_error(self, client):
        client._restricted_client.service.AddItemImages.side_effect = Exception("Upload failed")

        result = client.upload_images(item_id=1, images=[("data", "image/jpeg")])

        assert result["error"] == "Upload failed"

    def test_empty_list(self, client):
        client._restricted_client.service.AddItemImages.return_value = None

        result = client.upload_images(item_id=1, images=[])

        assert result["images_uploaded"] == 0


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

        result = client.get_categories(parent_id=0)

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

        result = client.get_categories(parent_id=999)

        assert result["categories"] == []


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
