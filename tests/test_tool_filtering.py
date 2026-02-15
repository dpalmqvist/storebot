"""Tests for dynamic tool filtering (#52)."""

import json
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

from storebot.agent import (
    Agent,
    _detect_categories,
    _get_filtered_tools,
)
from storebot.db import Base
from storebot.tools.definitions import TOOLS, TOOL_CATEGORIES
from storebot.tools.schemas import validate_tool_result


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _make_agent(engine):
    settings = MagicMock()
    settings.claude_api_key = "test"
    settings.claude_model = "claude-sonnet-4-5-20250929"
    settings.tradera_app_id = "1"
    settings.tradera_app_key = "k"
    settings.tradera_sandbox = True
    settings.tradera_user_id = None
    settings.tradera_user_token = None
    settings.blocket_bearer_token = None
    settings.postnord_api_key = None
    return Agent(settings=settings, engine=engine)


# --- _detect_categories tests ---


class TestDetectCategories:
    def test_core_always_included(self):
        result = _detect_categories([], set())
        assert "core" in result

    def test_keyword_annons_triggers_listing(self):
        messages = [{"role": "user", "content": "skapa en annons"}]
        result = _detect_categories(messages, set())
        assert "listing" in result
        assert "core" in result

    def test_keyword_order_triggers_order(self):
        messages = [{"role": "user", "content": "visa ordrar"}]
        result = _detect_categories(messages, set())
        assert "order" in result

    def test_keyword_rapport_triggers_analytics(self):
        messages = [{"role": "user", "content": "ge mig en rapport"}]
        result = _detect_categories(messages, set())
        assert "analytics" in result

    def test_multiple_keywords(self):
        messages = [{"role": "user", "content": "sök tradera och skapa annons"}]
        result = _detect_categories(messages, set())
        assert "research" in result
        assert "listing" in result

    def test_tool_name_in_history_triggers_category(self):
        """SDK-style tool_use blocks (with .type and .name attrs) trigger categories."""
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_tradera"
        messages = [{"role": "assistant", "content": [tool_block]}]
        result = _detect_categories(messages, set())
        assert "research" in result

    def test_tool_use_dict_triggers_category(self):
        """Dict-style tool_use blocks trigger categories."""
        messages = [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "create_saved_search", "id": "t1"}],
            }
        ]
        result = _detect_categories(messages, set())
        assert "scout" in result

    def test_active_categories_preserved(self):
        result = _detect_categories([], {"listing", "order"})
        assert "listing" in result
        assert "order" in result
        assert "core" in result

    def test_case_insensitive(self):
        messages = [{"role": "user", "content": "ANNONS"}]
        result = _detect_categories(messages, set())
        assert "listing" in result

    def test_content_block_text(self):
        """Structured content blocks with text type are scanned."""
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "visa min bevakning"}],
            }
        ]
        result = _detect_categories(messages, set())
        assert "scout" in result

    def test_scans_last_five_messages_only(self):
        """Only the last 5 messages are scanned."""
        messages = [
            {"role": "user", "content": "bokföring"},  # old, outside scan window
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "hej"},
            {"role": "assistant", "content": "hej"},
            {"role": "user", "content": "tjena"},
            {"role": "assistant", "content": "tjena"},
            {"role": "user", "content": "visa produkter"},
        ]
        result = _detect_categories(messages, set())
        # "bokföring" is in msg[0] which is outside the last 5
        assert "accounting" not in result


# --- _get_filtered_tools tests ---


class TestGetFilteredTools:
    def test_core_only(self):
        tools = _get_filtered_tools({"core"})
        names = {t["name"] for t in tools}
        assert "search_products" in names
        assert "create_product" in names
        assert "request_tools" in names
        # Non-core tools excluded
        assert "search_tradera" not in names
        assert "create_draft_listing" not in names

    def test_multiple_categories(self):
        tools = _get_filtered_tools({"core", "listing"})
        names = {t["name"] for t in tools}
        assert "search_products" in names
        assert "create_draft_listing" in names
        # Still no research tools
        assert "search_tradera" not in names

    def test_all_categories(self):
        all_cats = set(TOOL_CATEGORIES.keys())
        tools = _get_filtered_tools(all_cats)
        assert len(tools) == len(TOOLS)

    def test_cache_control_on_last(self):
        tools = _get_filtered_tools({"core"})
        assert tools[-1].get("cache_control") == {"type": "ephemeral"}
        # Not on earlier tools
        for t in tools[:-1]:
            assert "cache_control" not in t

    def test_category_field_stripped(self):
        tools = _get_filtered_tools({"core", "research", "listing"})
        for t in tools:
            assert "category" not in t


# --- request_tools integration tests ---


