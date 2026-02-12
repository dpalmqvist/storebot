import json
import logging
from dataclasses import dataclass, field

import anthropic

from storebot.config import get_settings
from storebot.tools.accounting import AccountingService
from storebot.tools.blocket import BlocketClient
from storebot.tools.image import encode_image_base64
from storebot.tools.listing import ListingService
from storebot.tools.marketing import MarketingService
from storebot.tools.order import OrderService
from storebot.tools.postnord import Address, PostNordClient
from storebot.tools.pricing import PricingService
from storebot.tools.scout import ScoutService
from storebot.tools.tradera import TraderaClient

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    text: str
    messages: list[dict] = field(default_factory=list)


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
                "weight_grams": {
                    "type": "integer",
                    "description": "Weight in grams (required for shipping labels)",
                },
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
- Publicera godkända annonser till Tradera (med bilduppladdning)
- Bläddra i Tradera-kategorier för att hitta rätt kategori
- Hantera ordrar: kolla efter nya ordrar, visa ordrar, skapa fraktetiketter via PostNord, skapa försäljningsverifikation, markera som skickad
- Skapa bokföringsverifikationer och exportera som PDF
- Söka i produktdatabasen
- Hantera sparade sökningar (scout): skapa, lista, uppdatera, ta bort
- Köra sparade sökningar manuellt eller alla på en gång för att hitta nya fynd
- Marknadsföring: uppdatera annonsstatistik, analysera prestanda, skapa rapporter, ge förbättringsförslag

VIKTIGT — Orderhantering:
1. Markera ALDRIG en order som skickad utan ägarens uttryckliga bekräftelse.
2. Skapa alltid en försäljningsverifikation (create_sale_voucher) för varje ny order.
3. Informera ägaren om nya ordrar med köpare, belopp och produkt.
4. Fraktetiketter kräver att produkten har vikt (weight_grams). Föreslå att ange vikt om det saknas.
5. PostNord-tjänster: 19=MyPack Collect (standard), 17=MyPack Home, 18=Postpaket.

När användaren skickar en bild:
1. Beskriv vad du ser i bilden.
2. Fråga om du ska skapa en ny produkt eller koppla bilden till en befintlig.
3. Använd create_product och/eller save_product_image.
4. Föreslå priskoll eller annons som nästa steg.

VIKTIGT — Annonseringsflöde:
1. Alla annonser skapas som utkast (status=draft) och kräver ägarens godkännande.
2. Visa alltid en förhandsgranskning efter att utkastet skapats.
3. Ändra utkast efter feedback — godkänn ALDRIG automatiskt.
4. Först efter godkännande (approve) kan annonsen publiceras med publish_listing.
5. Publicering laddar upp bilder och skapar annonsen på Tradera.
6. Informera ägaren om den publicerade annonsens URL.

