"""Pydantic models for validating tool results before returning to Claude.

Validation is warn-only: if a result fails validation, it is logged and
returned unchanged so the conversation loop is never broken.
"""

import logging

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class ToolResult(BaseModel):
    """Base model for successful tool results.

    ``extra="allow"`` tolerates additional fields (e.g. ``_display_images``,
    context fields) while still catching missing required fields and wrong types.
    """

    model_config = ConfigDict(extra="allow")


class ErrorResult(BaseModel):
    """Tool returned an error."""

    error: str
    model_config = ConfigDict(extra="allow")


# --- Search ---


class SearchResult(ToolResult):
    results: list[dict]
    total_count: int


# --- Pricing ---


class PriceCheckResult(ToolResult):
    query: str
    tradera: dict
    blocket: dict
    combined: dict
    suggested_range: dict


# --- Listings ---


class DraftCreatedResult(ToolResult):
    listing_id: int
    status: str


class DraftListResult(ToolResult):
    count: int
    listings: list[dict]


class DraftDetailResult(ToolResult):
    id: int
    product_id: int
    platform: str
    status: str


# --- Products ---


class ProductCreatedResult(ToolResult):
    product_id: int
    title: str
    status: str


class ProductDetailResult(ToolResult):
    product_id: int
    title: str
    status: str


class ProductSearchResult(ToolResult):
    count: int
    products: list[dict]


# --- Orders ---


class NewOrdersResult(ToolResult):
    new_orders: list[dict]
    count: int


class OrderListResult(ToolResult):
    count: int
    orders: list[dict]


class OrderDetailResult(ToolResult):
    order_id: int
    status: str


# --- Analytics ---


class BusinessSummaryResult(ToolResult):
    period: str
    revenue: float
    acquisition_cost: float
    platform_fees: float
    shipping_cost: float
    gross_profit: float
    margin_percent: float
    items_sold: int
    stock_count: int


# --- Usage ---


class UsageReportResult(ToolResult):
    period: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_sek: float
    total_turns: int


# --- Tool filtering ---


class RequestToolsResult(ToolResult):
    status: str
    activated_categories: list[str]
    new_tools: list[str]


# Registry: tool name → schema class
TOOL_SCHEMAS: dict[str, type[ToolResult]] = {
    "search_tradera": SearchResult,
    "search_blocket": SearchResult,
    "price_check": PriceCheckResult,
    "create_draft_listing": DraftCreatedResult,
    "list_draft_listings": DraftListResult,
    "get_draft_listing": DraftDetailResult,
    "create_product": ProductCreatedResult,
    "get_product": ProductDetailResult,
    "search_products": ProductSearchResult,
    "check_new_orders": NewOrdersResult,
    "list_orders": OrderListResult,
    "get_order": OrderDetailResult,
    "business_summary": BusinessSummaryResult,
    "usage_report": UsageReportResult,
    "request_tools": RequestToolsResult,
}


def validate_tool_result(tool_name: str, result: dict) -> dict:
    """Validate a tool result against its registered schema.

    - If the result contains an ``error`` key, validates against ``ErrorResult``.
    - If no schema is registered for the tool, returns the result unchanged.
    - On validation failure, logs a warning and returns the result unchanged.
    - Never raises — the conversation loop must not break.
    """
    if not isinstance(result, dict):
        return result

    if "error" in result:
        try:
            ErrorResult.model_validate(result)
        except Exception:
            logger.warning("ErrorResult validation failed for tool '%s'", tool_name)
        return result

    schema = TOOL_SCHEMAS.get(tool_name)
    if schema is None:
        return result

    try:
        validated = schema.model_validate(result)
        return validated.model_dump()
    except Exception as e:
        logger.warning(
            "Validation failed for tool '%s': %s",
            tool_name,
            e,
        )
        return result
