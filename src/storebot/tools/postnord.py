"""PostNord Shipping Label API client.

Supports creating shipments and retrieving PDF labels via the
PostNord Booking & Shipping API (REST).
"""

import base64
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from storebot.retry import retry_on_transient

logger = logging.getLogger(__name__)

SANDBOX_URL = "https://atapi2.postnord.com"
PRODUCTION_URL = "https://api2.postnord.com"


class PostNordError(Exception):
    """Error from PostNord API."""

    def __init__(self, message: str, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


@dataclass
class Address:
    """Postal address for sender or recipient."""

    name: str
    street: str
    postal_code: str
    city: str
    country_code: str = "SE"
    phone: str = ""
    email: str = ""


# Backwards-compatible aliases
SenderAddress = Address
RecipientAddress = Address


def parse_buyer_address(buyer_name: str, buyer_address: str) -> Address:
    """Parse a buyer address string into an Address.

    Handles formats:
      - "Storgatan 1, 123 45 Stockholm"
      - "Storgatan 1, 12345 Stockholm"
      - "Storgatan 1\\n123 45 Stockholm"
    """
    if not buyer_address or not buyer_address.strip():
        raise ValueError("Buyer address is empty")

    # Normalize: replace newlines with comma separator
    addr = buyer_address.replace("\n", ", ").strip()

    # Split on comma
    parts = [p.strip() for p in addr.split(",") if p.strip()]

    if len(parts) < 2:
        raise ValueError(f"Cannot parse address: {buyer_address!r}")

    street = parts[0]

    # Last part should contain postal code + city: "123 45 Stockholm" or "12345 Stockholm"
    postal_city = parts[-1]
    match = re.match(r"(\d{3}\s?\d{2})\s+(.+)", postal_city)
    if not match:
        # Fallback: treat entire last part as city, no postal code
        raise ValueError(f"Cannot parse postal code from: {postal_city!r}")

    postal_code = match.group(1).replace(" ", "")
    city = match.group(2).strip()

    return Address(
        name=buyer_name or "",
        street=street,
        postal_code=postal_code,
        city=city,
    )


class PostNordClient:
    """Client for PostNord Booking & Shipping API."""

    def __init__(self, api_key: str, sender: Address, sandbox: bool = True):
        self.api_key = api_key
        self.sender = sender
        self.base_url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self.session = requests.Session()

    @staticmethod
    def _address_to_payload(addr: Address) -> dict:
        """Convert an Address to the PostNord API party format."""
        return {
            "name": addr.name,
            "address": {
                "streetName": addr.street,
                "postalCode": addr.postal_code,
                "city": addr.city,
                "countryCode": addr.country_code,
            },
            "contact": {
                "emailAddress": addr.email,
                "phoneNo": addr.phone,
            },
        }

    def _build_shipment_payload(
        self,
        recipient: Address,
        weight_grams: int,
        reference: str = "",
        service_code: str = "19",
    ) -> dict:
        """Build the JSON payload for creating a shipment."""
        return {
            "shipment": {
                "service": {"basicServiceCode": service_code},
                "consignor": self._address_to_payload(self.sender),
                "consignee": self._address_to_payload(recipient),
                "parcels": [
                    {
                        "weight": {"value": weight_grams / 1000, "unit": "kg"},
                        "reference": reference,
                    }
                ],
            }
        }

    @retry_on_transient()
    def create_shipment(
        self,
        recipient: Address,
        weight_grams: int,
        reference: str = "",
        service_code: str = "19",
    ) -> dict:
        """Create a shipment and return tracking info.

        Service codes:
          19 = MyPack Collect (default)
          17 = MyPack Home
          18 = Postpaket

        Returns:
            dict with shipment_id, tracking_number, label_base64
        """
        url = f"{self.base_url}/rest/shipment/v3/shipments"
        payload = self._build_shipment_payload(recipient, weight_grams, reference, service_code)

        resp = self.session.post(
            url,
            json=payload,
            params={"apikey": self.api_key},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if resp.status_code >= 500:
            resp.raise_for_status()  # raises requests.HTTPError, retryable
        if resp.status_code == 401:
            raise PostNordError("Authentication failed — check API key", status_code=401)
        if resp.status_code >= 400:
            details = {}
            try:
                details = resp.json()
            except ValueError:
                pass
            raise PostNordError(
                f"PostNord API error: {resp.status_code}",
                status_code=resp.status_code,
                details=details,
            )

        data = resp.json()
        shipment_response = data.get("shipmentResponse", {})
        shipment_data = shipment_response.get("shipments", [{}])[0]
        parcel = shipment_data.get("parcels", [{}])[0]

        shipment_id = shipment_data.get("shipmentId", "")
        logger.info("Created PostNord shipment: %s", shipment_id)

        return {
            "shipment_id": shipment_id,
            "tracking_number": parcel.get("parcelNumber", ""),
            "label_base64": shipment_response.get("labelPrintout", ""),
        }

    @retry_on_transient()
    def get_label(self, shipment_id: str) -> bytes:
        """Retrieve the shipping label PDF for a shipment.

        Returns the raw PDF bytes.
        """
        url = f"{self.base_url}/rest/shipment/v3/labels"
        resp = self.session.get(
            url,
            params={"apikey": self.api_key, "shipmentId": shipment_id},
            timeout=30,
        )

        if resp.status_code >= 500:
            resp.raise_for_status()  # raises requests.HTTPError, retryable
        if resp.status_code == 404:
            raise PostNordError(
                f"Label not found for shipment {shipment_id}",
                status_code=404,
            )
        if resp.status_code >= 400:
            raise PostNordError(
                f"PostNord API error: {resp.status_code}",
                status_code=resp.status_code,
            )

        logger.info("Retrieved shipping label for shipment: %s", shipment_id)

        # Response may be direct PDF or JSON with base64
        content_type = resp.headers.get("Content-Type", "")
        if "application/pdf" in content_type:
            return resp.content

        # Fallback: JSON with base64-encoded PDF
        try:
            data = resp.json()
            b64 = data.get("labelPrintout", "")
            if b64:
                return base64.b64decode(b64)
        except (ValueError, KeyError):
            pass

        return resp.content

    def save_label(self, label_data: bytes, output_path: str) -> str:
        """Save label PDF to disk, creating directories as needed."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(label_data)
        return str(path)
