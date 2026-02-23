"""Shared tool dispatch logic.

Used by both ``agent.py`` (Claude API loop) and ``mcp_server.py`` (MCP server).
"""

import logging

from storebot.tools.schemas import validate_tool_result

logger = logging.getLogger(__name__)


def strip_nulls(value):
    """Recursively remove None values from dicts/lists.

    Empty dicts/lists that result from stripping are collapsed to None so
    that downstream ``is not None`` guards work correctly (e.g. details in
    relist_product).
    """
    if isinstance(value, dict):
        cleaned = {k: strip_nulls(v) for k, v in value.items() if v is not None}
        return cleaned or None
    if isinstance(value, list):
        return [strip_nulls(v) for v in value]
    return value


DISPATCH: dict[str, tuple[str, str]] = {
    "search_tradera": ("tradera", "search"),
    "get_tradera_item": ("tradera", "get_item"),
    "get_shipping_options": ("tradera", "get_shipping_options"),
    "get_shipping_types": ("tradera", "get_shipping_types"),
    "get_attribute_definitions": ("tradera", "get_attribute_definitions"),
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
    "listing_dashboard": ("marketing", "get_listing_dashboard"),
    "business_summary": ("analytics", "business_summary"),
    "profitability_report": ("analytics", "profitability_report"),
    "inventory_report": ("analytics", "inventory_report"),
    "period_comparison": ("analytics", "period_comparison"),
    "sourcing_analysis": ("analytics", "sourcing_analysis"),
    "usage_report": ("analytics", "usage_report"),
}

# Services that require a database engine (service_attr -> display name).
DB_SERVICES: dict[str, str] = {
    "listing": "ListingService",
    "order": "OrderService",
    "accounting": "AccountingService",
    "scout": "ScoutService",
    "marketing": "MarketingService",
    "analytics": "AnalyticsService",
}


def create_services(settings, engine) -> dict[str, object]:
    """Instantiate all tool services from settings and engine.

    Returns a dict keyed by service attribute name (matching DISPATCH values).
    DB-backed services are None when engine is None.
    """
    from storebot.tools.accounting import AccountingService
    from storebot.tools.analytics import AnalyticsService
    from storebot.tools.blocket import BlocketClient
    from storebot.tools.listing import ListingService
    from storebot.tools.marketing import MarketingService
    from storebot.tools.order import OrderService
    from storebot.tools.postnord import Address, PostNordClient
    from storebot.tools.pricing import PricingService
    from storebot.tools.scout import ScoutService
    from storebot.tools.tradera import TraderaClient

    tradera = TraderaClient(
        app_id=settings.tradera_app_id,
        app_key=settings.tradera_app_key,
        sandbox=settings.tradera_sandbox,
        user_id=settings.tradera_user_id,
        user_token=settings.tradera_user_token,
    )
    blocket = BlocketClient()
    accounting = (
        AccountingService(engine=engine, export_path=settings.voucher_export_path)
        if engine
        else None
    )
    postnord = None
    if settings.postnord_api_key:
        postnord = PostNordClient(
            api_key=settings.postnord_api_key,
            sender=Address(
                name=settings.postnord_sender_name,
                street=settings.postnord_sender_street,
                postal_code=settings.postnord_sender_postal_code,
                city=settings.postnord_sender_city,
                country_code=settings.postnord_sender_country_code,
                phone=settings.postnord_sender_phone,
                email=settings.postnord_sender_email,
            ),
            sandbox=settings.postnord_sandbox,
        )

    return {
        "tradera": tradera,
        "blocket": blocket,
        "pricing": PricingService(tradera=tradera, blocket=blocket, engine=engine),
        "listing": (
            ListingService(engine=engine, tradera=tradera, image_dir=settings.product_image_dir)
            if engine
            else None
        ),
        "order": (
            OrderService(
                engine=engine,
                tradera=tradera,
                accounting=accounting,
                postnord=postnord,
                label_export_path=settings.label_export_path,
            )
            if engine
            else None
        ),
        "accounting": accounting,
        "scout": (
            ScoutService(engine=engine, tradera=tradera, blocket=blocket) if engine else None
        ),
        "marketing": (
            MarketingService(engine=engine, tradera=tradera) if engine else None
        ),
        "analytics": AnalyticsService(engine=engine) if engine else None,
        "postnord": postnord,
    }


def execute_tool(services: dict[str, object], name: str, tool_input: dict) -> dict:
    """Execute a tool by name using the provided services dict.

    Thread-safe: each service method creates its own ``Session(engine)``
    context for DB access.
    """
    if not isinstance(tool_input, dict):
        return {"error": f"Invalid tool input type for '{name}': expected dict"}

    if name == "request_tools":
        return {"error": "request_tools is handled inline in handle_message"}

    cleaned = strip_nulls(tool_input) or {}

    logger.debug("Executing tool: %s with keys: %s", name, list(cleaned.keys()))

    entry = DISPATCH.get(name)
    if entry is None:
        return {"error": f"Unknown tool: {name}"}

    service_attr, method_name = entry
    service = services.get(service_attr)
    if service is None:
        if service_attr in DB_SERVICES:
            return {"error": f"{DB_SERVICES[service_attr]} not available (no database engine)"}
        return {"error": f"Service '{service_attr}' not available"}

    try:
        result = getattr(service, method_name)(**cleaned)
        return validate_tool_result(name, result)
    except TypeError as e:
        logger.warning("Tool input validation failed: %s — %s", name, e)
        return {"error": f"Invalid arguments for '{name}': {e}"}
    except NotImplementedError:
        return {"error": f"Tool '{name}' is not yet implemented"}
    except Exception as e:
        logger.exception("Tool execution failed: %s", name)
        return {"error": str(e)}
