"""Tool definitions for the Claude API agent loop.

Each entry defines a tool name, description, and input schema that Claude
uses to decide when and how to call the tool.
"""

TOOLS = [
    {
        "name": "search_tradera",
        "description": "Search Tradera for items matching a query. Use for price research and finding comparable listings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "category": {"type": "string", "description": "Category filter (optional)"},
                "max_price": {"type": "number", "description": "Maximum price in SEK (optional)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_blocket",
        "description": "Search Blocket for items. Read-only, useful for price research and sourcing opportunities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "category": {"type": "string", "description": "Category filter (optional)"},
                "region": {"type": "string", "description": "Region filter (optional)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_blocket_ad",
        "description": "Get full details of a single Blocket ad including description, all images, seller info, and item parameters. Useful for deeper research on a specific item found via search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_id": {"type": "string", "description": "Blocket ad ID"},
            },
            "required": ["ad_id"],
        },
    },
    {
        "name": "create_draft_listing",
        "description": "Create a draft listing for a product. The draft must be approved before publishing. Use after price_check to set appropriate pricing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Local product ID"},
                "listing_type": {
                    "type": "string",
                    "enum": ["auction", "buy_it_now"],
                    "description": "Auction or fixed-price listing",
                },
                "listing_title": {"type": "string", "description": "Listing title in Swedish"},
                "listing_description": {
                    "type": "string",
                    "description": "Listing description in Swedish",
                },
                "platform": {
                    "type": "string",
                    "default": "tradera",
                    "description": "Platform (tradera/blocket)",
                },
                "start_price": {
                    "type": "number",
                    "description": "Auction start price in SEK (required for auctions)",
                },
                "buy_it_now_price": {
                    "type": "number",
                    "description": "Fixed price / buy-it-now price in SEK",
                },
                "duration_days": {
                    "type": "integer",
                    "enum": [3, 5, 7, 10, 14],
                    "description": "Listing duration in days (default 7)",
                },
                "tradera_category_id": {
                    "type": "integer",
                    "description": "Tradera category ID",
                },
                "details": {
                    "type": "object",
                    "description": "Additional details. Shipping: set 'shipping_options' (list of {cost, shipping_product_id, shipping_provider_id, name}) or 'shipping_cost' (flat int). Optional: 'shipping_condition' (str).",
                },
            },
            "required": ["product_id", "listing_type", "listing_title", "listing_description"],
        },
    },
    {
        "name": "list_draft_listings",
        "description": "List listings filtered by status. Defaults to showing drafts awaiting approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "default": "draft",
                    "description": "Filter by status: draft, approved, active, ended, sold",
                },
            },
        },
    },
    {
        "name": "get_draft_listing",
        "description": "Get full details of a single listing including preview.",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID"},
            },
            "required": ["listing_id"],
        },
    },
    {
        "name": "update_draft_listing",
        "description": "Update fields on a draft listing. Only drafts can be edited.",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID"},
                "listing_title": {"type": "string", "description": "New title"},
                "listing_description": {"type": "string", "description": "New description"},
                "listing_type": {
                    "type": "string",
                    "enum": ["auction", "buy_it_now"],
                    "description": "New listing type",
                },
                "start_price": {"type": "number", "description": "New start price"},
                "buy_it_now_price": {"type": "number", "description": "New buy-it-now price"},
                "duration_days": {
                    "type": "integer",
                    "enum": [3, 5, 7, 10, 14],
                    "description": "New duration",
                },
                "tradera_category_id": {"type": "integer", "description": "New category ID"},
                "details": {"type": "object", "description": "New details"},
            },
            "required": ["listing_id"],
        },
    },
    {
        "name": "approve_draft_listing",
        "description": "Approve a draft listing, moving it to 'approved' status ready for publishing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID to approve"},
            },
            "required": ["listing_id"],
        },
    },
    {
        "name": "publish_listing",
        "description": "Publish an approved listing to Tradera. Uploads images and creates the listing. The listing must be in 'approved' status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "Listing ID to publish",
                },
            },
            "required": ["listing_id"],
        },
    },
    {
        "name": "get_categories",
        "description": "Browse Tradera categories. Use to find the right category ID for a listing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "parent_id": {
                    "type": "integer",
                    "description": "Parent category ID (0 for top-level categories)",
                    "default": 0,
                },
            },
        },
    },
    {
        "name": "get_shipping_options",
        "description": "Hämta tillgängliga fraktalternativ från Tradera. Returnerar fraktprodukter med leverantör, viktgräns och pris. Använd produktens vikt för att filtrera.",
        "input_schema": {
            "type": "object",
            "properties": {
                "weight_grams": {
                    "type": "integer",
                    "description": "Paketets vikt i gram — filtrerar till alternativ som klarar vikten",
                },
            },
        },
    },
    {
        "name": "reject_draft_listing",
        "description": "Reject and delete a draft listing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID to reject"},
                "reason": {"type": "string", "description": "Reason for rejection"},
            },
            "required": ["listing_id"],
        },
    },
    {
        "name": "check_new_orders",
        "description": "Poll Tradera for new orders and import them locally. Creates order records and updates product/listing status.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_orders",
        "description": "List local orders, optionally filtered by status (pending/shipped/delivered/returned).",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "shipped", "delivered", "returned"],
                    "description": "Filter by order status (optional)",
                },
            },
        },
    },
    {
        "name": "get_order",
        "description": "Get full details of a specific order including product title.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "create_sale_voucher",
        "description": "Create an accounting voucher for a completed sale. Calculates VAT, revenue, and platform fees automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID to create voucher for"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "mark_order_shipped",
        "description": "Mark an order as shipped. Updates local status and notifies Tradera. NEVER use without explicit owner confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID to mark as shipped"},
                "tracking_number": {
                    "type": "string",
                    "description": "Tracking number (optional)",
                },
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "create_shipping_label",
        "description": "Skapa en fraktetikett via PostNord för en order. Kräver att produkten har weight_grams satt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
                "service_code": {
                    "type": "string",
                    "enum": ["19", "17", "18"],
                    "default": "19",
                    "description": "PostNord service: 19=MyPack Collect, 17=MyPack Home, 18=Postpaket",
                },
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "list_orders_pending_feedback",
        "description": "Lista Tradera-ordrar som är skickade men saknar omdöme till köparen.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "leave_feedback",
        "description": "Lämna omdöme till köparen på en Tradera-order. Lämna ALDRIG omdöme utan ägarens uttryckliga bekräftelse av texten.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
                "comment": {
                    "type": "string",
                    "maxLength": 80,
                    "description": "Omdömestext (max 80 tecken)",
                },
                "feedback_type": {
                    "type": "string",
                    "enum": ["Positive", "Negative"],
                    "default": "Positive",
                    "description": "Typ av omdöme",
                },
            },
            "required": ["order_id", "comment"],
        },
    },
    {
        "name": "create_voucher",
        "description": "Skapa en bokföringsverifikation och spara lokalt. Debet och kredit måste balansera.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Voucher description"},
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "account": {"type": "integer", "description": "BAS account number"},
                            "debit": {"type": "number"},
                            "credit": {"type": "number"},
                        },
                    },
                    "description": "Voucher rows (debit/credit per account)",
                },
                "order_id": {
                    "type": "integer",
                    "description": "Link to order ID (optional)",
                },
                "transaction_date": {
                    "type": "string",
                    "description": "Transaction date ISO format (default today)",
                },
            },
            "required": ["description", "rows"],
        },
    },
    {
        "name": "export_vouchers",
        "description": "Exportera verifikationer som PDF. Ange datumintervall.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_date": {
                    "type": "string",
                    "description": "Start date (ISO format, e.g. 2026-01-01)",
                },
                "to_date": {
                    "type": "string",
                    "description": "End date (ISO format, e.g. 2026-12-31)",
                },
            },
            "required": ["from_date", "to_date"],
        },
    },
    {
        "name": "price_check",
        "description": "Search both Tradera and Blocket for comparable items and compute price statistics with a suggested price range. Use for pricing research before listing a product.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query describing the item to price",
                },
                "product_id": {
                    "type": "integer",
                    "description": "Local product ID to link analysis to (optional)",
                },
                "category": {
                    "type": "string",
                    "description": "Category filter — Tradera int or Blocket string (optional)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_products",
        "description": "Search the local product database. Archived products are hidden by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "status": {
                    "type": "string",
                    "description": "Filter by status: draft, listed, sold, archived",
                },
                "include_archived": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include archived products in results (default false)",
                },
            },
        },
    },
    {
        "name": "create_product",
        "description": "Create a new product in the database. Use when the user wants to register a new item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Product title in Swedish"},
                "description": {"type": "string", "description": "Product description in Swedish"},
                "category": {
                    "type": "string",
                    "description": "Category (e.g. möbler, inredning, kuriosa, antikviteter)",
                },
                "condition": {
                    "type": "string",
                    "description": "Condition (e.g. renoverad, bra skick, slitage)",
                },
                "materials": {
                    "type": "string",
                    "description": "Materials (e.g. ek, mässing, glas)",
                },
                "era": {
                    "type": "string",
                    "description": "Era or period (e.g. 1940-tal, jugend, art deco)",
                },
                "dimensions": {"type": "string", "description": "Dimensions (e.g. 60x40x80 cm)"},
                "source": {
                    "type": "string",
                    "description": "Where it was acquired (e.g. loppis, dödsbo, tradera)",
                },
                "acquisition_cost": {"type": "number", "description": "Purchase cost in SEK"},
                "weight_grams": {
                    "type": "integer",
                    "description": "Weight in grams (required for shipping labels)",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_product",
        "description": "Uppdatera fält på en befintlig produkt. Ange bara de fält som ska ändras.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to update"},
                "title": {
                    "type": ["string", "null"],
                    "description": "Product title in Swedish (null to clear)",
                },
                "description": {
                    "type": ["string", "null"],
                    "description": "Detailed product description in Swedish (null to clear)",
                },
                "category": {
                    "type": ["string", "null"],
                    "description": "Product category (e.g. möbler, belysning, kuriosa)",
                },
                "condition": {
                    "type": ["string", "null"],
                    "description": "Condition (e.g. utmärkt skick, bra skick, renoveringsobjekt)",
                },
                "materials": {
                    "type": ["string", "null"],
                    "description": "Materials (e.g. ek, mässing, glas)",
                },
                "era": {
                    "type": ["string", "null"],
                    "description": "Era or period (e.g. 1940-tal, jugend, art deco)",
                },
                "dimensions": {
                    "type": ["string", "null"],
                    "description": "Dimensions (e.g. 60x40x80 cm)",
                },
                "source": {
                    "type": ["string", "null"],
                    "description": "Where it was acquired (e.g. loppis, dödsbo, tradera)",
                },
                "acquisition_cost": {
                    "type": ["number", "null"],
                    "description": "Purchase cost in SEK",
                },
                "weight_grams": {
                    "type": ["integer", "null"],
                    "description": "Weight in grams (required for shipping labels)",
                },
            },
            "required": ["product_id"],
        },
    },
    {
        "name": "get_product_images",
        "description": "Hämta och visa produktbilder. Använd för att granska bilder innan godkännande/publicering av annons.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "Product ID (optional if listing_id is given)",
                },
                "listing_id": {
                    "type": "integer",
                    "description": "Listing ID — resolves to product automatically (optional if product_id is given)",
                },
            },
        },
    },
    {
        "name": "save_product_image",
        "description": "Save an image to a product. Use after create_product to attach photos.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to attach image to"},
                "image_path": {"type": "string", "description": "File path to the image"},
                "is_primary": {
                    "type": "boolean",
                    "description": "Set as primary product image (default false)",
                },
            },
            "required": ["product_id", "image_path"],
        },
    },
    {
        "name": "archive_product",
        "description": "Archive a product, hiding it from normal search and listing views. Cannot archive products with active marketplace listings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to archive"},
            },
            "required": ["product_id"],
        },
    },
    {
        "name": "unarchive_product",
        "description": "Restore an archived product to its previous status (draft, listed, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to unarchive"},
            },
            "required": ["product_id"],
        },
    },
    {
        "name": "create_saved_search",
        "description": "Create a saved search for periodic sourcing. Searches run daily and new finds are reported.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'antik byrå')"},
                "platform": {
                    "type": "string",
                    "enum": ["tradera", "blocket", "both"],
                    "default": "both",
                    "description": "Which platform(s) to search",
                },
                "category": {
                    "type": "string",
                    "description": "Category filter (Tradera int ID or Blocket category name)",
                },
                "max_price": {"type": "number", "description": "Maximum price in SEK"},
                "region": {"type": "string", "description": "Region filter (Blocket only)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_saved_searches",
        "description": "List all saved searches. By default shows only active ones.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_inactive": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include deactivated searches",
                },
            },
        },
    },
    {
        "name": "update_saved_search",
        "description": "Update a saved search's query, platform, category, max_price, or region.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "integer", "description": "Saved search ID"},
                "query": {"type": "string", "description": "New search query"},
                "platform": {
                    "type": "string",
                    "enum": ["tradera", "blocket", "both"],
                    "description": "New platform filter",
                },
                "category": {"type": "string", "description": "New category filter"},
                "max_price": {"type": "number", "description": "New max price in SEK"},
                "region": {"type": "string", "description": "New region filter"},
            },
            "required": ["search_id"],
        },
    },
    {
        "name": "delete_saved_search",
        "description": "Deactivate a saved search (soft delete).",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "integer", "description": "Saved search ID to deactivate"},
            },
            "required": ["search_id"],
        },
    },
    {
        "name": "run_saved_search",
        "description": "Run a single saved search now and return new items found since last run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "integer", "description": "Saved search ID to run"},
            },
            "required": ["search_id"],
        },
    },
    {
        "name": "run_all_saved_searches",
        "description": "Run all active saved searches and produce a digest of new finds.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "refresh_listing_stats",
        "description": "Hämta aktuell statistik (visningar, bevakare, bud) från Tradera för aktiva annonser och spara en snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "Specific listing ID to refresh (optional, default all active)",
                },
            },
        },
    },
    {
        "name": "analyze_listing",
        "description": "Analysera en annons prestanda: konverteringsgrad, trend, dagar aktiv, potentiell vinst.",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID to analyze"},
            },
            "required": ["listing_id"],
        },
    },
    {
        "name": "get_performance_report",
        "description": "Sammanställ en övergripande marknadsföringsrapport: aktiva annonser, visningar, försäljning, kategorier, konverteringstratt.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_recommendations",
        "description": "Generera åtgärdsförslag för annonser: omlistning, prisjustering, förbättra innehåll, förläng, kategoritips.",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "Specific listing ID (optional, default all active+ended)",
                },
            },
        },
    },
    {
        "name": "business_summary",
        "description": "Affärssammanfattning för en period: intäkter, kostnader, bruttovinst, marginal, antal sålda, lagerstatus, snittid till försäljning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Period: YYYY-MM (månad), YYYY-QN (kvartal), YYYY (år). Utelämna för innevarande månad.",
                },
            },
        },
    },
    {
        "name": "profitability_report",
        "description": "Lönsamhetsrapport: nettovinst per produkt, aggregerat per kategori och inköpskälla. Topp/botten 5.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Period: YYYY-MM, YYYY-QN eller YYYY. Utelämna för innevarande månad.",
                },
            },
        },
    },
    {
        "name": "inventory_report",
        "description": "Lagerrapport: lagervärde, statusfördelning, åldersanalys (0-7d, 8-14d, 15-30d, 30+d), lista på gamla artiklar.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "period_comparison",
        "description": "Periodjämförelse: två perioder sida vid sida med skillnader i intäkter, vinst, antal och marginal. Standard: denna månad vs förra.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period_a": {
                    "type": "string",
                    "description": "Första perioden (YYYY-MM, YYYY-QN, YYYY). Standard: innevarande månad.",
                },
                "period_b": {
                    "type": "string",
                    "description": "Andra perioden att jämföra med. Standard: föregående månad.",
                },
            },
        },
    },
    {
        "name": "sourcing_analysis",
        "description": "Inköpskanalanalys: ROI per källa (loppis, dödsbo, tradera etc.), antal inköpta/sålda, marginal, snittid till försäljning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Period: YYYY-MM, YYYY-QN eller YYYY. Utelämna för innevarande månad.",
                },
            },
        },
    },
]
