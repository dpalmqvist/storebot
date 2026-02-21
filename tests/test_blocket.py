import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from storebot.tools.blocket import (
    AD_HTML_URL,
    SEARCH_URL,
    USER_AGENT,
    BlocketClient,
    Category,
    Location,
    SortOrder,
    _extract_hydration_data,
    _parse_hydration_item,
)


@pytest.fixture
def client():
    return BlocketClient()


# ---------------------------------------------------------------------------
# Search result helpers
# ---------------------------------------------------------------------------


def _make_doc(**overrides):
    doc = {
        "ad_id": 20753486,
        "id": "20753486",
        "heading": "Antikt bord från 1800-tal",
        "price": {"amount": 600, "currency_code": "SEK", "price_unit": "kr"},
        "canonical_url": "https://www.blocket.se/recommerce/forsale/item/20753486",
        "image": {
            "url": "https://images.blocketcdn.se/dynamic/default/item/20753486/img.jpg",
        },
        "location": "Stockholm",
        "timestamp": 1770668084000,
        "trade_type": "Säljes",
    }
    doc.update(overrides)
    return doc


def _make_response(docs=None, total=None, page=1, last_page=1):
    if docs is None:
        docs = []
    return {
        "docs": docs,
        "metadata": {
            "result_size": {
                "match_count": total if total is not None else len(docs),
            },
            "paging": {"current": page, "last": last_page},
        },
    }


# ---------------------------------------------------------------------------
# Hydration data helpers (for HTML-scraped ad detail)
# ---------------------------------------------------------------------------


def _make_hydration_data(**overrides):
    data = {
        "title": "Antikt bord från 1800-tal",
        "description": "Vackert antikt bord i ek från sent 1800-tal. Gott skick med viss patina.",
        "price": 600,
        "meta": {"adId": "20753486", "edited": 1770668084000},
        "images": [
            {"uri": "https://images.blocketcdn.se/img1.jpg"},
            {"uri": "https://images.blocketcdn.se/img2.jpg"},
        ],
        "location": {"postalName": "Stockholm"},
        "category": {"value": "Möbler & Heminredning"},
        "extras": [
            {"label": "Skick", "value": "Begagnad"},
            {"label": "Märke", "value": "Okänt"},
        ],
    }
    data.update(overrides)
    return data


def _make_ad_html(item_data):
    hydration = {
        "loaderData": {
            "item-recommerce": {
                "itemData": item_data,
            }
        }
    }
    json_str = json.dumps(hydration, ensure_ascii=False)
    escaped = json_str.replace("\\", "\\\\").replace('"', '\\"')
    return f'<html><script>window.__staticRouterHydrationData = JSON.parse("{escaped}")</script></html>'


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


