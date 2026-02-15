import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

import anthropic

from storebot.config import get_settings
from storebot.tools.accounting import AccountingService
from storebot.tools.analytics import AnalyticsService
from storebot.tools.blocket import BlocketClient
from storebot.tools.definitions import TOOLS, TOOL_CATEGORIES
from storebot.tools.schemas import validate_tool_result
from storebot.tools.image import encode_image_base64
from storebot.tools.listing import ListingService
from storebot.tools.marketing import MarketingService
from storebot.tools.order import OrderService
from storebot.tools.postnord import Address, PostNordClient
from storebot.tools.pricing import PricingService
from storebot.tools.scout import ScoutService
from storebot.tools.tradera import TraderaClient

from sqlalchemy.orm import Session

from storebot.db import ApiUsage

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (USD) — Decimal for precision
_MODEL_PRICING = {
    "claude-sonnet-4-5-20250929": {
        "input": Decimal("3.0"),
        "output": Decimal("15.0"),
        "cache_write": Decimal("3.75"),
        "cache_read": Decimal("0.30"),
    },
    "claude-sonnet-4-20250514": {
        "input": Decimal("3.0"),
        "output": Decimal("15.0"),
        "cache_write": Decimal("3.75"),
        "cache_read": Decimal("0.30"),
    },
    "claude-haiku-3-5-20241022": {
        "input": Decimal("0.80"),
        "output": Decimal("4.0"),
        "cache_write": Decimal("1.0"),
        "cache_read": Decimal("0.08"),
    },
}
_USD_TO_SEK = Decimal("10.5")
_ONE_MILLION = Decimal("1000000")
_COST_QUANTIZE = Decimal("0.0001")


def _estimate_cost_sek(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation: int,
    cache_read: int,
) -> Decimal:
    """Estimate cost in SEK based on model pricing. Falls back to Sonnet pricing."""
    pricing = _MODEL_PRICING.get(model, _MODEL_PRICING["claude-sonnet-4-5-20250929"])
    cost_usd = (
        Decimal(input_tokens) * pricing["input"]
        + Decimal(output_tokens) * pricing["output"]
        + Decimal(cache_creation) * pricing["cache_write"]
        + Decimal(cache_read) * pricing["cache_read"]
    ) / _ONE_MILLION
    return (cost_usd * _USD_TO_SEK).quantize(_COST_QUANTIZE, rounding=ROUND_HALF_UP)


@dataclass
class AgentResponse:
    text: str
    messages: list[dict] = field(default_factory=list)
    display_images: list[dict] = field(default_factory=list)


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
- Hantera ordrar: kolla efter nya ordrar, visa ordrar, skapa fraktetiketter via PostNord, skapa försäljningsverifikation, markera som skickad, lämna omdöme till köparen
- Skapa bokföringsverifikationer och exportera som PDF
- Söka i produktdatabasen och hämta fullständig produktinfo (get_product)
- Hämta detaljer om enskilda Tradera-objekt (get_tradera_item)
- Lista bokföringsverifikationer med datumfilter (list_vouchers)
- Återlista produkter från avslutade/sålda annonser (relist_product)
- Ta bort produktbilder (delete_product_image)
- Avbryta aktiva annonser lokalt (cancel_listing — kräver manuell åtgärd på Tradera)
- Hämta Tradera frakttyper/leveransvillkor (get_shipping_types)
- Hantera sparade sökningar (scout): skapa, lista, uppdatera, ta bort
- Köra sparade sökningar manuellt eller alla på en gång för att hitta nya fynd
- Visa produktbilder direkt i chatten med get_product_images (använd för att granska bilder innan godkännande)
- Marknadsföring: uppdatera annonsstatistik, analysera prestanda, skapa rapporter, ge förbättringsförslag
- Analys: affärssammanfattning, lönsamhet per produkt/kategori/källa, lagerrapport, periodjämförelse, inköpskanalanalys
- API-användning: visa tokenförbrukning och kostnad per dag/månad (usage_report)

