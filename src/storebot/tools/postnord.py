class PostNordClient:
    """Client for PostNord shipping label API."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def create_shipment(
        self,
        sender_name: str,
        sender_address: str,
        recipient_name: str,
        recipient_address: str,
        weight_grams: int,
    ):
        # TODO: Implement shipment creation via PostNord API
        raise NotImplementedError("PostNordClient.create_shipment not yet implemented")

    def get_label(self, shipment_id: str) -> bytes:
        # TODO: Implement label PDF retrieval
        raise NotImplementedError("PostNordClient.get_label not yet implemented")
