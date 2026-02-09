class FortnoxClient:
    """Client for Fortnox REST API with OAuth2 authentication.

    Requires developer/partner account. Key endpoints:
      - /3/vouchers — bookkeeping vouchers
      - /3/invoices — customer invoices
      - /3/supplierinvoices — supplier invoices
      - /3/inbox — receipt/document upload
    """

    def __init__(self, client_id: str, client_secret: str, access_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token

    def create_voucher(self, description: str, rows: list[dict]):
        # TODO: POST /3/vouchers with VoucherRows
        raise NotImplementedError("FortnoxClient.create_voucher not yet implemented")

    def get_vouchers(self, financial_year: int | None = None):
        # TODO: GET /3/vouchers
        raise NotImplementedError("FortnoxClient.get_vouchers not yet implemented")

    def upload_receipt(self, file_path: str):
        # TODO: POST /3/inbox (multipart/form-data)
        raise NotImplementedError("FortnoxClient.upload_receipt not yet implemented")

    def create_customer(self, name: str, address: str | None = None):
        # TODO: POST /3/customers
        raise NotImplementedError("FortnoxClient.create_customer not yet implemented")