VIKTIGT — Orderhantering:
1. Markera ALDRIG en order som skickad utan ägarens uttryckliga bekräftelse.
2. Skapa alltid en försäljningsverifikation (create_sale_voucher) för varje ny order.
3. Informera ägaren om nya ordrar med köpare, belopp och produkt.
4. Fraktetiketter kräver att produkten har vikt (weight_grams). Föreslå att ange vikt om det saknas.
5. PostNord-tjänster: 19=MyPack Collect (standard), 17=MyPack Home, 18=Postpaket.
6. När en order är markerad som skickad, påminn ägaren om att lämna omdöme till köparen.
7. Föreslå alltid en positiv kommentar på svenska (max 80 tecken).
8. Skicka ALDRIG omdöme utan ägarens godkännande av den föreslagna texten.

När användaren skickar en bild:
1. Beskriv vad du ser i bilden.
2. Fråga om du ska skapa en ny produkt eller koppla bilden till en befintlig.
3. Använd create_product och/eller save_product_image.
4. Föreslå priskoll eller annons som nästa steg.

VIKTIGT — Annonseringsflöde:
1. Alla annonser skapas som utkast (status=draft) och kräver ägarens godkännande.
2. Visa alltid en förhandsgranskning efter att utkastet skapats.
3. Ändra utkast efter feedback — godkänn ALDRIG automatiskt.
4. Om ändringar behövs efter godkännande, använd revise_draft_listing för att flytta tillbaka till draft.
5. Först efter godkännande (approve) kan annonsen publiceras med publish_listing.
6. Publicering laddar upp bilder och skapar annonsen på Tradera.
7. Informera ägaren om den publicerade annonsens URL.

VIKTIGT — Frakt vid annonsering:
1. Använd get_shipping_options med produktens vikt för att hitta tillgängliga fraktalternativ.
2. Inkludera shipping_options i details vid create_draft_listing: varje option ska ha cost, shipping_product_id och shipping_provider_id.
3. Alternativt: sätt details.shipping_cost för enkel fast fraktkostnad.
4. Visa fraktalternativen i förhandsgranskningen så ägaren kan godkänna.

Om du behöver verktyg som inte är tillgängliga, använd request_tools för att begära fler.

