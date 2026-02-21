"""Tool definitions for the Claude API agent loop.

Each entry defines a tool name, description, and input schema that Claude
uses to decide when and how to call the tool.

Optional parameters are omitted from ``required`` — Claude leaves them out
when not needed.  Tools with only required parameters use ``strict: true``
for guaranteed schema-valid calls; tools with optional parameters omit it.

Each tool also carries a ``category`` tag used by the dynamic tool filtering
in ``agent.py`` to send only relevant tools per turn.
"""

# Shared sub-schema for listing details (shipping, reserve price).
# Used by create_draft_listing, update_draft_listing, and relist_product.
_DETAILS_SCHEMA = {
    "type": "object",
    "properties": {
        "shipping_options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cost": {"type": "number"},
                    "shipping_product_id": {"type": "integer"},
                    "shipping_provider_id": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": [
                    "cost",
                    "shipping_product_id",
                    "shipping_provider_id",
                    "name",
                ],
                "additionalProperties": False,
            },
        },
        "shipping_cost": {"type": "number"},
        "shipping_condition": {"type": "string"},
        "reserve_price": {"type": "number"},
        "item_attributes": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Lista med attribut-ID:n (ItemAttributes) som krävs av kategorin",
        },
        "attribute_values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Attribut-ID från get_attribute_definitions",
                    },
                    "name": {"type": "string", "description": "Attributnamn"},
                    "values": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Valda värden (från possible_values)",
                    },
                    "type": {
                        "type": "string",
                        "description": "term (standard) eller number",
                    },
                },
                "required": ["id", "values"],
                "additionalProperties": False,
            },
            "description": "Kategoriattribut med valda värden",
        },
    },
    "additionalProperties": False,
}

# Schema for the optional period parameter shared by analytics tools.
_PERIOD_SCHEMA = {
    "type": "object",
    "properties": {
        "period": {
            "type": "string",
            "description": "Period: YYYY-MM (månad), YYYY-QN (kvartal), YYYY (år). Standard: innevarande månad.",
        },
    },
    "additionalProperties": False,
}

# Schema for tools that take no parameters.
_EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

