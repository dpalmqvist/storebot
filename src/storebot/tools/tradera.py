class TraderaClient:
    """Client for Tradera SOAP API via zeep.

    Register at the Tradera Developer Program to get app_id and app_key.
    WSDL endpoints:
      - PublicService:     https://api.tradera.com/v3/publicservice.asmx?WSDL
      - RestrictedService: https://api.tradera.com/v3/restrictedservice.asmx?WSDL
      - SearchService:     https://api.tradera.com/v3/searchservice.asmx?WSDL
      - OrderService:      https://api.tradera.com/v3/orderservice.asmx?WSDL
    """

    def __init__(self, app_id: str, app_key: str):
        self.app_id = app_id
        self.app_key = app_key

    def search(self, query: str, category: str | None = None, max_price: float | None = None):
        # TODO: Implement via SearchService WSDL
        raise NotImplementedError("TraderaClient.search not yet implemented")

    def create_listing(
        self,
        title: str,
        description: str,
        price: float,
        category_id: int | None = None,
        images: list[str] | None = None,
    ):
        # TODO: Implement via RestrictedService AddItem
        raise NotImplementedError("TraderaClient.create_listing not yet implemented")

    def get_orders(self, status: str | None = None):
        # TODO: Implement via OrderService
        raise NotImplementedError("TraderaClient.get_orders not yet implemented")

    def get_item(self, item_id: int):
        # TODO: Implement via PublicService GetItem
        raise NotImplementedError("TraderaClient.get_item not yet implemented")