class TestRequestTools:
    def test_request_tools_activates_categories(self, engine):
        """Mock Claude calling request_tools → next _call_api gets expanded tool set."""
        agent = _make_agent(engine)

        # First response: Claude calls request_tools
        request_block = MagicMock()
        request_block.type = "tool_use"
        request_block.name = "request_tools"
        request_block.input = {
            "categories": ["listing", "research"],
            "reason": "need listing tools",
        }
        request_block.id = "rt1"

        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 0

        resp1 = MagicMock()
        resp1.stop_reason = "tool_use"
        resp1.content = [request_block]
        resp1.usage = usage
        resp1.model = "claude-sonnet-4-5-20250929"

        # Second response: end_turn
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Nu har jag fler verktyg."

        resp2 = MagicMock()
        resp2.stop_reason = "end_turn"
        resp2.content = [text_block]
        resp2.usage = usage
        resp2.model = "claude-sonnet-4-5-20250929"

        call_args_list = []

        def mock_call_api(messages, tools=None):
            call_args_list.append({"messages": messages, "tools": tools})
            if len(call_args_list) == 1:
                return resp1
            return resp2

        agent._call_api = mock_call_api

        agent.handle_message("skapa annons")

        # Second _call_api should have more tools than the first
        first_tools = call_args_list[0]["tools"]
        second_tools = call_args_list[1]["tools"]
        assert len(second_tools) > len(first_tools)

        # Second call should include listing tools
        second_names = {t["name"] for t in second_tools}
        assert "create_draft_listing" in second_names
        assert "search_tradera" in second_names

    def test_request_tools_returns_tool_names(self, engine):
        """request_tools result includes new tool names."""
        agent = _make_agent(engine)

        request_block = MagicMock()
        request_block.type = "tool_use"
        request_block.name = "request_tools"
        request_block.input = {"categories": ["scout"], "reason": "need scout tools"}
        request_block.id = "rt1"

        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 0

        resp1 = MagicMock()
        resp1.stop_reason = "tool_use"
        resp1.content = [request_block]
        resp1.usage = usage
        resp1.model = "claude-sonnet-4-5-20250929"

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Klart."

        resp2 = MagicMock()
        resp2.stop_reason = "end_turn"
        resp2.content = [text_block]
        resp2.usage = usage
        resp2.model = "claude-sonnet-4-5-20250929"

        agent._call_api = MagicMock(side_effect=[resp1, resp2])

        # Use a neutral message that doesn't trigger scout via keywords
        result = agent.handle_message("hej")

        # Find the tool_result message in conversation
        tool_result_msgs = [
            m
            for m in result.messages
            if m.get("role") == "user" and isinstance(m.get("content"), list)
        ]
        assert len(tool_result_msgs) == 1
        content = tool_result_msgs[0]["content"]
        rt_result = json.loads(content[0]["content"])
        assert rt_result["status"] == "ok"
        assert "scout" in rt_result["activated_categories"]
        assert "create_saved_search" in rt_result["new_tools"]

    def test_handle_message_uses_filtered_tools(self, engine):
        """Verify _call_api receives filtered tools based on message content."""
        agent = _make_agent(engine)

        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 0

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hej!"

        resp = MagicMock()
        resp.stop_reason = "end_turn"
        resp.content = [text_block]
        resp.usage = usage
        resp.model = "claude-sonnet-4-5-20250929"

        call_args_list = []

        def mock_call_api(messages, tools=None):
            call_args_list.append(tools)
            return resp

        agent._call_api = mock_call_api

        # "rapport" triggers analytics
        agent.handle_message("ge mig en rapport")

        tools_sent = call_args_list[0]
        names = {t["name"] for t in tools_sent}
        assert "business_summary" in names  # analytics tool
        assert "search_products" in names  # core always included
        # No category field in sent tools
        for t in tools_sent:
            assert "category" not in t

    def test_execute_tool_rejects_request_tools(self, engine):
        """request_tools should not be dispatched via execute_tool."""
        agent = _make_agent(engine)
        result = agent.execute_tool("request_tools", {"categories": ["listing"], "reason": "test"})
        assert "error" in result

    def test_request_tools_with_concurrent_regular_tool(self, engine):
        """Claude can call request_tools + regular tool in the same turn."""
        agent = _make_agent(engine)

        request_block = MagicMock()
        request_block.type = "tool_use"
        request_block.name = "request_tools"
        request_block.input = {"categories": ["research"], "reason": "need search"}
        request_block.id = "rt1"

        search_block = MagicMock()
        search_block.type = "tool_use"
        search_block.name = "search_products"
        search_block.input = {"query": "stol", "status": None, "include_archived": None}
        search_block.id = "sp1"

        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 0

        resp1 = MagicMock()
        resp1.stop_reason = "tool_use"
        resp1.content = [request_block, search_block]
        resp1.usage = usage
        resp1.model = "claude-sonnet-4-5-20250929"

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Klart."

        resp2 = MagicMock()
        resp2.stop_reason = "end_turn"
        resp2.content = [text_block]
        resp2.usage = usage
        resp2.model = "claude-sonnet-4-5-20250929"

        agent._call_api = MagicMock(side_effect=[resp1, resp2])
        agent.execute_tool = MagicMock(return_value={"count": 0, "products": []})

        result = agent.handle_message("hej")

        # execute_tool called for regular tool only, not request_tools
        agent.execute_tool.assert_called_once_with("search_products", search_block.input)

        # Both results appear in the tool_result message
        tool_result_msgs = [
            m
            for m in result.messages
            if m.get("role") == "user" and isinstance(m.get("content"), list)
        ]
        assert len(tool_result_msgs) == 1
        results = tool_result_msgs[0]["content"]
        result_ids = {r["tool_use_id"] for r in results}
        assert result_ids == {"rt1", "sp1"}

        # request_tools result has correct structure
        rt_content = next(r for r in results if r["tool_use_id"] == "rt1")
        rt_data = json.loads(rt_content["content"])
        assert rt_data["status"] == "ok"
        assert "research" in rt_data["activated_categories"]

    def test_request_tools_schema_validation(self):
        """RequestToolsResult validates correctly."""
        result = {
            "status": "ok",
            "activated_categories": ["core", "listing"],
            "new_tools": ["create_draft_listing"],
        }
        validated = validate_tool_result("request_tools", result)
        assert validated["status"] == "ok"
        assert "core" in validated["activated_categories"]

    def test_request_tools_filters_unknown_categories(self, engine):
        """Unknown categories in request_tools are silently ignored."""
        agent = _make_agent(engine)

        request_block = MagicMock()
        request_block.type = "tool_use"
        request_block.name = "request_tools"
        request_block.input = {
            "categories": ["listing", "nonexistent", 42],
            "reason": "test",
        }
        request_block.id = "rt1"

        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 0

        resp1 = MagicMock()
        resp1.stop_reason = "tool_use"
        resp1.content = [request_block]
        resp1.usage = usage
        resp1.model = "claude-sonnet-4-5-20250929"

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Ok."

        resp2 = MagicMock()
        resp2.stop_reason = "end_turn"
        resp2.content = [text_block]
        resp2.usage = usage
        resp2.model = "claude-sonnet-4-5-20250929"

        agent._call_api = MagicMock(side_effect=[resp1, resp2])

        result = agent.handle_message("hej")

        tool_result_msgs = [
            m
            for m in result.messages
            if m.get("role") == "user" and isinstance(m.get("content"), list)
        ]
        rt_data = json.loads(tool_result_msgs[0]["content"][0]["content"])
        assert rt_data["status"] == "ok"
        # "listing" accepted, "nonexistent" and 42 filtered out
        assert "listing" in rt_data["activated_categories"]
        assert "nonexistent" not in rt_data["activated_categories"]

    def test_tool_results_preserve_original_order(self, engine):
        """Tool results should match original tool_blocks order, not request-first."""
        agent = _make_agent(engine)

        search_block = MagicMock()
        search_block.type = "tool_use"
        search_block.name = "search_products"
        search_block.input = {"query": "stol"}
        search_block.id = "sp1"

        request_block = MagicMock()
        request_block.type = "tool_use"
        request_block.name = "request_tools"
        request_block.input = {"categories": ["research"], "reason": "test"}
        request_block.id = "rt1"

        # Order: search_products THEN request_tools
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 0

        resp1 = MagicMock()
        resp1.stop_reason = "tool_use"
        resp1.content = [search_block, request_block]
        resp1.usage = usage
        resp1.model = "claude-sonnet-4-5-20250929"

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Klart."

        resp2 = MagicMock()
        resp2.stop_reason = "end_turn"
        resp2.content = [text_block]
        resp2.usage = usage
        resp2.model = "claude-sonnet-4-5-20250929"

        agent._call_api = MagicMock(side_effect=[resp1, resp2])
        agent.execute_tool = MagicMock(return_value={"count": 0, "products": []})

        result = agent.handle_message("hej")

        tool_result_msgs = [
            m
            for m in result.messages
            if m.get("role") == "user" and isinstance(m.get("content"), list)
        ]
        results = tool_result_msgs[0]["content"]
        # Results should be in original order: sp1 first, rt1 second
        assert results[0]["tool_use_id"] == "sp1"
        assert results[1]["tool_use_id"] == "rt1"
