"""Tests for shared tool dispatch logic."""

from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

from storebot.db import Base
from storebot.tools.dispatch import (
    DISPATCH,
    create_services,
    execute_tool,
    strip_nulls,
)


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _make_settings(**overrides):
    settings = MagicMock()
    settings.tradera_app_id = "1"
    settings.tradera_app_key = "k"
    settings.tradera_sandbox = True
    settings.tradera_user_id = ""
    settings.tradera_user_token = ""
    settings.postnord_api_key = ""
    settings.postnord_sender_name = ""
    settings.postnord_sender_street = ""
    settings.postnord_sender_postal_code = ""
    settings.postnord_sender_city = ""
    settings.postnord_sender_country_code = "SE"
    settings.postnord_sender_phone = ""
    settings.postnord_sender_email = ""
    settings.postnord_sandbox = True
    settings.voucher_export_path = "/tmp/vouchers"
    settings.product_image_dir = "/tmp/images"
    settings.label_export_path = "/tmp/labels"
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


class TestStripNulls:
    def test_removes_none_values(self):
        assert strip_nulls({"a": 1, "b": None}) == {"a": 1}

    def test_empty_dict_becomes_none(self):
        assert strip_nulls({"a": None}) is None

    def test_nested_dict(self):
        assert strip_nulls({"a": {"b": None, "c": 1}}) == {"a": {"c": 1}}

    def test_list_preserved(self):
        assert strip_nulls([1, None, 3]) == [1, None, 3]

    def test_scalar_passthrough(self):
        assert strip_nulls(42) == 42

    def test_none_passthrough(self):
        assert strip_nulls(None) is None


class TestDispatchMapping:
    def test_has_all_expected_tools(self):
        assert "search_tradera" in DISPATCH
        assert "create_draft_listing" in DISPATCH
        assert "business_summary" in DISPATCH

    def test_entries_are_tuples(self):
        for name, entry in DISPATCH.items():
            assert isinstance(entry, tuple), f"{name} entry is not a tuple"
            assert len(entry) == 2, f"{name} entry length is not 2"

    def test_request_tools_not_in_dispatch(self):
        assert "request_tools" not in DISPATCH

    def test_get_categories_not_in_dispatch(self):
        assert "get_categories" not in DISPATCH


class TestCreateServices:
    def test_creates_all_services_with_engine(self, engine):
        settings = _make_settings()
        services = create_services(settings, engine)
        assert "tradera" in services
        assert "blocket" in services
        assert "pricing" in services
        assert "listing" in services
        assert "order" in services
        assert "accounting" in services
        assert "scout" in services
        assert "marketing" in services
        assert "analytics" in services

    def test_db_services_none_without_engine(self):
        settings = _make_settings()
        services = create_services(settings, engine=None)
        assert services["tradera"] is not None
        assert services["blocket"] is not None
        assert services["listing"] is None
        assert services["order"] is None

    def test_postnord_created_with_api_key(self, engine):
        settings = _make_settings(postnord_api_key="test-key")
        services = create_services(settings, engine)
        assert services["postnord"] is not None

    def test_postnord_none_without_api_key(self, engine):
        settings = _make_settings(postnord_api_key="")
        services = create_services(settings, engine)
        assert services["postnord"] is None


class TestExecuteTool:
    def test_dispatches_to_service_method(self):
        mock_service = MagicMock()
        mock_service.search.return_value = {"items": []}
        services = {"tradera": mock_service}
        result = execute_tool(services, "search_tradera", {"query": "test"})
        mock_service.search.assert_called_once_with(query="test")
        assert result == {"items": []}

    def test_unknown_tool_returns_error(self):
        result = execute_tool({}, "nonexistent_tool", {})
        assert "error" in result

    def test_missing_service_returns_error(self):
        services = {"listing": None}
        result = execute_tool(services, "create_draft_listing", {})
        assert "error" in result
        assert "not available" in result["error"]

    def test_strips_nulls_from_input(self):
        mock_service = MagicMock()
        mock_service.search.return_value = {"items": []}
        services = {"tradera": mock_service}
        execute_tool(services, "search_tradera", {"query": "test", "extra": None})
        mock_service.search.assert_called_once_with(query="test")

    def test_invalid_input_type_returns_error(self):
        result = execute_tool({}, "search_tradera", "not a dict")
        assert "error" in result

    def test_type_error_returns_error(self):
        mock_service = MagicMock()
        mock_service.search.side_effect = TypeError("bad args")
        services = {"tradera": mock_service}
        result = execute_tool(services, "search_tradera", {})
        assert "error" in result

    def test_exception_returns_error(self):
        mock_service = MagicMock()
        mock_service.search.side_effect = RuntimeError("boom")
        services = {"tradera": mock_service}
        result = execute_tool(services, "search_tradera", {})
        assert "error" in result

    def test_request_tools_returns_error(self):
        result = execute_tool({}, "request_tools", {})
        assert "error" in result
