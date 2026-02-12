import base64
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from storebot.tools.postnord import (
    PRODUCTION_URL,
    SANDBOX_URL,
    Address,
    PostNordClient,
    PostNordError,
    RecipientAddress,
    SenderAddress,
    parse_buyer_address,
)


@pytest.fixture
def sender():
    return Address(
        name="Lantshopen",
        street="Byvägen 5",
        postal_code="12345",
        city="Småstad",
        country_code="SE",
        phone="0701234567",
        email="shop@example.com",
    )


@pytest.fixture
def recipient():
    return Address(
        name="Anna Svensson",
        street="Storgatan 1",
        postal_code="11122",
        city="Stockholm",
    )


@pytest.fixture
def client(sender):
    return PostNordClient(api_key="test-key", sender=sender, sandbox=True)


class TestPostNordClientInit:
    def test_sandbox_url(self, sender):
        client = PostNordClient(api_key="key", sender=sender, sandbox=True)
        assert client.base_url == SANDBOX_URL

    def test_production_url(self, sender):
        client = PostNordClient(api_key="key", sender=sender, sandbox=False)
        assert client.base_url == PRODUCTION_URL


class TestBuildPayload:
    def test_payload_structure(self, client, recipient):
        payload = client._build_shipment_payload(recipient, weight_grams=2500)

        shipment = payload["shipment"]
        assert shipment["service"]["basicServiceCode"] == "19"
        assert shipment["consignor"]["name"] == "Lantshopen"
        assert shipment["consignor"]["address"]["streetName"] == "Byvägen 5"
        assert shipment["consignee"]["name"] == "Anna Svensson"
        assert shipment["consignee"]["address"]["streetName"] == "Storgatan 1"
        assert shipment["parcels"][0]["weight"]["value"] == 2.5
        assert shipment["parcels"][0]["weight"]["unit"] == "kg"

    def test_weight_conversion(self, client, recipient):
        payload = client._build_shipment_payload(recipient, weight_grams=500)
        assert payload["shipment"]["parcels"][0]["weight"]["value"] == 0.5

    def test_custom_service_code(self, client, recipient):
        payload = client._build_shipment_payload(recipient, weight_grams=1000, service_code="17")
        assert payload["shipment"]["service"]["basicServiceCode"] == "17"

    def test_reference(self, client, recipient):
        payload = client._build_shipment_payload(
            recipient, weight_grams=1000, reference="Order #42"
        )
        assert payload["shipment"]["parcels"][0]["reference"] == "Order #42"


class TestCreateShipment:
    def test_success(self, client, recipient):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "shipmentResponse": {
                "shipments": [
                    {
                        "shipmentId": "SH-001",
                        "parcels": [{"parcelNumber": "SE123456789"}],
                    }
                ],
                "labelPrintout": base64.b64encode(b"%PDF-1.4 test").decode(),
            }
        }

        with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
            result = client.create_shipment(recipient, weight_grams=2000)

        assert result["shipment_id"] == "SH-001"
        assert result["tracking_number"] == "SE123456789"
        assert result["label_base64"]

        # Verify API key passed as query param
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["params"]["apikey"] == "test-key"

    def test_auth_error(self, client, recipient):
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch.object(client.session, "post", return_value=mock_resp):
            with pytest.raises(PostNordError, match="Authentication failed"):
                client.create_shipment(recipient, weight_grams=2000)

    def test_server_error_raises_http_error(self, client, recipient):
        """5xx errors raise requests.HTTPError so the retry decorator can handle them."""
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)

        with patch.object(client.session, "post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                client.create_shipment(recipient, weight_grams=2000)

    def test_bad_request(self, client, recipient):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"errors": [{"message": "Invalid postal code"}]}

        with patch.object(client.session, "post", return_value=mock_resp):
            with pytest.raises(PostNordError) as exc_info:
                client.create_shipment(recipient, weight_grams=2000)
            assert exc_info.value.status_code == 400
            assert "Invalid postal code" in str(exc_info.value.details)

    def test_api_key_in_params(self, client, recipient):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "shipmentResponse": {
                "shipments": [{"shipmentId": "X", "parcels": [{"parcelNumber": "Y"}]}],
                "labelPrintout": "",
            }
        }

        with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
            client.create_shipment(recipient, weight_grams=1000)

        assert mock_post.call_args.kwargs["params"]["apikey"] == "test-key"

    def test_empty_label_response(self, client, recipient):
        """When no label is returned inline, label_base64 should be empty string."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "shipmentResponse": {
                "shipments": [{"shipmentId": "SH-002", "parcels": [{"parcelNumber": "SE999"}]}],
            }
        }

        with patch.object(client.session, "post", return_value=mock_resp):
            result = client.create_shipment(recipient, weight_grams=1000)

        assert result["label_base64"] == ""


class TestGetLabel:
    def test_pdf_response(self, client):
        pdf_bytes = b"%PDF-1.4 fake label content"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = pdf_bytes

        with patch.object(client.session, "get", return_value=mock_resp):
            result = client.get_label("SH-001")

        assert result == pdf_bytes

    def test_base64_json_response(self, client):
        pdf_bytes = b"%PDF-1.4 fake label"
        b64 = base64.b64encode(pdf_bytes).decode()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"labelPrintout": b64}
        mock_resp.content = json.dumps({"labelPrintout": b64}).encode()

        with patch.object(client.session, "get", return_value=mock_resp):
            result = client.get_label("SH-001")

        assert result == pdf_bytes

    def test_server_error_raises_http_error(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)

        with patch.object(client.session, "get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                client.get_label("SH-001")

    def test_not_found(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch.object(client.session, "get", return_value=mock_resp):
            with pytest.raises(PostNordError, match="Label not found"):
                client.get_label("SH-MISSING")


class TestSaveLabel:
    def test_saves_to_file(self, client, tmp_path):
        pdf_bytes = b"%PDF-1.4 test label"
        output = str(tmp_path / "labels" / "order_1.pdf")

        result = client.save_label(pdf_bytes, output)

        assert result == output
        with open(output, "rb") as f:
            assert f.read() == pdf_bytes


class TestParseBuyerAddress:
    def test_comma_separated(self):
        addr = parse_buyer_address("Anna Svensson", "Storgatan 1, 123 45 Stockholm")
        assert addr.name == "Anna Svensson"
        assert addr.street == "Storgatan 1"
        assert addr.postal_code == "12345"
        assert addr.city == "Stockholm"

    def test_no_space_in_postal_code(self):
        addr = parse_buyer_address("Erik", "Lilla gatan 3, 11122 Malmö")
        assert addr.postal_code == "11122"
        assert addr.city == "Malmö"

    def test_newline_separated(self):
        addr = parse_buyer_address("Lisa", "Parkvägen 10\n543 21 Göteborg")
        assert addr.street == "Parkvägen 10"
        assert addr.postal_code == "54321"
        assert addr.city == "Göteborg"

    def test_empty_address_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_buyer_address("Anna", "")

    def test_no_postal_code_raises(self):
        with pytest.raises(ValueError, match="Cannot parse postal code"):
            parse_buyer_address("Anna", "Storgatan 1, Stockholm")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_buyer_address("Anna", "   ")

    def test_country_code_defaults_to_se(self):
        addr = parse_buyer_address("Test", "Gatan 1, 12345 Stad")
        assert addr.country_code == "SE"


class TestBackwardsCompatibleAliases:
    def test_sender_address_is_address(self):
        assert SenderAddress is Address

    def test_recipient_address_is_address(self):
        assert RecipientAddress is Address