TOOLS = [
    # --- Tradera ---
    {
        "name": "search_tradera",
        "description": "Search Tradera for items matching a query. Use for price research and finding comparable listings.",
        "category": "research",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "category": {
                    "type": "string",
                    "description": "Category filter (omit to skip)",
                },
                "max_price": {
                    "type": "number",
                    "description": "Maximum price in SEK (omit to skip)",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_tradera_item",
        "description": "Hämta fullständig information om ett enskilt Tradera-objekt via dess ID. Använd för att se detaljer, slutpris, köpare etc.",
        "category": "research",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "Tradera item ID"},
            },
            "required": ["item_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_categories",
        "description": "Sök i Traderas kategorihierarki (DB-backad). Returnerar kategorier med fullständig sökväg (t.ex. Möbler > Vardagsrum > Soffor) och beskrivningar. Utan query returneras toppkategorierna. Synkas från API med storebot-sync-categories.",
        "category": "listing",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Sökord för att filtrera kategorier på namn eller sökväg (t.ex. 'möbler', 'antik')",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_shipping_options",
        "description": "Hämta tillgängliga fraktalternativ från Tradera. Returnerar en lista med fälten shipping_product_id, shipping_provider_id, cost, name m.fl. — skicka valda alternativ direkt till shipping_options i update_draft_listing. Använd produktens vikt för att filtrera.",
        "category": "listing",
        "input_schema": {
            "type": "object",
            "properties": {
                "weight_grams": {
                    "type": "integer",
                    "description": "Paketets vikt i gram — filtrerar till alternativ som klarar vikten",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_shipping_types",
        "description": "Hämta alla tillgängliga frakttyper (leveransvillkor) från Tradera. Returnerar en lista med ID och namn.",
        "category": "listing",
        "strict": True,
        "input_schema": _EMPTY_SCHEMA,
    },
    {
        "name": "get_attribute_definitions",
        "description": "Hämta attributdefinitioner för en Tradera-kategori. Visar vilka egenskaper (material, tidsepok, skick) som krävs eller är valfria. Använd innan approve_draft_listing.",
        "category": "listing",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "category_id": {"type": "integer", "description": "Tradera category ID"},
            },
            "required": ["category_id"],
            "additionalProperties": False,
        },
    },
    # --- Blocket ---
    {
        "name": "search_blocket",
        "description": "Search Blocket for items. Read-only, useful for price research and sourcing opportunities. No auth needed.",
        "category": "research",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "category": {
                    "type": "string",
                    "description": "Category ID, e.g. '0.78' (Möbler & Inredning), '0.76' (Konst & Antikt)",
                },
                "region": {
                    "type": "string",
                    "description": "Region ID, e.g. '0.300001' (Stockholm), '0.300012' (Skåne)",
                },
                "price_from": {
                    "type": "integer",
                    "description": "Minimum price filter in SEK",
                },
                "price_to": {
                    "type": "integer",
                    "description": "Maximum price filter in SEK",
                },
                "sort": {
                    "type": "string",
                    "description": "Sort order (omit defaults to PUBLISHED_DESC)",
                    "enum": [
                        "RELEVANCE",
                        "PRICE_DESC",
                        "PRICE_ASC",
                        "PUBLISHED_DESC",
                        "PUBLISHED_ASC",
                    ],
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_blocket_ad",
        "description": "Get full details of a single Blocket ad including description, all images, and item parameters. Uses HTML scraping, no auth needed.",
        "category": "research",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_id": {"type": "string", "description": "Blocket ad ID"},
            },
            "required": ["ad_id"],
            "additionalProperties": False,
        },
    },
    # --- Pricing ---
    {
        "name": "price_check",
        "description": "Search both Tradera and Blocket for comparable items and compute price statistics with a suggested price range. Use for pricing research before listing a product.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query describing the item to price",
                },
                "product_id": {
                    "type": "integer",
                    "description": "Local product ID to link analysis to (omit to skip)",
                },
                "category": {
                    "type": "string",
                    "description": "Category filter — Tradera int or Blocket string (omit to skip)",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    # --- Listings ---
    {
        "name": "create_draft_listing",
        "description": "Create a draft listing for a product. The draft must be approved before publishing. Use after price_check to set appropriate pricing.",
        "category": "listing",
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
                    "description": "Platform: tradera or blocket (omit defaults to tradera)",
                },
                "start_price": {
                    "type": "number",
                    "description": "Auction start price in SEK (required for auctions)",
                },
                "buy_it_now_price": {
                    "type": "number",
                    "description": "Fixed price / buy-it-now price in SEK (omit to skip)",
                },
                "duration_days": {
                    "type": "integer",
                    "enum": [3, 5, 7, 10, 14],
                    "description": "Listing duration in days (omit defaults to 7)",
                },
                "tradera_category_id": {
                    "type": "integer",
                    "description": "Tradera category ID (omit to skip)",
                },
                "details": {
                    **_DETAILS_SCHEMA,
                    "description": "Shipping and extra details (omit to skip). Set shipping_options OR shipping_cost, not both.",
                },
            },
            "required": [
                "product_id",
                "listing_type",
                "listing_title",
                "listing_description",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_draft_listings",
        "description": "List listings filtered by status. Defaults to showing drafts awaiting approval.",
        "category": "listing",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: draft, approved, active, ended, sold (omit defaults to draft)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_draft_listing",
        "description": "Get full details of a single listing including preview.",
        "category": "listing",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID"},
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_draft_listing",
        "description": "Update fields on a draft listing. Only drafts can be edited. Only include fields to change.",
        "category": "listing",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID"},
                "listing_title": {
                    "type": "string",
                    "description": "New title (omit to keep current)",
                },
                "listing_description": {
                    "type": "string",
                    "description": "New description (omit to keep current)",
                },
                "listing_type": {
                    "type": "string",
                    "enum": ["auction", "buy_it_now"],
                    "description": "New listing type (omit to keep current)",
                },
                "start_price": {
                    "type": "number",
                    "description": "New start price (omit to keep current)",
                },
                "buy_it_now_price": {
                    "type": "number",
                    "description": "New buy-it-now price (omit to keep current)",
                },
                "duration_days": {
                    "type": "integer",
                    "enum": [3, 5, 7, 10, 14],
                    "description": "New duration (omit to keep current)",
                },
                "tradera_category_id": {
                    "type": "integer",
                    "description": "New category ID (omit to keep current)",
                },
                "details": {
                    **_DETAILS_SCHEMA,
                    "description": "New details (omit to keep current)",
                },
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "approve_draft_listing",
        "description": "Approve a draft listing, moving it to 'approved' status ready for publishing.",
        "category": "listing",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID to approve"},
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "revise_draft_listing",
        "description": "Move an approved listing back to draft status for editing. Use when changes are needed before publishing.",
        "category": "listing",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID to revise"},
                "reason": {
                    "type": "string",
                    "description": "Reason for revision (for audit trail)",
                },
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reject_draft_listing",
        "description": "Reject and delete a draft listing.",
        "category": "listing",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID to reject"},
                "reason": {
                    "type": "string",
                    "description": "Reason for rejection",
                },
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "publish_listing",
        "description": "Publish an approved listing to Tradera. Uploads images and creates the listing. The listing must be in 'approved' status.",
        "category": "listing",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "Listing ID to publish",
                },
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "relist_product",
        "description": "Skapa ett nytt annonsutkast genom att kopiera från en avslutad eller såld annons. Kräver godkännande innan publicering. Inkludera bara fält som ska ändras.",
        "category": "listing",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "ID på den avslutade/sålda annonsen att kopiera från",
                },
                "listing_title": {
                    "type": "string",
                    "description": "Ny titel (omit to keep original)",
                },
                "listing_description": {
                    "type": "string",
                    "description": "Ny beskrivning (omit to keep original)",
                },
                "listing_type": {
                    "type": "string",
                    "enum": ["auction", "buy_it_now"],
                    "description": "Ny annonstyp (omit to keep original)",
                },
                "start_price": {
                    "type": "number",
                    "description": "Nytt startpris (omit to keep original)",
                },
                "buy_it_now_price": {
                    "type": "number",
                    "description": "Nytt köp nu-pris (omit to keep original)",
                },
                "duration_days": {
                    "type": "integer",
                    "enum": [3, 5, 7, 10, 14],
                    "description": "Ny varaktighet i dagar (omit to keep original)",
                },
                "tradera_category_id": {
                    "type": "integer",
                    "description": "Ny Tradera-kategori (omit to keep original)",
                },
                "details": {
                    **_DETAILS_SCHEMA,
                    "description": "Nya detaljer/frakt (omit to keep original)",
                },
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cancel_listing",
        "description": "Avbryt en aktiv annons lokalt. OBS: Tradera har inget API för att avbryta annonser — det måste göras manuellt på plattformen.",
        "category": "listing",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "Listing ID att avbryta",
                },
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    # --- Products ---
    {
        "name": "search_products",
        "description": "Search the local product database. Archived products are hidden by default.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (omit to list all)",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: draft, listed, sold, archived (omit to show all non-archived)",
                },
                "include_archived": {
                    "type": "boolean",
                    "description": "Include archived products in results (omit defaults to false)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "create_product",
        "description": "Create a new product in the database. Use when the user wants to register a new item.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Product title in Swedish"},
                "description": {
                    "type": "string",
                    "description": "Product description in Swedish",
                },
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
                "dimensions": {
                    "type": "string",
                    "description": "Dimensions (e.g. 60x40x80 cm)",
                },
                "source": {
                    "type": "string",
                    "description": "Where it was acquired (e.g. loppis, dödsbo, tradera)",
                },
                "acquisition_cost": {
                    "type": "number",
                    "description": "Purchase cost in SEK",
                },
                "weight_grams": {
                    "type": "integer",
                    "description": "Weight in grams (needed for shipping labels)",
                },
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_product",
        "description": "Uppdatera fält på en befintlig produkt. Inkludera bara de fält som ska ändras.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to update"},
                "title": {
                    "type": "string",
                    "description": "New title (omit to keep current)",
                },
                "description": {
                    "type": "string",
                    "description": "New description (omit to keep current)",
                },
                "category": {
                    "type": "string",
                    "description": "New category (omit to keep current)",
                },
                "condition": {
                    "type": "string",
                    "description": "New condition (omit to keep current)",
                },
                "materials": {
                    "type": "string",
                    "description": "New materials (omit to keep current)",
                },
                "era": {
                    "type": "string",
                    "description": "New era (omit to keep current)",
                },
                "dimensions": {
                    "type": "string",
                    "description": "New dimensions (omit to keep current)",
                },
                "source": {
                    "type": "string",
                    "description": "New source (omit to keep current)",
                },
                "acquisition_cost": {
                    "type": "number",
                    "description": "New cost in SEK (omit to keep current)",
                },
                "weight_grams": {
                    "type": "integer",
                    "description": "New weight in grams (omit to keep current)",
                },
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_product",
        "description": "Hämta fullständig information om en produkt: alla fält, antal bilder och aktiva annonser. Använd för att se detaljer som saknas i search_products (beskrivning, material, mått, vikt, källa).",
        "category": "core",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID"},
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
    },
    # --- Product images ---
    {
        "name": "save_product_image",
        "description": "Save an image to a product. Use after create_product to attach photos.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to attach image to"},
                "image_path": {"type": "string", "description": "File path to the image"},
                "is_primary": {
                    "type": "boolean",
                    "description": "Set as primary product image (omit defaults to false)",
                },
            },
            "required": ["product_id", "image_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_product_images",
        "description": "Hämta och visa produktbilder. Använd för att granska bilder innan godkännande/publicering av annons.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "Product ID (provide this or listing_id)",
                },
                "listing_id": {
                    "type": "integer",
                    "description": "Listing ID — resolves to product automatically (provide this or product_id)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_product_image",
        "description": "Ta bort en produktbild. Om bilden var primär blir nästa bild primär automatiskt.",
        "category": "core",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "image_id": {"type": "integer", "description": "Image ID att ta bort"},
            },
            "required": ["image_id"],
            "additionalProperties": False,
        },
    },
    # --- Archive ---
    {
        "name": "archive_product",
        "description": "Archive a product, hiding it from normal search and listing views. Cannot archive products with active marketplace listings.",
        "category": "core",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to archive"},
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "unarchive_product",
        "description": "Restore an archived product to its previous status (draft, listed, etc.).",
        "category": "core",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to unarchive"},
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
    },
    # --- Orders ---
    {
        "name": "check_new_orders",
        "description": "Poll Tradera for new orders and import them locally. Creates order records and updates product/listing status.",
        "category": "order",
        "strict": True,
        "input_schema": _EMPTY_SCHEMA,
    },
    {
        "name": "list_orders",
        "description": "List local orders, optionally filtered by status (pending/shipped/delivered/returned).",
        "category": "order",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "shipped", "delivered", "returned"],
                    "description": "Filter by order status (omit to show all)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_order",
        "description": "Get full details of a specific order including product title.",
        "category": "order",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_sale_voucher",
        "description": "Create an accounting voucher for a completed sale. Calculates VAT, revenue, and platform fees automatically.",
        "category": "order",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID to create voucher for"},
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mark_order_shipped",
        "description": "Mark an order as shipped. Updates local status and notifies Tradera. NEVER use without explicit owner confirmation.",
        "category": "order",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID to mark as shipped"},
                "tracking_number": {
                    "type": "string",
                    "description": "Tracking number",
                },
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_shipping_label",
        "description": "Skapa en fraktetikett via PostNord för en order. Kräver att produkten har weight_grams satt.",
        "category": "order",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
                "service_code": {
                    "type": "string",
                    "enum": ["19", "17", "18"],
                    "description": "PostNord service: 19=MyPack Collect, 17=MyPack Home, 18=Postpaket (standard: 19)",
                },
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_orders_pending_feedback",
        "description": "Lista Tradera-ordrar som är skickade men saknar omdöme till köparen.",
        "category": "order",
        "strict": True,
        "input_schema": _EMPTY_SCHEMA,
    },
    {
        "name": "leave_feedback",
        "description": "Lämna omdöme till köparen på en Tradera-order. Lämna ALDRIG omdöme utan ägarens uttryckliga bekräftelse av texten.",
        "category": "order",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
                "comment": {
                    "type": "string",
                    "description": "Omdömestext (max 80 tecken)",
                },
                "feedback_type": {
                    "type": "string",
                    "enum": ["Positive", "Negative"],
                    "description": "Typ av omdöme (standard: Positive)",
                },
            },
            "required": ["order_id", "comment"],
            "additionalProperties": False,
        },
    },
    # --- Accounting ---
    {
        "name": "create_voucher",
        "description": "Skapa en bokföringsverifikation och spara lokalt. Debet och kredit måste balansera.",
        "category": "accounting",
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
                            "debit": {"type": "number", "description": "Debit amount"},
                            "credit": {"type": "number", "description": "Credit amount"},
                        },
                        "required": ["account", "debit", "credit"],
                        "additionalProperties": False,
                    },
                    "description": "Voucher rows (debit/credit per account)",
                },
                "order_id": {
                    "type": "integer",
                    "description": "Link to order ID",
                },
                "transaction_date": {
                    "type": "string",
                    "description": "Transaction date ISO format (omit defaults to today)",
                },
            },
            "required": ["description", "rows"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_vouchers",
        "description": "Lista bokföringsverifikationer, valfritt filtrerade efter datumintervall.",
        "category": "accounting",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_date": {
                    "type": "string",
                    "description": "Startdatum (ISO-format, t.ex. 2026-01-01)",
                },
                "to_date": {
                    "type": "string",
                    "description": "Slutdatum (ISO-format, t.ex. 2026-12-31)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "export_vouchers",
        "description": "Exportera verifikationer som PDF. Ange datumintervall.",
        "category": "accounting",
        "strict": True,
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
            "additionalProperties": False,
        },
    },
    # --- Scout ---
    {
        "name": "create_saved_search",
        "description": "Create a saved search for periodic sourcing. Searches run daily and new finds are reported.",
        "category": "scout",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'antik byrå')"},
                "platform": {
                    "type": "string",
                    "enum": ["tradera", "blocket", "both"],
                    "description": "Which platform(s) to search (omit defaults to both)",
                },
                "category": {
                    "type": "string",
                    "description": "Category filter (Tradera int ID or Blocket category name)",
                },
                "max_price": {
                    "type": "number",
                    "description": "Maximum price in SEK",
                },
                "region": {
                    "type": "string",
                    "description": "Region filter (Blocket only)",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_saved_searches",
        "description": "List all saved searches. By default shows only active ones.",
        "category": "scout",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_inactive": {
                    "type": "boolean",
                    "description": "Include deactivated searches (omit defaults to false)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "update_saved_search",
        "description": "Update a saved search. Only include fields to change.",
        "category": "scout",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "integer", "description": "Saved search ID"},
                "query": {
                    "type": "string",
                    "description": "New search query (omit to keep current)",
                },
                "platform": {
                    "type": "string",
                    "enum": ["tradera", "blocket", "both"],
                    "description": "New platform filter (omit to keep current)",
                },
                "category": {
                    "type": "string",
                    "description": "New category filter (omit to keep current)",
                },
                "max_price": {
                    "type": "number",
                    "description": "New max price in SEK (omit to keep current)",
                },
                "region": {
                    "type": "string",
                    "description": "New region filter (omit to keep current)",
                },
            },
            "required": ["search_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_saved_search",
        "description": "Deactivate a saved search (soft delete).",
        "category": "scout",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "integer", "description": "Saved search ID to deactivate"},
            },
            "required": ["search_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_saved_search",
        "description": "Run a single saved search now and return new items found since last run.",
        "category": "scout",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "integer", "description": "Saved search ID to run"},
            },
            "required": ["search_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_all_saved_searches",
        "description": "Run all active saved searches and produce a digest of new finds.",
        "category": "scout",
        "strict": True,
        "input_schema": _EMPTY_SCHEMA,
    },
    # --- Marketing ---
    {
        "name": "refresh_listing_stats",
        "description": "Hämta aktuell statistik (visningar, bevakare, bud) från Tradera för aktiva annonser och spara en snapshot.",
        "category": "marketing",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "Specific listing ID to refresh (omit to refresh all active)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "analyze_listing",
        "description": "Analysera en annons prestanda: konverteringsgrad, trend, dagar aktiv, potentiell vinst.",
        "category": "marketing",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID to analyze"},
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_performance_report",
        "description": "Sammanställ en övergripande marknadsföringsrapport: aktiva annonser, visningar, försäljning, kategorier, konverteringstratt.",
        "category": "marketing",
        "strict": True,
        "input_schema": _EMPTY_SCHEMA,
    },
    {
        "name": "get_recommendations",
        "description": "Generera åtgärdsförslag för annonser: omlistning, prisjustering, förbättra innehåll, förläng, kategoritips.",
        "category": "marketing",
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "Specific listing ID (omit to show all active+ended)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "listing_dashboard",
        "description": "Daglig annonsrapport: visa per-annons-statistik (visningar, bud, bevakare, pris, dagar kvar, trend) med dagliga förändringar för alla aktiva Tradera-annonser.",
        "category": "marketing",
        "strict": True,
        "input_schema": _EMPTY_SCHEMA,
    },
    # --- Analytics ---
    {
        "name": "business_summary",
        "description": "Affärssammanfattning för en period: intäkter, kostnader, bruttovinst, marginal, antal sålda, lagerstatus, snittid till försäljning.",
        "category": "analytics",
        "input_schema": _PERIOD_SCHEMA,
    },
    {
        "name": "profitability_report",
        "description": "Lönsamhetsrapport: nettovinst per produkt, aggregerat per kategori och inköpskälla. Topp/botten 5.",
        "category": "analytics",
        "input_schema": _PERIOD_SCHEMA,
    },
    {
        "name": "inventory_report",
        "description": "Lagerrapport: lagervärde, statusfördelning, åldersanalys (0-7d, 8-14d, 15-30d, 30+d), lista på gamla artiklar.",
        "category": "analytics",
        "strict": True,
        "input_schema": _EMPTY_SCHEMA,
    },
    {
        "name": "period_comparison",
        "description": "Periodjämförelse: två perioder sida vid sida med skillnader i intäkter, vinst, antal och marginal. Standard: denna månad vs förra.",
        "category": "analytics",
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
            "additionalProperties": False,
        },
    },
    {
        "name": "sourcing_analysis",
        "description": "Inköpskanalanalys: ROI per källa (loppis, dödsbo, tradera etc.), antal inköpta/sålda, marginal, snittid till försäljning.",
        "category": "analytics",
        "input_schema": _PERIOD_SCHEMA,
    },
    {
        "name": "usage_report",
        "description": "Visa API-tokenförbrukning och kostnad per dag/månad. Visar input/output-tokens, cache-effektivitet och kostnad i SEK.",
        "category": "analytics",
        "input_schema": _PERIOD_SCHEMA,
    },
    # --- Meta ---
    {
        "name": "request_tools",
        "description": (
            "Begär fler verktyg genom att ange kategorier. "
            "Tillgängliga kategorier: core (produkter, bilder, priskoll), "
            "research (Tradera/Blocket-sök), listing (annonser, frakt, kategorier), "
            "order (ordrar, leverans, omdöme), accounting (bokföring, verifikationer), "
            "scout (sparade sökningar), marketing (annonsstatistik, rekommendationer), "
            "analytics (rapporter, lönsamhet, lager)."
        ),
        "category": "core",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "categories": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "core",
                            "research",
                            "listing",
                            "order",
                            "accounting",
                            "scout",
                            "marketing",
                            "analytics",
                        ],
                    },
                    "description": "List of tool categories to activate",
                },
                "reason": {
                    "type": "string",
                    "description": "Why these tools are needed",
                },
            },
            "required": ["categories", "reason"],
            "additionalProperties": False,
        },
    },
]

# Lookup: category → list of tool names
TOOL_CATEGORIES: dict[str, list[str]] = {}
for _tool in TOOLS:
    TOOL_CATEGORIES.setdefault(_tool.get("category", "core"), []).append(_tool["name"])
