"""Tool definitions for the Claude API agent loop.

Each entry defines a tool name, description, and input schema that Claude
uses to decide when and how to call the tool.

All tools use strict mode (``strict: true``) so Claude must produce
schema-valid calls.  Rules:
- Every ``input_schema`` has ``additionalProperties: false``
- ALL properties are listed in ``required``
- Optional parameters use ``anyOf`` with null (model sends null to omit)
"""

TOOLS = [
    # --- Tradera ---
    {
        "name": "search_tradera",
        "description": "Search Tradera for items matching a query. Use for price research and finding comparable listings.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "category": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Category filter (null to omit)",
                },
                "max_price": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "Maximum price in SEK (null to omit)",
                },
            },
            "required": ["query", "category", "max_price"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_tradera_item",
        "description": "Hämta fullständig information om ett enskilt Tradera-objekt via dess ID. Använd för att se detaljer, slutpris, köpare etc.",
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
        "description": "Get all Tradera categories. Use to find the right category ID for a listing.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_shipping_options",
        "description": "Hämta tillgängliga fraktalternativ från Tradera. Returnerar fraktprodukter med leverantör, viktgräns och pris. Använd produktens vikt för att filtrera.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "weight_grams": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Paketets vikt i gram — filtrerar till alternativ som klarar vikten (null to omit)",
                },
            },
            "required": ["weight_grams"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_shipping_types",
        "description": "Hämta alla tillgängliga frakttyper (leveransvillkor) från Tradera. Returnerar en lista med ID och namn.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    # --- Blocket ---
    {
        "name": "search_blocket",
        "description": "Search Blocket for items. Read-only, useful for price research and sourcing opportunities.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "category": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Category filter (null to omit)",
                },
                "region": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Region filter (null to omit)",
                },
            },
            "required": ["query", "category", "region"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_blocket_ad",
        "description": "Get full details of a single Blocket ad including description, all images, seller info, and item parameters. Useful for deeper research on a specific item found via search.",
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
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query describing the item to price",
                },
                "product_id": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Local product ID to link analysis to (null to omit)",
                },
                "category": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Category filter — Tradera int or Blocket string (null to omit)",
                },
            },
            "required": ["query", "product_id", "category"],
            "additionalProperties": False,
        },
    },
    # --- Listings ---
    {
        "name": "create_draft_listing",
        "description": "Create a draft listing for a product. The draft must be approved before publishing. Use after price_check to set appropriate pricing.",
        "strict": True,
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
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Platform: tradera or blocket (null defaults to tradera)",
                },
                "start_price": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "Auction start price in SEK (required for auctions, null otherwise)",
                },
                "buy_it_now_price": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "Fixed price / buy-it-now price in SEK (null to omit)",
                },
                "duration_days": {
                    "anyOf": [{"type": "integer", "enum": [3, 5, 7, 10, 14]}, {"type": "null"}],
                    "description": "Listing duration in days (null defaults to 7)",
                },
                "tradera_category_id": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Tradera category ID (null to omit)",
                },
                "details": {
                    "anyOf": [
                        {
                            "type": "object",
                            "description": "Shipping and extra details",
                            "properties": {
                                "shipping_options": {
                                    "anyOf": [
                                        {
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
                                        {"type": "null"},
                                    ],
                                },
                                "shipping_cost": {
                                    "anyOf": [{"type": "number"}, {"type": "null"}],
                                },
                                "shipping_condition": {
                                    "anyOf": [{"type": "string"}, {"type": "null"}],
                                },
                                "reserve_price": {
                                    "anyOf": [{"type": "number"}, {"type": "null"}],
                                },
                            },
                            "required": [
                                "shipping_options",
                                "shipping_cost",
                                "shipping_condition",
                                "reserve_price",
                            ],
                            "additionalProperties": False,
                        },
                        {"type": "null"},
                    ],
                    "description": "Shipping and extra details (null to omit). Set shipping_options OR shipping_cost, not both.",
                },
            },
            "required": [
                "product_id",
                "listing_type",
                "listing_title",
                "listing_description",
                "platform",
                "start_price",
                "buy_it_now_price",
                "duration_days",
                "tradera_category_id",
                "details",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_draft_listings",
        "description": "List listings filtered by status. Defaults to showing drafts awaiting approval.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Filter by status: draft, approved, active, ended, sold (null defaults to draft)",
                },
            },
            "required": ["status"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_draft_listing",
        "description": "Get full details of a single listing including preview.",
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
        "description": "Update fields on a draft listing. Only drafts can be edited.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID"},
                "listing_title": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New title (null to keep current)",
                },
                "listing_description": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New description (null to keep current)",
                },
                "listing_type": {
                    "anyOf": [
                        {"type": "string", "enum": ["auction", "buy_it_now"]},
                        {"type": "null"},
                    ],
                    "description": "New listing type (null to keep current)",
                },
                "start_price": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "New start price (null to keep current)",
                },
                "buy_it_now_price": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "New buy-it-now price (null to keep current)",
                },
                "duration_days": {
                    "anyOf": [{"type": "integer", "enum": [3, 5, 7, 10, 14]}, {"type": "null"}],
                    "description": "New duration (null to keep current)",
                },
                "tradera_category_id": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "New category ID (null to keep current)",
                },
                "details": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "shipping_options": {
                                    "anyOf": [
                                        {
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
                                        {"type": "null"},
                                    ],
                                },
                                "shipping_cost": {
                                    "anyOf": [{"type": "number"}, {"type": "null"}],
                                },
                                "shipping_condition": {
                                    "anyOf": [{"type": "string"}, {"type": "null"}],
                                },
                                "reserve_price": {
                                    "anyOf": [{"type": "number"}, {"type": "null"}],
                                },
                            },
                            "required": [
                                "shipping_options",
                                "shipping_cost",
                                "shipping_condition",
                                "reserve_price",
                            ],
                            "additionalProperties": False,
                        },
                        {"type": "null"},
                    ],
                    "description": "New details (null to keep current)",
                },
            },
            "required": [
                "listing_id",
                "listing_title",
                "listing_description",
                "listing_type",
                "start_price",
                "buy_it_now_price",
                "duration_days",
                "tradera_category_id",
                "details",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "approve_draft_listing",
        "description": "Approve a draft listing, moving it to 'approved' status ready for publishing.",
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
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID to revise"},
                "reason": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Reason for revision (null to omit, for audit trail)",
                },
            },
            "required": ["listing_id", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reject_draft_listing",
        "description": "Reject and delete a draft listing.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "integer", "description": "Listing ID to reject"},
                "reason": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Reason for rejection (null to omit)",
                },
            },
            "required": ["listing_id", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "publish_listing",
        "description": "Publish an approved listing to Tradera. Uploads images and creates the listing. The listing must be in 'approved' status.",
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
        "description": "Skapa ett nytt annonsutkast genom att kopiera från en avslutad eller såld annons. Kräver godkännande innan publicering.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "integer",
                    "description": "ID på den avslutade/sålda annonsen att kopiera från",
                },
                "listing_title": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Ny titel (null to keep original)",
                },
                "listing_description": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Ny beskrivning (null to keep original)",
                },
                "listing_type": {
                    "anyOf": [
                        {"type": "string", "enum": ["auction", "buy_it_now"]},
                        {"type": "null"},
                    ],
                    "description": "Ny annonstyp (null to keep original)",
                },
                "start_price": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "Nytt startpris (null to keep original)",
                },
                "buy_it_now_price": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "Nytt köp nu-pris (null to keep original)",
                },
                "duration_days": {
                    "anyOf": [{"type": "integer", "enum": [3, 5, 7, 10, 14]}, {"type": "null"}],
                    "description": "Ny varaktighet i dagar (null to keep original)",
                },
                "tradera_category_id": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Ny Tradera-kategori (null to keep original)",
                },
                "details": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "shipping_options": {
                                    "anyOf": [
                                        {
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
                                        {"type": "null"},
                                    ],
                                },
                                "shipping_cost": {
                                    "anyOf": [{"type": "number"}, {"type": "null"}],
                                },
                                "shipping_condition": {
                                    "anyOf": [{"type": "string"}, {"type": "null"}],
                                },
                                "reserve_price": {
                                    "anyOf": [{"type": "number"}, {"type": "null"}],
                                },
                            },
                            "required": [
                                "shipping_options",
                                "shipping_cost",
                                "shipping_condition",
                                "reserve_price",
                            ],
                            "additionalProperties": False,
                        },
                        {"type": "null"},
                    ],
                    "description": "Nya detaljer/frakt (null to keep original)",
                },
            },
            "required": [
                "listing_id",
                "listing_title",
                "listing_description",
                "listing_type",
                "start_price",
                "buy_it_now_price",
                "duration_days",
                "tradera_category_id",
                "details",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "cancel_listing",
        "description": "Avbryt en aktiv annons lokalt. OBS: Tradera har inget API för att avbryta annonser — det måste göras manuellt på plattformen.",
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
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Search query (null to list all)",
                },
                "status": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Filter by status: draft, listed, sold, archived (null to show all non-archived)",
                },
                "include_archived": {
                    "anyOf": [{"type": "boolean"}, {"type": "null"}],
                    "description": "Include archived products in results (null defaults to false)",
                },
            },
            "required": ["query", "status", "include_archived"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_product",
        "description": "Create a new product in the database. Use when the user wants to register a new item.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Product title in Swedish"},
                "description": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Product description in Swedish (null to omit)",
                },
                "category": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Category (e.g. möbler, inredning, kuriosa, antikviteter)",
                },
                "condition": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Condition (e.g. renoverad, bra skick, slitage)",
                },
                "materials": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Materials (e.g. ek, mässing, glas)",
                },
                "era": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Era or period (e.g. 1940-tal, jugend, art deco)",
                },
                "dimensions": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Dimensions (e.g. 60x40x80 cm)",
                },
                "source": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Where it was acquired (e.g. loppis, dödsbo, tradera)",
                },
                "acquisition_cost": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "Purchase cost in SEK (null to omit)",
                },
                "weight_grams": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Weight in grams (required for shipping labels, null to omit)",
                },
            },
            "required": [
                "title",
                "description",
                "category",
                "condition",
                "materials",
                "era",
                "dimensions",
                "source",
                "acquisition_cost",
                "weight_grams",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_product",
        "description": "Uppdatera fält på en befintlig produkt. Skicka bara värden för de fält som ska ändras, null för övriga.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to update"},
                "title": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New title (null to keep current)",
                },
                "description": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New description (null to keep current)",
                },
                "category": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New category (null to keep current)",
                },
                "condition": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New condition (null to keep current)",
                },
                "materials": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New materials (null to keep current)",
                },
                "era": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New era (null to keep current)",
                },
                "dimensions": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New dimensions (null to keep current)",
                },
                "source": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New source (null to keep current)",
                },
                "acquisition_cost": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "New cost in SEK (null to keep current)",
                },
                "weight_grams": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "New weight in grams (null to keep current)",
                },
            },
            "required": [
                "product_id",
                "title",
                "description",
                "category",
                "condition",
                "materials",
                "era",
                "dimensions",
                "source",
                "acquisition_cost",
                "weight_grams",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_product",
        "description": "Hämta fullständig information om en produkt: alla fält, antal bilder och aktiva annonser. Använd för att se detaljer som saknas i search_products (beskrivning, material, mått, vikt, källa).",
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
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID to attach image to"},
                "image_path": {"type": "string", "description": "File path to the image"},
                "is_primary": {
                    "anyOf": [{"type": "boolean"}, {"type": "null"}],
                    "description": "Set as primary product image (null defaults to false)",
                },
            },
            "required": ["product_id", "image_path", "is_primary"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_product_images",
        "description": "Hämta och visa produktbilder. Använd för att granska bilder innan godkännande/publicering av annons.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Product ID (null if listing_id is given)",
                },
                "listing_id": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Listing ID — resolves to product automatically (null if product_id is given)",
                },
            },
            "required": ["product_id", "listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_product_image",
        "description": "Ta bort en produktbild. Om bilden var primär blir nästa bild primär automatiskt.",
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
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_orders",
        "description": "List local orders, optionally filtered by status (pending/shipped/delivered/returned).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "anyOf": [
                        {
                            "type": "string",
                            "enum": ["pending", "shipped", "delivered", "returned"],
                        },
                        {"type": "null"},
                    ],
                    "description": "Filter by order status (null to show all)",
                },
            },
            "required": ["status"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_order",
        "description": "Get full details of a specific order including product title.",
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
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID to mark as shipped"},
                "tracking_number": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Tracking number (null to omit)",
                },
            },
            "required": ["order_id", "tracking_number"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_shipping_label",
        "description": "Skapa en fraktetikett via PostNord för en order. Kräver att produkten har weight_grams satt.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
                "service_code": {
                    "anyOf": [
                        {"type": "string", "enum": ["19", "17", "18"]},
                        {"type": "null"},
                    ],
                    "description": "PostNord service: 19=MyPack Collect, 17=MyPack Home, 18=Postpaket (null defaults to 19)",
                },
            },
            "required": ["order_id", "service_code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_orders_pending_feedback",
        "description": "Lista Tradera-ordrar som är skickade men saknar omdöme till köparen.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "leave_feedback",
        "description": "Lämna omdöme till köparen på en Tradera-order. Lämna ALDRIG omdöme utan ägarens uttryckliga bekräftelse av texten.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
                "comment": {
                    "type": "string",
                    "description": "Omdömestext (max 80 tecken)",
                },
                "feedback_type": {
                    "anyOf": [
                        {"type": "string", "enum": ["Positive", "Negative"]},
                        {"type": "null"},
                    ],
                    "description": "Typ av omdöme (null defaults to Positive)",
                },
            },
            "required": ["order_id", "comment", "feedback_type"],
            "additionalProperties": False,
        },
    },
    # --- Accounting ---
    {
        "name": "create_voucher",
        "description": "Skapa en bokföringsverifikation och spara lokalt. Debet och kredit måste balansera.",
        "strict": True,
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
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Link to order ID (null to omit)",
                },
                "transaction_date": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Transaction date ISO format (null defaults to today)",
                },
            },
            "required": ["description", "rows", "order_id", "transaction_date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_vouchers",
        "description": "Lista bokföringsverifikationer, valfritt filtrerade efter datumintervall.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "from_date": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Startdatum (ISO-format, t.ex. 2026-01-01, null to omit)",
                },
                "to_date": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Slutdatum (ISO-format, t.ex. 2026-12-31, null to omit)",
                },
            },
            "required": ["from_date", "to_date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "export_vouchers",
        "description": "Exportera verifikationer som PDF. Ange datumintervall.",
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
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'antik byrå')"},
                "platform": {
                    "anyOf": [
                        {"type": "string", "enum": ["tradera", "blocket", "both"]},
                        {"type": "null"},
                    ],
                    "description": "Which platform(s) to search (null defaults to both)",
                },
                "category": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Category filter (Tradera int ID or Blocket category name, null to omit)",
                },
                "max_price": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "Maximum price in SEK (null to omit)",
                },
                "region": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Region filter (Blocket only, null to omit)",
                },
            },
            "required": ["query", "platform", "category", "max_price", "region"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_saved_searches",
        "description": "List all saved searches. By default shows only active ones.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "include_inactive": {
                    "anyOf": [{"type": "boolean"}, {"type": "null"}],
                    "description": "Include deactivated searches (null defaults to false)",
                },
            },
            "required": ["include_inactive"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_saved_search",
        "description": "Update a saved search's query, platform, category, max_price, or region.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "integer", "description": "Saved search ID"},
                "query": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New search query (null to keep current)",
                },
                "platform": {
                    "anyOf": [
                        {"type": "string", "enum": ["tradera", "blocket", "both"]},
                        {"type": "null"},
                    ],
                    "description": "New platform filter (null to keep current)",
                },
                "category": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New category filter (null to keep current)",
                },
                "max_price": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "description": "New max price in SEK (null to keep current)",
                },
                "region": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "New region filter (null to keep current)",
                },
            },
            "required": ["search_id", "query", "platform", "category", "max_price", "region"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_saved_search",
        "description": "Deactivate a saved search (soft delete).",
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
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    # --- Marketing ---
    {
        "name": "refresh_listing_stats",
        "description": "Hämta aktuell statistik (visningar, bevakare, bud) från Tradera för aktiva annonser och spara en snapshot.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Specific listing ID to refresh (null to refresh all active)",
                },
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "analyze_listing",
        "description": "Analysera en annons prestanda: konverteringsgrad, trend, dagar aktiv, potentiell vinst.",
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
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_recommendations",
        "description": "Generera åtgärdsförslag för annonser: omlistning, prisjustering, förbättra innehåll, förläng, kategoritips.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "Specific listing ID (null to show all active+ended)",
                },
            },
            "required": ["listing_id"],
            "additionalProperties": False,
        },
    },
    # --- Analytics ---
    {
        "name": "business_summary",
        "description": "Affärssammanfattning för en period: intäkter, kostnader, bruttovinst, marginal, antal sålda, lagerstatus, snittid till försäljning.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Period: YYYY-MM (månad), YYYY-QN (kvartal), YYYY (år). Null för innevarande månad.",
                },
            },
            "required": ["period"],
            "additionalProperties": False,
        },
    },
    {
        "name": "profitability_report",
        "description": "Lönsamhetsrapport: nettovinst per produkt, aggregerat per kategori och inköpskälla. Topp/botten 5.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Period: YYYY-MM, YYYY-QN eller YYYY. Null för innevarande månad.",
                },
            },
            "required": ["period"],
            "additionalProperties": False,
        },
    },
    {
        "name": "inventory_report",
        "description": "Lagerrapport: lagervärde, statusfördelning, åldersanalys (0-7d, 8-14d, 15-30d, 30+d), lista på gamla artiklar.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "period_comparison",
        "description": "Periodjämförelse: två perioder sida vid sida med skillnader i intäkter, vinst, antal och marginal. Standard: denna månad vs förra.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "period_a": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Första perioden (YYYY-MM, YYYY-QN, YYYY). Null för innevarande månad.",
                },
                "period_b": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Andra perioden att jämföra med. Null för föregående månad.",
                },
            },
            "required": ["period_a", "period_b"],
            "additionalProperties": False,
        },
    },
    {
        "name": "sourcing_analysis",
        "description": "Inköpskanalanalys: ROI per källa (loppis, dödsbo, tradera etc.), antal inköpta/sålda, marginal, snittid till försäljning.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Period: YYYY-MM, YYYY-QN eller YYYY. Null för innevarande månad.",
                },
            },
            "required": ["period"],
            "additionalProperties": False,
        },
    },
]