VIKTIGT — Frakt vid annonsering:
1. Använd get_shipping_options med produktens vikt för att hitta tillgängliga fraktalternativ.
2. Inkludera shipping_options i details vid create_draft_listing: varje option ska ha cost, shipping_product_id och shipping_provider_id.
3. Alternativt: sätt details.shipping_cost för enkel fast fraktkostnad.
4. Visa fraktalternativen i förhandsgranskningen så ägaren kan godkänna.

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
            user_id=self.settings.tradera_user_id,
            user_token=self.settings.tradera_user_token,
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
        self.listing = (
            ListingService(engine=self.engine, tradera=self.tradera) if self.engine else None
        )
        self.postnord = None
        if self.settings.postnord_api_key:
            self.postnord = PostNordClient(
                api_key=self.settings.postnord_api_key,
                sender=Address(
                    name=self.settings.postnord_sender_name,
                    street=self.settings.postnord_sender_street,
                    postal_code=self.settings.postnord_sender_postal_code,
                    city=self.settings.postnord_sender_city,
                    country_code=self.settings.postnord_sender_country_code,
                    phone=self.settings.postnord_sender_phone,
                    email=self.settings.postnord_sender_email,
                ),
                sandbox=self.settings.postnord_sandbox,
            )
        self.order = (
            OrderService(
                engine=self.engine,
                tradera=self.tradera,
                accounting=self.accounting,
                postnord=self.postnord,
                label_export_path=self.settings.label_export_path,
            )
            if self.engine
            else None
        )
        self.scout = (
            ScoutService(
                engine=self.engine,
                tradera=self.tradera,
                blocket=self.blocket,
            )
            if self.engine
            else None
        )
        self.marketing = (
            MarketingService(
                engine=self.engine,
                tradera=self.tradera,
            )
            if self.engine
            else None
        )

    def _call_api(self, messages: list[dict]):
        """Send messages to Claude and return the response."""
        return self.client.messages.create(
            model=self.settings.claude_model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        )

    def handle_message(
        self,
        user_message: str,
        image_paths: list[str] | None = None,
        conversation_history: list[dict] | None = None,
    ) -> AgentResponse:
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

        response = self._call_api(messages)

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

            response = self._call_api(messages)

        messages.append({"role": "assistant", "content": response.content})

        text_blocks = [b for b in response.content if b.type == "text"]
        text = text_blocks[0].text if text_blocks else ""
        return AgentResponse(text=text, messages=messages)

    # Maps tool names to the service attribute they require (None = no DB needed)
    _TOOL_SERVICE = {
        "search_tradera": None,
        "search_blocket": None,
        "get_blocket_ad": None,
        "price_check": None,
        "get_categories": None,
        "get_shipping_options": None,
        "create_draft_listing": "listing",
        "list_draft_listings": "listing",
        "get_draft_listing": "listing",
        "update_draft_listing": "listing",
        "reject_draft_listing": "listing",
        "approve_draft_listing": "listing",
        "publish_listing": "listing",
        "search_products": "listing",
        "create_product": "listing",
        "save_product_image": "listing",
        "check_new_orders": "order",
        "list_orders": "order",
        "get_order": "order",
        "create_sale_voucher": "order",
        "mark_order_shipped": "order",
        "create_shipping_label": "order",
        "create_voucher": "accounting",
        "export_vouchers": "accounting",
        "create_saved_search": "scout",
        "list_saved_searches": "scout",
        "update_saved_search": "scout",
        "delete_saved_search": "scout",
        "run_saved_search": "scout",
        "run_all_saved_searches": "scout",
        "refresh_listing_stats": "marketing",
        "analyze_listing": "marketing",
        "get_performance_report": "marketing",
        "get_recommendations": "marketing",
    }

    _SERVICE_NAMES = {
        "listing": "ListingService",
        "order": "OrderService",
        "accounting": "AccountingService",
        "scout": "ScoutService",
        "marketing": "MarketingService",
    }

    def execute_tool(self, name: str, tool_input: dict) -> dict:
        logger.info("Executing tool: %s with input: %s", name, tool_input)

        required_service = self._TOOL_SERVICE.get(name)
        if required_service is not None and not getattr(self, required_service):
            service_name = self._SERVICE_NAMES[required_service]
            return {"error": f"{service_name} not available (no database engine)"}

        try:
            match name:
                case "search_tradera":
                    return self.tradera.search(**tool_input)
                case "search_blocket":
                    return self.blocket.search(**tool_input)
                case "get_blocket_ad":
                    return self.blocket.get_ad(**tool_input)
                case "price_check":
                    return self.pricing.price_check(**tool_input)
                case "get_categories":
                    return self.tradera.get_categories(**tool_input)
                case "get_shipping_options":
                    weight = tool_input.get("weight_grams")
                    result = self.tradera.get_shipping_options()
                    if "error" not in result and weight is not None:
                        result["shipping_options"] = [
                            opt
                            for opt in result["shipping_options"]
                            if opt.get("weight_limit_grams") is None
                            or opt["weight_limit_grams"] >= weight
                        ]
                        result["filtered_by_weight_grams"] = weight
                    return result
                case "create_draft_listing":
                    return self.listing.create_draft(**tool_input)
                case "list_draft_listings":
                    return self.listing.list_drafts(**tool_input)
                case "get_draft_listing":
                    return self.listing.get_draft(**tool_input)
                case "update_draft_listing":
                    listing_id = tool_input.pop("listing_id")
                    return self.listing.update_draft(listing_id, **tool_input)
                case "reject_draft_listing":
                    return self.listing.reject_draft(**tool_input)
                case "approve_draft_listing":
                    return self.listing.approve_draft(**tool_input)
                case "publish_listing":
                    return self.listing.publish_listing(**tool_input)
                case "search_products":
                    return self.listing.search_products(**tool_input)
                case "create_product":
                    return self.listing.create_product(**tool_input)
                case "save_product_image":
                    return self.listing.save_product_image(**tool_input)
                case "check_new_orders":
                    return self.order.check_new_orders()
                case "list_orders":
                    return self.order.list_orders(**tool_input)
                case "get_order":
                    return self.order.get_order(**tool_input)
                case "create_sale_voucher":
                    return self.order.create_sale_voucher(**tool_input)
                case "mark_order_shipped":
                    return self.order.mark_shipped(**tool_input)
                case "create_shipping_label":
                    return self.order.create_shipping_label(**tool_input)
                case "create_voucher":
                    return self.accounting.create_voucher(**tool_input)
                case "export_vouchers":
                    path = self.accounting.export_vouchers_pdf(**tool_input)
                    return {"pdf_path": path}
                case "create_saved_search":
                    return self.scout.create_search(**tool_input)
                case "list_saved_searches":
                    return self.scout.list_searches(**tool_input)
                case "update_saved_search":
                    search_id = tool_input.pop("search_id")
                    return self.scout.update_search(search_id, **tool_input)
                case "delete_saved_search":
                    return self.scout.delete_search(**tool_input)
                case "run_saved_search":
                    return self.scout.run_search(**tool_input)
                case "run_all_saved_searches":
                    return self.scout.run_all_searches()
                case "refresh_listing_stats":
                    return self.marketing.refresh_listing_stats(**tool_input)
                case "analyze_listing":
                    return self.marketing.analyze_listing(**tool_input)
                case "get_performance_report":
                    return self.marketing.get_performance_report()
                case "get_recommendations":
                    return self.marketing.get_recommendations(**tool_input)
                case _:
                    return {"error": f"Unknown tool: {name}"}
        except NotImplementedError:
            return {"error": f"Tool '{name}' is not yet implemented"}
        except Exception as e:
            logger.exception("Tool execution failed: %s", name)
            return {"error": str(e)}
