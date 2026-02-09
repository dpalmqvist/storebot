from unittest.mock import MagicMock, patch

import pytest

from storebot.tools.tradera import TraderaClient


@pytest.fixture
def client():
    with patch("storebot.tools.tradera.zeep.Client") as mock_zeep:
        c = TraderaClient(app_id="12345", app_key="testkey", sandbox=True)
        # Force the lazy property to use our mock
        c._search_client = mock_zeep.return_value
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
        client.search_client.service.SearchAdvanced.side_effect = Exception(
            "Connection refused"
        )

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

    def test_soap_headers_include_auth_and_config(self, client):
        auth_element = MagicMock()
        config_element = MagicMock()
        client.search_client.get_element.side_effect = [
            lambda **kw: auth_element,
            lambda **kw: config_element,
        ]

        headers = client._soap_headers()

        assert "_soapheaders" in headers
        assert len(headers["_soapheaders"]) == 2

    def test_lazy_client_not_created_on_init(self):
        with patch("storebot.tools.tradera.zeep.Client") as mock_zeep:
            c = TraderaClient(app_id="123", app_key="key")
            mock_zeep.assert_not_called()
            assert c._search_client is None
