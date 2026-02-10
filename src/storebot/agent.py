import json
import logging

import anthropic

from storebot.config import get_settings
from storebot.tools.blocket import BlocketClient
from storebot.tools.fortnox import FortnoxClient
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
        "name": "create_listing",
        "description": "Create a new listing on Tradera for a product.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Listing title in Swedish"},
                "description": {
                    "type": "string",
                    "description": "Listing description in Swedish",
                },
                "price": {"type": "number", "description": "Price in SEK"},
                "category_id": {"type": "integer", "description": "Tradera category ID"},
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of image file paths",
                },
            },
            "required": ["title", "description", "price"],
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
        "description": "Create a bookkeeping voucher in Fortnox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Voucher description"},
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "account": {"type": "integer"},
                            "debit": {"type": "number"},
                            "credit": {"type": "number"},
                        },
                    },
                    "description": "Voucher rows (debit/credit per account)",
                },
            },
            "required": ["description", "rows"],
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
]

SYSTEM_PROMPT = """Du är en AI-assistent för en svensk lanthandel som säljer renoverade möbler, \
inredning, kuriosa, antikviteter och grödor. Du hjälper ägaren att hantera butiken via Telegram.

Du kan:
- Söka efter liknande produkter på Tradera och Blocket för prisundersökning
- Göra priskoll som söker båda plattformarna och ger prisstatistik med föreslagen prisintervall
- Skapa annonser på Tradera
- Hantera ordrar och leveranser
- Skapa verifikationer i Fortnox
- Söka i produktdatabasen

Svara alltid på svenska om inte användaren skriver på engelska. Var kortfattad och tydlig.
Alla annonser och produktbeskrivningar ska vara på svenska."""


class Agent:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.claude_api_key)
        self.tradera = TraderaClient(
            app_id=self.settings.tradera_app_id,
            app_key=self.settings.tradera_app_key,
            sandbox=self.settings.tradera_sandbox,
        )
        self.blocket = BlocketClient(bearer_token=self.settings.blocket_bearer_token)
        self.fortnox = FortnoxClient(
            client_id=self.settings.fortnox_client_id,
            client_secret=self.settings.fortnox_client_secret,
            access_token=self.settings.fortnox_access_token,
        )
        self.pricing = PricingService(
            tradera=self.tradera,
            blocket=self.blocket,
        )

    def handle_message(
        self, user_message: str, conversation_history: list[dict] | None = None
    ) -> str:
        if conversation_history is None:
            conversation_history = []

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
                case "create_listing":
                    return self.tradera.create_listing(**tool_input)
                case "get_orders":
                    return self.tradera.get_orders(**tool_input)
                case "create_voucher":
                    return self.fortnox.create_voucher(**tool_input)
                case "search_products":
                    return {"results": [], "message": "Product search not yet implemented"}
                case _:
                    return {"error": f"Unknown tool: {name}"}
        except NotImplementedError:
            return {"error": f"Tool '{name}' is not yet implemented"}
        except Exception as e:
            logger.exception("Tool execution failed: %s", name)
            return {"error": str(e)}