Svara alltid på svenska om inte användaren skriver på engelska. Var kortfattad och tydlig.
Alla annonser och produktbeskrivningar ska vara på svenska."""


def _strip_nulls(value):
    """Recursively remove None values from dicts/lists (strict mode sends null for omitted params).

    Empty dicts/lists that result from stripping are collapsed to None so
    that downstream ``is not None`` guards work correctly (e.g. details in
    relist_product).
    """
    if isinstance(value, dict):
        cleaned = {k: _strip_nulls(v) for k, v in value.items() if v is not None}
        return cleaned or None
    if isinstance(value, list):
        return [_strip_nulls(v) for v in value]
    return value


_KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "research": ["sök", "söka", "tradera", "blocket", "jämför", "jämföra"],
    "listing": [
        "annons",
        "utkast",
        "draft",
        "publicera",
        "kategori",
        "frakt",
        "godkänn",
        "avvisa",
    ],
    "order": [
        "order",
        "ordrar",
        "beställning",
        "skicka",
        "leverans",
        "fraktetikett",
        "shipped",
        "omdöme",
        "feedback",
    ],
    "accounting": ["bokföring", "verifikation", "voucher", "moms", "export"],
    "scout": ["scout", "bevakning", "sparad sökning"],
    "marketing": ["marknadsföring", "marketing", "prestanda", "rekommendation"],
    "analytics": [
        "rapport",
        "analys",
        "lönsamhet",
        "omsättning",
        "lager",
        "intäkt",
        "kostnad",
        "periodjämförelse",
    ],
}

# Reverse lookup: tool name → category
_TOOL_NAME_TO_CATEGORY: dict[str, str] = {}
for _cat, _names in TOOL_CATEGORIES.items():
    for _name in _names:
        _TOOL_NAME_TO_CATEGORY[_name] = _cat


def _detect_categories(messages: list[dict], active_categories: set[str]) -> set[str]:
    """Detect relevant tool categories from recent messages.

    Always includes ``core``. Preserves ``active_categories`` for stickiness
    within a single ``handle_message`` call.
    """
    cats: set[str] = {"core"} | active_categories

    # Scan last 3 messages
    recent = messages[-3:] if len(messages) > 3 else messages
    for msg in recent:
        content = msg.get("content")
        if content is None:
            continue

        # Collect text fragments and tool names from the message
        texts: list[str] = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_name = block.get("name", "")
                        if tool_name in _TOOL_NAME_TO_CATEGORY:
                            cats.add(_TOOL_NAME_TO_CATEGORY[tool_name])
                elif hasattr(block, "type"):
                    # SDK content block objects
                    if block.type == "tool_use":
                        if hasattr(block, "name") and block.name in _TOOL_NAME_TO_CATEGORY:
                            cats.add(_TOOL_NAME_TO_CATEGORY[block.name])
                    elif block.type == "text" and hasattr(block, "text"):
                        texts.append(block.text)

        # Match keywords (case-insensitive)
        combined = " ".join(texts).lower()
        for category, keywords in _KEYWORD_CATEGORIES.items():
            for kw in keywords:
                if kw in combined:
                    cats.add(category)
                    break

    return cats


def _get_filtered_tools(categories: set[str]) -> list[dict]:
    """Return tool definitions for the given categories.

    Strips the internal ``category`` key and sets ``cache_control`` on the
    last tool for prompt caching.
    """
    tools = []
    for t in TOOLS:
        if t.get("category", "core") in categories:
            # Strip category from what we send to Claude
            cleaned = {k: v for k, v in t.items() if k != "category"}
            tools.append(cleaned)
    if tools:
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
    return tools


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
        self.blocket = (
            BlocketClient(bearer_token=self.settings.blocket_bearer_token)
            if self.settings.blocket_bearer_token
            else None
        )
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
            ListingService(
                engine=self.engine,
                tradera=self.tradera,
                image_dir=self.settings.product_image_dir,
            )
            if self.engine
            else None
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
        self.analytics = AnalyticsService(engine=self.engine) if self.engine else None

    def _call_api(self, messages: list[dict], tools: list[dict] | None = None):
        """Send messages to Claude and return the response."""
        logger.debug(
            "API call: sending %d messages",
            len(messages),
        )
        # Cache the system prompt (5-min TTL, ~90% cost reduction)
        system = [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if tools is None:
            tools = _get_filtered_tools({"core"})
        try:
            response = self.client.messages.create(
                model=self.settings.claude_model,
                max_tokens=4096,
                system=system,
                messages=messages,
                tools=tools,
            )
        except anthropic.APIError as e:
            status = getattr(e, "status_code", None)
            logger.error(
                "Claude API error: %s (status=%s) — %s",
                type(e).__name__,
                status,
                e,
            )
            raise
        cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        logger.info(
            "API call: input_tokens=%d, output_tokens=%d, "
            "cache_creation=%d, cache_read=%d, stop_reason=%s",
            response.usage.input_tokens,
            response.usage.output_tokens,
            cache_creation,
            cache_read,
            response.stop_reason,
        )
        return response

    def handle_message(
        self,
        user_message: str,
        image_paths: list[str] | None = None,
        conversation_history: list[dict] | None = None,
        chat_id: str | None = None,
    ) -> AgentResponse:
        if conversation_history is None:
            conversation_history = []

        logger.info(
            "handle_message: history_messages=%d, has_images=%s",
            len(conversation_history),
            bool(image_paths),
        )

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

        # Token accumulation across all API calls in this turn
        total_input = 0
        total_output = 0
        total_cache_creation = 0
        total_cache_read = 0
        tool_call_count = 0

        # Dynamic tool filtering: detect relevant categories from messages
        active_categories = _detect_categories(messages, set())
        filtered_tools = _get_filtered_tools(active_categories)
        logger.info(
            "Tool filtering: %d tools from categories %s",
            len(filtered_tools),
            sorted(active_categories),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Filtered tools: %s", [t["name"] for t in filtered_tools])

        response = self._call_api(messages, tools=filtered_tools)
        usage = getattr(response, "usage", None)
        total_input += getattr(usage, "input_tokens", 0) or 0
        total_output += getattr(usage, "output_tokens", 0) or 0
        total_cache_creation += getattr(usage, "cache_creation_input_tokens", 0) or 0
        total_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        all_display_images = []

        while response.stop_reason == "tool_use":
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            tool_call_count += len(tool_blocks)
            messages.append({"role": "assistant", "content": response.content})

            # request_tools is handled separately because it modifies the tool set
            # for the NEXT API call in this turn. Regular tools execute independently.
            request_blocks = [b for b in tool_blocks if b.name == "request_tools"]
            regular_blocks = [b for b in tool_blocks if b.name != "request_tools"]

            tool_results = []

            # Process request_tools first (expands tool set for next API call)
            for rb in request_blocks:
                cleaned = _strip_nulls(rb.input) or {}
                requested = cleaned.get("categories", [])
                new_cats = set(requested) - active_categories
                active_categories |= set(requested)
                filtered_tools = _get_filtered_tools(active_categories)
                new_tool_names = []
                for cat in new_cats:
                    new_tool_names.extend(TOOL_CATEGORIES.get(cat, []))
                result = {
                    "status": "ok",
                    "activated_categories": sorted(active_categories),
                    "new_tools": new_tool_names,
                }
                result = validate_tool_result("request_tools", result)
                logger.info(
                    "request_tools: activated %s, now %d tools",
                    sorted(new_cats) if new_cats else "none new",
                    len(filtered_tools),
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": rb.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            # Process regular tool blocks (parallel if 2+)
            if len(regular_blocks) >= 2:
                with ThreadPoolExecutor(max_workers=min(len(regular_blocks), 4)) as pool:
                    futures = {
                        pool.submit(self.execute_tool, b.name, b.input): i
                        for i, b in enumerate(regular_blocks)
                    }
                    results_by_index = {}
                    for future in futures:
                        idx = futures[future]
                        try:
                            results_by_index[idx] = future.result()
                        except Exception as exc:
                            logger.exception("Tool failed in parallel execution")
                            results_by_index[idx] = {"error": str(exc)}
                for i, tool_block in enumerate(regular_blocks):
                    result = results_by_index[i]
                    display_images = result.pop("_display_images", None)
                    if display_images:
                        all_display_images.extend(display_images)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
            else:
                for tool_block in regular_blocks:
                    result = self.execute_tool(tool_block.name, tool_block.input)
                    display_images = result.pop("_display_images", None)
                    if display_images:
                        all_display_images.extend(display_images)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )

            logger.info("Agent turn completed: %d tool calls", len(tool_blocks))
            messages.append({"role": "user", "content": tool_results})

            response = self._call_api(messages, tools=filtered_tools)
            usage = getattr(response, "usage", None)
            total_input += getattr(usage, "input_tokens", 0) or 0
            total_output += getattr(usage, "output_tokens", 0) or 0
            total_cache_creation += getattr(usage, "cache_creation_input_tokens", 0) or 0
            total_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0

        messages.append({"role": "assistant", "content": response.content})

        self._store_usage(
            chat_id=chat_id,
            model=getattr(response, "model", self.settings.claude_model),
            input_tokens=total_input,
            output_tokens=total_output,
            cache_creation=total_cache_creation,
            cache_read=total_cache_read,
            tool_calls=tool_call_count,
        )

        text_blocks = [b for b in response.content if b.type == "text"]
        text = text_blocks[0].text if text_blocks else ""
        return AgentResponse(text=text, messages=messages, display_images=all_display_images)

    def _store_usage(
        self,
        chat_id: str | None,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int,
        cache_read: int,
        tool_calls: int,
    ) -> None:
        """Persist one ApiUsage row per handle_message call. Never raises."""
        if not self.engine:
            return
        cost = _estimate_cost_sek(model, input_tokens, output_tokens, cache_creation, cache_read)
        try:
            with Session(self.engine) as session:
                session.add(
                    ApiUsage(
                        chat_id=chat_id,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_creation_input_tokens=cache_creation,
                        cache_read_input_tokens=cache_read,
                        tool_calls=tool_calls,
                        estimated_cost_sek=cost,
                    )
                )
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
        except Exception:
            logger.warning("Failed to store API usage", exc_info=True)

    # Maps tool name → (service_attr, method_name).
    # service_attr is None for tools that don't require a DB-backed service.
    _DISPATCH = {
        "search_tradera": ("tradera", "search"),
        "get_tradera_item": ("tradera", "get_item"),
        "get_categories": ("tradera", "get_categories"),
        "get_shipping_options": ("tradera", "get_shipping_options"),
        "get_shipping_types": ("tradera", "get_shipping_types"),
        "search_blocket": ("blocket", "search"),
        "get_blocket_ad": ("blocket", "get_ad"),
        "price_check": ("pricing", "price_check"),
        "create_draft_listing": ("listing", "create_draft"),
        "list_draft_listings": ("listing", "list_drafts"),
        "get_draft_listing": ("listing", "get_draft"),
        "update_draft_listing": ("listing", "update_draft"),
        "reject_draft_listing": ("listing", "reject_draft"),
        "approve_draft_listing": ("listing", "approve_draft"),
        "revise_draft_listing": ("listing", "revise_draft"),
        "publish_listing": ("listing", "publish_listing"),
        "relist_product": ("listing", "relist_product"),
        "cancel_listing": ("listing", "cancel_listing"),
        "search_products": ("listing", "search_products"),
        "create_product": ("listing", "create_product"),
        "update_product": ("listing", "update_product"),
        "get_product": ("listing", "get_product"),
        "save_product_image": ("listing", "save_product_image"),
        "get_product_images": ("listing", "get_product_images"),
        "delete_product_image": ("listing", "delete_product_image"),
        "archive_product": ("listing", "archive_product"),
        "unarchive_product": ("listing", "unarchive_product"),
        "check_new_orders": ("order", "check_new_orders"),
        "list_orders": ("order", "list_orders"),
        "get_order": ("order", "get_order"),
        "create_sale_voucher": ("order", "create_sale_voucher"),
        "mark_order_shipped": ("order", "mark_shipped"),
        "create_shipping_label": ("order", "create_shipping_label"),
        "list_orders_pending_feedback": ("order", "list_orders_pending_feedback"),
        "leave_feedback": ("order", "leave_feedback"),
        "create_voucher": ("accounting", "create_voucher"),
        "list_vouchers": ("accounting", "list_vouchers"),
        "export_vouchers": ("accounting", "export_vouchers_pdf"),
        "create_saved_search": ("scout", "create_search"),
        "list_saved_searches": ("scout", "list_searches"),
        "update_saved_search": ("scout", "update_search"),
        "delete_saved_search": ("scout", "delete_search"),
        "run_saved_search": ("scout", "run_search"),
        "run_all_saved_searches": ("scout", "run_all_searches"),
        "refresh_listing_stats": ("marketing", "refresh_listing_stats"),
        "analyze_listing": ("marketing", "analyze_listing"),
        "get_performance_report": ("marketing", "get_performance_report"),
        "get_recommendations": ("marketing", "get_recommendations"),
        "business_summary": ("analytics", "business_summary"),
        "profitability_report": ("analytics", "profitability_report"),
        "inventory_report": ("analytics", "inventory_report"),
        "period_comparison": ("analytics", "period_comparison"),
        "sourcing_analysis": ("analytics", "sourcing_analysis"),
        "usage_report": ("analytics", "usage_report"),
    }

    # Services that require a database engine (service_attr → display name)
    _DB_SERVICES = {
        "listing": "ListingService",
        "order": "OrderService",
        "accounting": "AccountingService",
        "scout": "ScoutService",
        "marketing": "MarketingService",
        "analytics": "AnalyticsService",
    }

    def execute_tool(self, name: str, tool_input: dict) -> dict:
        if not isinstance(tool_input, dict):
            return {"error": f"Invalid tool input type for '{name}': expected dict"}

        # request_tools is handled inline in handle_message, not via _DISPATCH
        if name == "request_tools":
            return {"error": "request_tools is handled inline in handle_message"}

        # Strict mode sends null for optional params — strip them so Python
        # methods use their default values instead.
        cleaned = _strip_nulls(tool_input) or {}

        logger.debug(
            "Executing tool: %s with keys: %s",
            name,
            list(cleaned.keys()),
            extra={"tool_name": name},
        )

        entry = self._DISPATCH.get(name)
        if entry is None:
            return {"error": f"Unknown tool: {name}"}

        service_attr, method_name = entry
        service = getattr(self, service_attr, None)
        if service is None:
            if service_attr in self._DB_SERVICES:
                return {
                    "error": f"{self._DB_SERVICES[service_attr]} not available (no database engine)"
                }
            return {"error": f"Service '{service_attr}' not available"}

        try:
            result = getattr(service, method_name)(**cleaned)
            return validate_tool_result(name, result)
        except TypeError as e:
            logger.warning(
                "Tool input validation failed: %s — %s", name, e, extra={"tool_name": name}
            )
            return {"error": f"Invalid arguments for '{name}': {e}"}
        except NotImplementedError:
            return {"error": f"Tool '{name}' is not yet implemented"}
        except Exception as e:
            logger.exception("Tool execution failed: %s", name, extra={"tool_name": name})
            return {"error": str(e)}
