from unittest.mock import MagicMock, patch

import pytest
import requests

from storebot.tools.blocket import AD_URL, BlocketClient, SEARCH_URL, USER_AGENT


@pytest.fixture
def client():
    return BlocketClient(bearer_token="test-token-123")


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


def _make_ad_detail(**overrides):
    detail = {
        "ad_id": 20753486,
        "id": "20753486",
        "heading": "Antikt bord från 1800-tal",
        "body": "Vackert antikt bord i ek från sent 1800-tal. Gott skick med viss patina.",
        "price": {"amount": 600, "currency_code": "SEK", "price_unit": "kr"},
        "canonical_url": "https://www.blocket.se/recommerce/forsale/item/20753486",
        "images": [
            {"url": "https://images.blocketcdn.se/dynamic/default/item/20753486/img1.jpg"},
            {"url": "https://images.blocketcdn.se/dynamic/default/item/20753486/img2.jpg"},
        ],
        "location": "Stockholm",
        "timestamp": 1770668084000,
        "trade_type": "Säljes",
        "category": "Möbler & Heminredning",
        "seller": {"name": "MöbelSansen", "id": 98765},
        "parameters": [
            {"label": "Skick", "value": "Begagnad"},
            {"label": "Märke", "value": "Okänt"},
        ],
    }
    detail.update(overrides)
    return detail


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
    def test_search_sends_auth_header(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_response()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client.search("test")

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-token-123"
        assert headers["User-Agent"] == USER_AGENT

    def test_rejects_empty_bearer_token(self):
        with pytest.raises(ValueError, match="bearer_token must not be empty"):
            BlocketClient(bearer_token="")

    @patch("storebot.tools.blocket.requests.get")
    def test_search_handles_http_error(self, mock_get, client):
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        result = client.search("test")

        assert "error" in result
        assert "Connection refused" in result["error"]
        assert result["total"] == 0
        assert result["items"] == []

    @patch("storebot.tools.blocket.requests.get")
    def test_search_handles_expired_token(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        result = client.search("test")

        assert "error" in result
        assert "401" in result["error"]
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()
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

    @patch("storebot.retry.time.sleep")
    @patch("storebot.tools.blocket.requests.get")
    def test_no_retry_on_401(self, mock_get, mock_sleep, client):
        resp_401 = MagicMock()
        resp_401.status_code = 401
        mock_get.return_value = resp_401

        result = client.search("test")

        assert "error" in result
        assert "401" in result["error"]
        mock_sleep.assert_not_called()


class TestBlocketGetAd:
    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_returns_full_detail(self, mock_get, client):
        detail = _make_ad_detail()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = detail
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
        assert result["url"] == "https://www.blocket.se/recommerce/forsale/item/20753486"
        assert len(result["images"]) == 2
        assert "img1.jpg" in result["images"][0]
        assert "img2.jpg" in result["images"][1]
        assert result["location"] == "Stockholm"
        assert result["category"] == "Möbler & Heminredning"
        assert result["seller"]["name"] == "MöbelSansen"
        assert result["seller"]["id"] == "98765"
        assert result["published"] == 1770668084000
        assert result["trade_type"] == "Säljes"
        assert result["parameters"]["Skick"] == "Begagnad"
        assert result["parameters"]["Märke"] == "Okänt"

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_calls_correct_url(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_ad_detail()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client.get_ad("12345")

        expected_url = AD_URL.format(ad_id="12345")
        call_args = mock_get.call_args
        assert call_args.args[0] == expected_url
        assert call_args.kwargs["timeout"] == 15

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_sends_auth_header(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_ad_detail()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client.get_ad("20753486")

        headers = mock_get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-token-123"
        assert headers["User-Agent"] == USER_AGENT

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_handles_expired_token(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        result = client.get_ad("20753486")

        assert "error" in result
        assert "401" in result["error"]

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
    def test_get_ad_missing_optional_fields(self, mock_get, client):
        """Ad with minimal fields still parses without errors."""
        minimal = {
            "ad_id": 111,
            "heading": "Enkel stol",
            "price": {"amount": 100, "currency_code": "SEK"},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = minimal
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
    def test_get_ad_falls_back_to_single_image(self, mock_get, client):
        """When images list is missing, falls back to single image field."""
        detail = _make_ad_detail()
        del detail["images"]
        detail["image"] = {"url": "https://images.blocketcdn.se/fallback.jpg"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = detail
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.get_ad("20753486")

        assert len(result["images"]) == 1
        assert "fallback.jpg" in result["images"][0]

    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_location_as_dict(self, mock_get, client):
        """Location can be returned as a dict with a name field."""
        detail = _make_ad_detail(location={"name": "Göteborg", "region": "Västra Götaland"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = detail
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.get_ad("20753486")

        assert result["location"] == "Göteborg"

    @patch("storebot.retry.time.sleep")
    @patch("storebot.tools.blocket.requests.get")
    def test_get_ad_retries_on_5xx(self, mock_get, mock_sleep, client):
        resp_500 = MagicMock()
        resp_500.status_code = 500

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = _make_ad_detail()
        resp_ok.raise_for_status = MagicMock()

        mock_get.side_effect = [resp_500, resp_ok]

        result = client.get_ad("20753486")

        assert "error" not in result
        assert result["id"] == "20753486"
        assert mock_sleep.call_count == 1