class TestBlocketSearch:
    @patch("storebot.tools.blocket.requests.get")
    def test_search_returns_formatted_results(self, mock_get, client):
        doc1 = _make_doc(ad_id=1, heading="Byrå", price={"amount": 1200, "currency_code": "SEK"})
        doc2 = _make_doc(ad_id=2, heading="Lampa", price={"amount": 350, "currency_code": "SEK"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_response(docs=[doc1, doc2], total=2)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.search("möbler")

        assert result["total"] == 2
        assert result["page"] == 1
        assert result["total_pages"] == 1
        assert len(result["items"]) == 2

        assert result["items"][0]["id"] == "1"
        assert result["items"][0]["title"] == "Byrå"
        assert result["items"][0]["price"] == 1200

        assert result["items"][1]["id"] == "2"
        assert result["items"][1]["title"] == "Lampa"
        assert result["items"][1]["price"] == 350

    @patch("storebot.tools.blocket.requests.get")
    def test_search_empty_results(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_response(docs=[], total=0)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.search("nonexistent")

        assert result["total"] == 0
        assert result["items"] == []
        assert "error" not in result

    @patch("storebot.tools.blocket.requests.get")
    def test_search_passes_query_params(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_response()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client.search("stol", category="0.78", region="0.300012", page=2)

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs["params"]
        assert params["q"] == "stol"
        assert params["category"] == "0.78"
        assert params["location"] == "0.300012"
        assert params["page"] == 2

    @patch("storebot.tools.blocket.requests.get")
    def test_search_sends_user_agent_only(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_response()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client.search("test")

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["User-Agent"] == USER_AGENT
        assert "Authorization" not in headers

    @patch("storebot.tools.blocket.requests.get")
    def test_search_handles_http_error(self, mock_get, client):
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        result = client.search("test")

        assert "error" in result
        assert "Connection refused" in result["error"]
        assert result["total"] == 0
        assert result["items"] == []

    @patch("storebot.tools.blocket.requests.get")
    def test_search_default_params(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_response()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client.search("bord")

        call_kwargs = mock_get.call_args
        assert call_kwargs.args[0] == SEARCH_URL
        params = call_kwargs.kwargs["params"]
        assert params["q"] == "bord"
        assert params["page"] == 1
        assert params["sort"] == "PUBLISHED_DESC"
        assert "category" not in params
        assert "location" not in params
        assert "price_from" not in params
        assert "price_to" not in params

    @patch("storebot.tools.blocket.requests.get")
    def test_search_item_fields(self, mock_get, client):
        doc = _make_doc()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_response(docs=[doc])
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.search("test")
        item = result["items"][0]

        assert item["id"] == "20753486"
        assert item["title"] == "Antikt bord från 1800-tal"
        assert item["price"] == 600
        assert item["currency"] == "SEK"
        assert item["url"] == "https://www.blocket.se/recommerce/forsale/item/20753486"
        assert "blocketcdn.se" in item["image_url"]
        assert item["location"] == "Stockholm"
        assert item["published"] == 1770668084000
        assert item["trade_type"] == "Säljes"

    @patch("storebot.tools.blocket.requests.get")
    def test_search_passes_price_filters(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_response()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client.search("bord", price_from=100, price_to=5000)

        params = mock_get.call_args.kwargs["params"]
        assert params["price_from"] == 100
        assert params["price_to"] == 5000

    @patch("storebot.tools.blocket.requests.get")
    def test_search_passes_sort(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_response()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client.search("bord", sort="PRICE_ASC")

        params = mock_get.call_args.kwargs["params"]
        assert params["sort"] == "PRICE_ASC"


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestBlocketEnums:
    def test_category_values(self):
        assert Category.MOBLER_OCH_INREDNING == "0.78"
        assert Category.KONST_OCH_ANTIKT == "0.76"

    def test_location_values(self):
        assert Location.STOCKHOLM == "0.300001"
        assert Location.SKANE == "0.300012"

    def test_sort_order_values(self):
        assert SortOrder.RELEVANCE == "RELEVANCE"
        assert SortOrder.PRICE_ASC == "PRICE_ASC"
        assert SortOrder.PUBLISHED_DESC == "PUBLISHED_DESC"


# ---------------------------------------------------------------------------
# Retry tests
# ---------------------------------------------------------------------------


class TestBlocketRetry:
    @patch("storebot.retry.time.sleep")
    @patch("storebot.tools.blocket.requests.get")
    def test_retries_on_5xx(self, mock_get, mock_sleep, client):
        resp_500 = MagicMock()
        resp_500.status_code = 500

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = _make_response(docs=[], total=0)
        resp_ok.raise_for_status = MagicMock()

        mock_get.side_effect = [resp_500, resp_ok]

        result = client.search("test")

        assert "error" not in result
        assert result["total"] == 0
        assert mock_sleep.call_count == 1


# ---------------------------------------------------------------------------
# Get ad tests (HTML scraping)
# ---------------------------------------------------------------------------


class TestBlocketGetAd:
    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_returns_full_detail(self, mock_get, client):
        item_data = _make_hydration_data()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _make_ad_html(item_data)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.get_ad("20753486")

        assert result["id"] == "20753486"
        assert result["title"] == "Antikt bord från 1800-tal"
        assert (
            result["description"]
            == "Vackert antikt bord i ek från sent 1800-tal. Gott skick med viss patina."
        )
        assert result["price"] == 600
        assert result["currency"] == "SEK"
        assert "20753486" in result["url"]
        assert len(result["images"]) == 2
        assert "img1.jpg" in result["images"][0]
        assert "img2.jpg" in result["images"][1]
        assert result["location"] == "Stockholm"
        assert result["category"] == "Möbler & Heminredning"
        assert result["published"] == 1770668084000
        assert result["parameters"]["Skick"] == "Begagnad"
        assert result["parameters"]["Märke"] == "Okänt"
        assert result["seller"] == {"name": "", "id": ""}

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_calls_correct_url(self, mock_get, client):
        item_data = _make_hydration_data()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _make_ad_html(item_data)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client.get_ad("12345")

        expected_url = AD_HTML_URL.format(ad_id="12345")
        call_args = mock_get.call_args
        assert call_args.args[0] == expected_url
        assert call_args.kwargs["timeout"] == 15

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_handles_not_found(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = client.get_ad("99999999")

        assert "error" in result
        assert "404" in result["error"]
        assert "99999999" in result["error"]

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_handles_connection_error(self, mock_get, client):
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        result = client.get_ad("20753486")

        assert "error" in result
        assert "Connection refused" in result["error"]

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_missing_hydration_data(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>No data here</body></html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.get_ad("20753486")

        assert "error" in result
        assert "Could not extract" in result["error"]

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_minimal_fields(self, mock_get, client):
        item_data = {
            "title": "Enkel stol",
            "price": 100,
            "meta": {"adId": "111"},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _make_ad_html(item_data)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.get_ad("111")

        assert result["id"] == "111"
        assert result["title"] == "Enkel stol"
        assert result["price"] == 100
        assert result["description"] == ""
        assert result["images"] == []
        assert result["parameters"] == {}
        assert result["seller"] == {"name": "", "id": ""}

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_price_as_int(self, mock_get, client):
        item_data = _make_hydration_data(price=1500)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _make_ad_html(item_data)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.get_ad("20753486")

        assert result["price"] == 1500

    @patch("storebot.retry.time.sleep")
    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_retries_on_5xx(self, mock_get, mock_sleep, client):
        resp_500 = MagicMock()
        resp_500.status_code = 500

        item_data = _make_hydration_data()
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.text = _make_ad_html(item_data)
        resp_ok.raise_for_status = MagicMock()

        mock_get.side_effect = [resp_500, resp_ok]

        result = client.get_ad("20753486")

        assert "error" not in result
        assert result["id"] == "20753486"
        assert mock_sleep.call_count == 1


# ---------------------------------------------------------------------------
# Hydration parser unit tests
# ---------------------------------------------------------------------------


class TestHydrationParser:
    def test_extract_hydration_data_valid(self):
        item_data = _make_hydration_data()
        html = _make_ad_html(item_data)

        result = _extract_hydration_data(html)

        assert result is not None
        assert result["title"] == "Antikt bord från 1800-tal"

    def test_extract_hydration_data_no_match(self):
        result = _extract_hydration_data("<html>no data</html>")
        assert result is None

    def test_extract_hydration_data_malformed_json(self):
        html = '<html><script>window.__staticRouterHydrationData = JSON.parse("not-valid-json")</script></html>'
        result = _extract_hydration_data(html)
        assert result is None

    def test_parse_hydration_item_maps_fields(self):
        data = _make_hydration_data()
        result = _parse_hydration_item(data, "20753486")

        assert result["id"] == "20753486"
        assert result["title"] == "Antikt bord från 1800-tal"
        assert result["price"] == 600
        assert result["currency"] == "SEK"
        assert result["location"] == "Stockholm"
        assert result["category"] == "Möbler & Heminredning"
        assert len(result["images"]) == 2

    def test_parse_hydration_item_empty_data(self):
        result = _parse_hydration_item({}, "999")

        assert result["id"] == "999"
        assert result["title"] == ""
        assert result["description"] == ""
        assert result["price"] == 0
        assert result["images"] == []
        assert result["seller"] == {"name": "", "id": ""}
