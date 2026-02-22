"""Tests for Pydantic tool-result schemas and validation."""

import logging

import pytest

from storebot.tools.schemas import (
    BusinessSummaryResult,
    DraftCreatedResult,
    ErrorResult,
    NewOrdersResult,
    PriceCheckResult,
    SearchResult,
    ToolResult,
    validate_tool_result,
)


class TestErrorResult:
    def test_valid(self):
        r = ErrorResult(error="something failed")
        assert r.error == "something failed"

    def test_missing_error_field(self):
        with pytest.raises(Exception):
            ErrorResult()


class TestSearchResult:
    def test_valid(self):
        r = SearchResult(results=[{"id": 1}], total_count=1)
        assert r.total_count == 1
        assert len(r.results) == 1

    def test_missing_total_count(self):
        with pytest.raises(Exception):
            SearchResult(results=[])


class TestPriceCheckResult:
    def test_valid_with_nested(self):
        r = PriceCheckResult(
            query="antik byrå",
            tradera={"items": [], "stats": {}},
            blocket={"items": [], "stats": {}},
            combined={"stats": {"count": 0}},
            suggested_range={"low": 100, "high": 500},
        )
        assert r.query == "antik byrå"
        assert r.suggested_range == {"low": 100, "high": 500}


class TestDraftCreatedResult:
    def test_valid(self):
        r = DraftCreatedResult(listing_id=42, status="draft")
        assert r.listing_id == 42

    def test_extra_field_preserved(self):
        r = DraftCreatedResult(listing_id=42, status="draft", preview="some text")
        dumped = r.model_dump()
        assert dumped["preview"] == "some text"


class TestNewOrdersResult:
    def test_valid(self):
        r = NewOrdersResult(new_orders=[{"order_id": 1}], count=1)
        assert r.count == 1


class TestBusinessSummaryResult:
    def test_valid(self):
        r = BusinessSummaryResult(
            period="2026-01",
            revenue=5000.0,
            acquisition_cost=2000.0,
            platform_fees=300.0,
            shipping_cost=200.0,
            gross_profit=2500.0,
            margin_percent=50.0,
            items_sold=10,
            stock_count=5,
        )
        assert r.margin_percent == 50.0


class TestToolResultExtraFields:
    def test_display_images_passes_through(self):
        r = ToolResult(_display_images=[{"path": "/img/1.jpg"}])
        dumped = r.model_dump()
        assert dumped["_display_images"] == [{"path": "/img/1.jpg"}]


class TestValidateToolResult:
    def test_unknown_tool_passthrough(self):
        data = {"foo": "bar"}
        result = validate_tool_result("unknown_tool", data)
        assert result == data

    def test_error_result_routes_to_error_schema(self):
        data = {"error": "not found"}
        result = validate_tool_result("search_tradera", data)
        assert result == data

    def test_valid_result_returns_validated(self):
        data = {"results": [{"id": 1}], "total_count": 1}
        result = validate_tool_result("search_tradera", data)
        assert result["total_count"] == 1

    def test_invalid_result_logs_warning_returns_unchanged(self, caplog):
        data = {"results": "not a list", "total_count": "bad"}
        with caplog.at_level(logging.WARNING):
            result = validate_tool_result("search_tradera", data)
        assert result is data
        assert "Validation failed" in caplog.text

    def test_display_images_preserved_through_validation(self):
        data = {
            "listing_id": 1,
            "status": "draft",
            "_display_images": [{"path": "/img/1.jpg"}],
        }
        result = validate_tool_result("create_draft_listing", data)
        assert result["_display_images"] == [{"path": "/img/1.jpg"}]

    def test_non_dict_passthrough(self):
        result = validate_tool_result("search_tradera", "not a dict")
        assert result == "not a dict"

    def test_malformed_error_result(self, caplog):
        data = {"error": 12345}  # error must be str — triggers validation failure
        with caplog.at_level(logging.WARNING):
            result = validate_tool_result("search_tradera", data)
        assert result is data
        assert "ErrorResult validation failed" in caplog.text
