"""Tests for self-critique / reflection prompts (#55)."""

from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

from storebot.agent import Agent, REFLECTION_TOOLS, _REFLECTION_PROMPT
from storebot.db import Base


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _make_settings(**overrides):
    settings = MagicMock()
    settings.claude_api_key = "test"
    settings.claude_model = "claude-sonnet-4-5-20250929"
    settings.claude_max_tokens = 16000
    settings.claude_thinking_budget = 0
    settings.tradera_app_id = "1"
    settings.tradera_app_key = "k"
    settings.tradera_sandbox = True
    settings.tradera_user_id = None
    settings.tradera_user_token = None
    settings.blocket_bearer_token = None
    settings.postnord_api_key = None
    settings.compact_threshold = 20
    settings.compact_keep_recent = 6
    settings.claude_model_compact = "claude-haiku-3-5-20241022"
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


class TestReflectionTools:
    def test_reflection_tools_constant_contents(self):
        """Verify REFLECTION_TOOLS set contains expected names."""
        assert REFLECTION_TOOLS == {
            "create_draft_listing",
            "price_check",
            "create_sale_voucher",
        }

    def test_reflection_prompt_appended_to_configured_tools(self, engine):
        """Verify reflection tools get the reflection suffix."""
        for tool_name in REFLECTION_TOOLS:
            settings = _make_settings()
            agent = Agent(settings=settings, engine=engine)

            tool_block = MagicMock()
            tool_block.type = "tool_use"
            tool_block.name = tool_name
            tool_block.input = {"product_id": 1} if tool_name != "price_check" else {"query": "x"}
            tool_block.id = f"tool_{tool_name}"

            response1 = MagicMock()
            response1.stop_reason = "tool_use"
            response1.content = [tool_block]
            response1.usage = MagicMock(
                input_tokens=100,
                output_tokens=50,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )

            text_block = MagicMock()
            text_block.type = "text"
            text_block.text = "Resultat"

            response2 = MagicMock()
            response2.stop_reason = "end_turn"
            response2.content = [text_block]
            response2.usage = MagicMock(
                input_tokens=200,
                output_tokens=100,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )
            response2.model = "claude-sonnet-4-5-20250929"

            agent._call_api = MagicMock(side_effect=[response1, response2])
            agent.execute_tool = MagicMock(return_value={"status": "ok", "data": "test"})

            agent.handle_message("test", chat_id="test")

            # Check the tool_result message sent back to the API.
            # messages is mutable — after handle_message, the final assistant
            # msg is appended, so the tool_result user msg is at [-2].
            second_call_messages = agent._call_api.call_args_list[1][0][0]
            tool_result_msg = second_call_messages[-2]
            assert tool_result_msg["role"] == "user"
            result_content = tool_result_msg["content"][0]["content"]
            assert _REFLECTION_PROMPT in result_content

    def test_reflection_prompt_not_appended_to_other_tools(self, engine):
        """Verify non-reflection tools do NOT get the suffix."""
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_tradera"
        tool_block.input = {"query": "stol"}
        tool_block.id = "tool_search"

        response1 = MagicMock()
        response1.stop_reason = "tool_use"
        response1.content = [tool_block]
        response1.usage = MagicMock(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Resultat"

        response2 = MagicMock()
        response2.stop_reason = "end_turn"
        response2.content = [text_block]
        response2.usage = MagicMock(
            input_tokens=200,
            output_tokens=100,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        response2.model = "claude-sonnet-4-5-20250929"

        agent._call_api = MagicMock(side_effect=[response1, response2])
        agent.execute_tool = MagicMock(return_value={"results": [], "total_count": 0})

        agent.handle_message("sök efter stol", chat_id="test")

        second_call_messages = agent._call_api.call_args_list[1][0][0]
        tool_result_msg = second_call_messages[-2]
        assert tool_result_msg["role"] == "user"
        result_content = tool_result_msg["content"][0]["content"]
        assert _REFLECTION_PROMPT not in result_content

    def test_reflection_prompt_not_appended_on_error(self, engine):
        """Error results are not modified with reflection."""
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "create_draft_listing"
        tool_block.input = {"product_id": 999}
        tool_block.id = "tool_draft"

        response1 = MagicMock()
        response1.stop_reason = "tool_use"
        response1.content = [tool_block]
        response1.usage = MagicMock(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Fel uppstod"

        response2 = MagicMock()
        response2.stop_reason = "end_turn"
        response2.content = [text_block]
        response2.usage = MagicMock(
            input_tokens=200,
            output_tokens=100,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        response2.model = "claude-sonnet-4-5-20250929"

        agent._call_api = MagicMock(side_effect=[response1, response2])
        agent.execute_tool = MagicMock(return_value={"error": "Product not found"})

        agent.handle_message("skapa annons", chat_id="test")

        second_call_messages = agent._call_api.call_args_list[1][0][0]
        tool_result_msg = second_call_messages[-2]
        assert tool_result_msg["role"] == "user"
        result_content = tool_result_msg["content"][0]["content"]
        assert _REFLECTION_PROMPT not in result_content
        assert "error" in result_content

    def test_reflection_works_without_thinking(self, engine):
        """No crash when thinking_budget=0 — reflection still appended."""
        settings = _make_settings(claude_thinking_budget=0)
        agent = Agent(settings=settings, engine=engine)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "price_check"
        tool_block.input = {"query": "stol"}
        tool_block.id = "tool_price"

        response1 = MagicMock()
        response1.stop_reason = "tool_use"
        response1.content = [tool_block]
        response1.usage = MagicMock(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Prisanalys klar"

        response2 = MagicMock()
        response2.stop_reason = "end_turn"
        response2.content = [text_block]
        response2.usage = MagicMock(
            input_tokens=200,
            output_tokens=100,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        response2.model = "claude-sonnet-4-5-20250929"

        agent._call_api = MagicMock(side_effect=[response1, response2])
        agent.execute_tool = MagicMock(
            return_value={"min": 100, "max": 500, "suggested_range": [200, 400]}
        )

        result = agent.handle_message("priskoll stol", chat_id="test")
        assert result.text == "Prisanalys klar"

        # Verify reflection was appended even without thinking
        second_call_messages = agent._call_api.call_args_list[1][0][0]
        tool_result_msg = second_call_messages[-2]
        assert tool_result_msg["role"] == "user"
        result_content = tool_result_msg["content"][0]["content"]
        assert _REFLECTION_PROMPT in result_content
