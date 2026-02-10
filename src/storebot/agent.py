import json
import logging

import anthropic

from storebot.config import get_settings
from storebot.tools.blocket import BlocketClient
from storebot.tools.accounting import AccountingService
from storebot.tools.image import encode_image_base64
from storebot.tools.listing import ListingService
from storebot.tools.pricing import PricingService
from storebot.tools.tradera import TraderaClient

logger = logging.getLogger(__name__)

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
                    "description": "Additional details (shipping, condition, etc.)",
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
        "name": "get_orders",
        "description": "Retrieve orders from Tradera.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (optional)",
                },
            },
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
        "description": "Search the local product database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "status": {
                    "type": "string",
                    "description": "Filter by status: draft, listed, sold, archived",
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
            },
            "required": ["title"],
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
]

SYSTEM_PROMPT = """Du är en AI-assistent för en svensk lanthandel som säljer renoverade möbler, \
inredning, kuriosa, antikviteter och grödor. Du hjälper ägaren att hantera butiken via Telegram.

Du kan:
- Analysera bilder som användaren skickar (möbler, inredning, kuriosa, etc.)
- Skapa nya produkter i databasen
- Spara bilder till produkter
- Söka efter liknande produkter på Tradera och Blocket för prisundersökning
- Göra priskoll som söker båda plattformarna och ger prisstatistik med föreslagen prisintervall
- Skapa utkast till annonser (alla annonser börjar som utkast)
- Visa, redigera, godkänna och avvisa annonsutkast
- Hantera ordrar och leveranser
- Skapa bokföringsverifikationer och exportera som PDF
- Söka i produktdatabasen

När användaren skickar en bild:
1. Beskriv vad du ser i bilden.
2. Fråga om du ska skapa en ny produkt eller koppla bilden till en befintlig.
3. Använd create_product och/eller save_product_image.
4. Föreslå priskoll eller annons som nästa steg.

VIKTIGT — Annonseringsflöde:
1. Alla annonser skapas som utkast (status=draft) och kräver ägarens godkännande.
2. Visa alltid en förhandsgranskning efter att utkastet skapats.
3. Ändra utkast efter feedback — godkänn ALDRIG automatiskt.
4. Först efter godkännande (approve) kan annonsen publiceras.

Svara alltid på svenska om inte användaren skriver på engelska. Var kortfattad och tydlig.
Alla annonser och produktbeskrivningar ska vara på svenska."""


class Agent:
    def __init__(self, settings=None, engine=None):
        self.settings = settings or get_settings()
        self.engine = engine
        self.client = anthropic.Anthropic(api_key=self.settings.claude_api_key)
        self.tradera = TraderaClient(
            app_id=self.settings.tradera_app_id,
            app_key=self.settings.tradera_app_key,
            sandbox=self.settings.tradera_sandbox,
        )
        self.blocket = BlocketClient(bearer_token=self.settings.blocket_bearer_token)
        self.accounting = (
            AccountingService(
                engine=self.engine,
                export_path=self.settings.voucher_export_path,
            )
            if self.engine
            else None
        )
        self.pricing = PricingService(
            tradera=self.tradera,
            blocket=self.blocket,
            engine=self.engine,
        )
        self.listing = ListingService(engine=self.engine) if self.engine else None

    def handle_message(
        self,
        user_message: str,
        image_paths: list[str] | None = None,
        conversation_history: list[dict] | None = None,
    ) -> str:
        if conversation_history is None:
            conversation_history = []

        if image_paths:
            content = []
            for path in image_paths:
                data, media_type = encode_image_base64(path)
                content.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": data},
                    }
                )
            text = user_message or (
                "Användaren skickade dessa bilder. "
                "Beskriv vad du ser och fråga hur du kan hjälpa till."
            )
            paths_info = ", ".join(image_paths)
            text += f"\n\n[Bildernas sökvägar: {paths_info}]"
            content.append({"type": "text", "text": text})
            messages = conversation_history + [{"role": "user", "content": content}]
        else:
            messages = conversation_history + [{"role": "user", "content": user_message}]

        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        )

        while response.stop_reason == "tool_use":
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tool_block in tool_blocks:
                result = self.execute_tool(tool_block.name, tool_block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            messages.append({"role": "user", "content": tool_results})

            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
            )

        text_blocks = [b for b in response.content if b.type == "text"]
        return text_blocks[0].text if text_blocks else ""

    def execute_tool(self, name: str, tool_input: dict) -> dict:
        logger.info("Executing tool: %s with input: %s", name, tool_input)

        try:
            match name:
                case "search_tradera":
                    return self.tradera.search(**tool_input)
                case "search_blocket":
                    return self.blocket.search(**tool_input)
                case "price_check":
                    return self.pricing.price_check(**tool_input)
                case "create_draft_listing":
                    if not self.listing:
                        return {"error": "ListingService not available (no database engine)"}
                    return self.listing.create_draft(**tool_input)
                case "list_draft_listings":
                    if not self.listing:
                        return {"error": "ListingService not available (no database engine)"}
                    return self.listing.list_drafts(**tool_input)
                case "get_draft_listing":
                    if not self.listing:
                        return {"error": "ListingService not available (no database engine)"}
                    return self.listing.get_draft(**tool_input)
                case "update_draft_listing":
                    if not self.listing:
                        return {"error": "ListingService not available (no database engine)"}
                    listing_id = tool_input.pop("listing_id")
                    return self.listing.update_draft(listing_id, **tool_input)
                case "reject_draft_listing":
                    if not self.listing:
                        return {"error": "ListingService not available (no database engine)"}
                    return self.listing.reject_draft(**tool_input)
                case "approve_draft_listing":
                    if not self.listing:
                        return {"error": "ListingService not available (no database engine)"}
                    return self.listing.approve_draft(**tool_input)
                case "get_orders":
                    return self.tradera.get_orders(**tool_input)
                case "create_voucher":
                    if not self.accounting:
                        return {"error": "AccountingService not available (no database engine)"}
                    return self.accounting.create_voucher(**tool_input)
                case "export_vouchers":
                    if not self.accounting:
                        return {"error": "AccountingService not available (no database engine)"}
                    path = self.accounting.export_vouchers_pdf(**tool_input)
                    return {"pdf_path": path}
                case "search_products":
                    if not self.listing:
                        return {"error": "ListingService not available (no database engine)"}
                    return self.listing.search_products(**tool_input)
                case "create_product":
                    if not self.listing:
                        return {"error": "ListingService not available (no database engine)"}
                    return self.listing.create_product(**tool_input)
                case "save_product_image":
                    if not self.listing:
                        return {"error": "ListingService not available (no database engine)"}
                    return self.listing.save_product_image(**tool_input)
                case _:
                    return {"error": f"Unknown tool: {name}"}
        except NotImplementedError:
            return {"error": f"Tool '{name}' is not yet implemented"}
        except Exception as e:
            logger.exception("Tool execution failed: %s", name)
            return {"error": str(e)}
