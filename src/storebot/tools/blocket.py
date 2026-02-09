class BlocketClient:
    """Client for Blocket's unofficial REST API.

    Read-only — useful for price research and sourcing.
    Bearer token extracted from browser session (expires, needs manual renewal).
    """

    def __init__(self, bearer_token: str):
        self.bearer_token = bearer_token

    def search(self, query: str, category: str | None = None, region: str | None = None):
        # TODO: Implement REST search via blocket-api
        raise NotImplementedError("BlocketClient.search not yet implemented")

    def get_ad(self, ad_id: str):
        # TODO: Implement REST ad detail fetch
        raise NotImplementedError("BlocketClient.get_ad not yet implemented")
