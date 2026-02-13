import json
import logging
from dataclasses import dataclass, field

import anthropic

from storebot.config import get_settings
from storebot.tools.accounting import AccountingService
from storebot.tools.blocket import BlocketClient
from storebot.tools.definitions import TOOLS
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

    # Maps tool name → (service_attr, method_name).
    # service_attr is None for tools that don't require a DB-backed service.
    _DISPATCH = {
        "search_tradera": ("tradera", "search"),
        "search_blocket": ("blocket", "search"),
        "get_blocket_ad": ("blocket", "get_ad"),
        "price_check": ("pricing", "price_check"),
        "get_categories": ("tradera", "get_categories"),
        "get_shipping_options": ("tradera", "get_shipping_options"),
        "create_draft_listing": ("listing", "create_draft"),
        "list_draft_listings": ("listing", "list_drafts"),
        "get_draft_listing": ("listing", "get_draft"),
        "update_draft_listing": ("listing", "update_draft"),
        "reject_draft_listing": ("listing", "reject_draft"),
        "approve_draft_listing": ("listing", "approve_draft"),
        "publish_listing": ("listing", "publish_listing"),
        "search_products": ("listing", "search_products"),
        "create_product": ("listing", "create_product"),
        "save_product_image": ("listing", "save_product_image"),
        "check_new_orders": ("order", "check_new_orders"),
        "list_orders": ("order", "list_orders"),
        "get_order": ("order", "get_order"),
        "create_sale_voucher": ("order", "create_sale_voucher"),
        "mark_order_shipped": ("order", "mark_shipped"),
        "create_shipping_label": ("order", "create_shipping_label"),
        "list_orders_pending_feedback": ("order", "list_orders_pending_feedback"),
        "leave_feedback": ("order", "leave_feedback"),
        "create_voucher": ("accounting", "create_voucher"),
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
    }

    # Services that require a database engine (service_attr → display name)
    _DB_SERVICES = {
        "listing": "ListingService",
        "order": "OrderService",
        "accounting": "AccountingService",
        "scout": "ScoutService",
        "marketing": "MarketingService",
    }

    def execute_tool(self, name: str, tool_input: dict) -> dict:
        logger.info("Executing tool: %s with input: %s", name, tool_input)

        entry = self._DISPATCH.get(name)
        if entry is None:
            return {"error": f"Unknown tool: {name}"}

        service_attr, method_name = entry
        service = getattr(self, service_attr, None)
        if service is None and service_attr in self._DB_SERVICES:
            return {"error": f"{self._DB_SERVICES[service_attr]} not available (no database engine)"}

        try:
            return getattr(service, method_name)(**tool_input)
        except NotImplementedError:
            return {"error": f"Tool '{name}' is not yet implemented"}
        except Exception as e:
            logger.exception("Tool execution failed: %s", name)
            return {"error": str(e)}
