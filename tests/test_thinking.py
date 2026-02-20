"""Tests for extended thinking support (#51)."""

from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa

from storebot.agent import Agent
from storebot.db import Base
from storebot.tools.conversation import _serialize_content


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _make_settings(**overrides):
    settings = MagicMock()
    settings.claude_api_key = "test"
    settings.claude_model = "claude-sonnet-4-6"
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


class TestThinkingConfig:
    def test_thinking_disabled_by_default(self, engine):
        """budget=0 → no 'thinking' kwarg in API call."""
        settings = _make_settings(claude_thinking_budget=0)
        agent = Agent(settings=settings, engine=engine)

        with patch.object(agent.client.messages, "create") as mock_create:
            mock_response = MagicMock()
            mock_response.stop_reason = "end_turn"
            mock_response.content = [MagicMock(type="text", text="Hej")]
            mock_response.usage = MagicMock(
                input_tokens=100,
                output_tokens=50,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )
            mock_response.model = "claude-sonnet-4-6"
            mock_create.return_value = mock_response

            agent.handle_message("hej", chat_id="test")

            call_kwargs = mock_create.call_args[1]
            assert "thinking" not in call_kwargs

    def test_thinking_enabled_with_budget(self, engine):
        """budget=5000 → thinking param in API call."""
        settings = _make_settings(claude_thinking_budget=5000)
        agent = Agent(settings=settings, engine=engine)

        with patch.object(agent.client.messages, "create") as mock_create:
            mock_response = MagicMock()
            mock_response.stop_reason = "end_turn"
            mock_response.content = [MagicMock(type="text", text="Hej")]
            mock_response.usage = MagicMock(
                input_tokens=100,
                output_tokens=50,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )
            mock_response.model = "claude-sonnet-4-6"
            mock_create.return_value = mock_response

            agent.handle_message("hej", chat_id="test")

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["thinking"] == {
                "type": "enabled",
                "budget_tokens": 5000,
            }

    def test_thinking_budget_below_minimum_disabled(self, engine):
        """budget=500 (< 1024) → no 'thinking' kwarg."""
        settings = _make_settings(claude_thinking_budget=500)
        agent = Agent(settings=settings, engine=engine)

        with patch.object(agent.client.messages, "create") as mock_create:
            mock_response = MagicMock()
            mock_response.stop_reason = "end_turn"
            mock_response.content = [MagicMock(type="text", text="Hej")]
            mock_response.usage = MagicMock(
                input_tokens=100,
                output_tokens=50,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )
            mock_response.model = "claude-sonnet-4-6"
            mock_create.return_value = mock_response

            agent.handle_message("hej", chat_id="test")

            call_kwargs = mock_create.call_args[1]
            assert "thinking" not in call_kwargs

    def test_max_tokens_from_settings(self, engine):
        """Verify max_tokens uses settings.claude_max_tokens."""
        settings = _make_settings(claude_max_tokens=8192)
        agent = Agent(settings=settings, engine=engine)

        with patch.object(agent.client.messages, "create") as mock_create:
            mock_response = MagicMock()
            mock_response.stop_reason = "end_turn"
            mock_response.content = [MagicMock(type="text", text="Hej")]
            mock_response.usage = MagicMock(
                input_tokens=100,
                output_tokens=50,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )
            mock_response.model = "claude-sonnet-4-6"
            mock_create.return_value = mock_response

            agent.handle_message("hej", chat_id="test")

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["max_tokens"] == 8192


class TestThinkingBlocks:
    def test_thinking_blocks_not_in_response_text(self, engine):
        """Response with thinking + text blocks → AgentResponse.text is text only."""
        settings = _make_settings(claude_thinking_budget=5000)
        agent = Agent(settings=settings, engine=engine)

        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        thinking_block.thinking = "Let me reason about this..."

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hej! Hur kan jag hjälpa?"

        response = MagicMock()
        response.stop_reason = "end_turn"
        response.content = [thinking_block, text_block]
        response.usage = MagicMock(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        response.model = "claude-sonnet-4-6"

        agent._call_api = MagicMock(return_value=response)
        result = agent.handle_message("hej", chat_id="test")

        assert result.text == "Hej! Hur kan jag hjälpa?"
        assert "reason" not in result.text

    def test_thinking_blocks_preserved_in_tool_loop(self, engine):
        """Assistant content with thinking blocks passed back in messages."""
        settings = _make_settings(claude_thinking_budget=5000)
        agent = Agent(settings=settings, engine=engine)

        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        thinking_block.thinking = "I should search for this"

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_tradera"
        tool_block.input = {"query": "stol"}
        tool_block.id = "tool_1"

        response1 = MagicMock()
        response1.stop_reason = "tool_use"
        response1.content = [thinking_block, tool_block]
        response1.usage = MagicMock(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hittade resultat"

        response2 = MagicMock()
        response2.stop_reason = "end_turn"
        response2.content = [text_block]
        response2.usage = MagicMock(
            input_tokens=200,
            output_tokens=100,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        response2.model = "claude-sonnet-4-6"

        agent._call_api = MagicMock(side_effect=[response1, response2])
        agent.execute_tool = MagicMock(return_value={"results": [], "total_count": 0})

        result = agent.handle_message("sök efter stol", chat_id="test")

        # The assistant message should include the thinking block
        assistant_msg = result.messages[1]  # [user, assistant, user_tool_result, assistant]
        assert assistant_msg["role"] == "assistant"
        assert thinking_block in assistant_msg["content"]


class TestThinkingBlockSerialization:
    def test_thinking_blocks_stripped_from_conversation_storage(self):
        """_serialize_content filters out thinking blocks."""
        thinking = MagicMock()
        thinking.type = "thinking"
        thinking.thinking = "deep reasoning here"
        thinking.model_dump.return_value = {"type": "thinking", "thinking": "deep reasoning here"}

        text = MagicMock()
        text.type = "text"
        text.text = "Hello"
        text.model_dump.return_value = {"type": "text", "text": "Hello"}

        content = [thinking, text]
        serialized = _serialize_content(content)

        assert len(serialized) == 1
        assert serialized[0]["type"] == "text"

    def test_redacted_thinking_blocks_stripped(self):
        """redacted_thinking type also filtered."""
        redacted = {"type": "redacted_thinking", "data": "abc123"}
        text = {"type": "text", "text": "Hello"}

        content = [redacted, text]
        serialized = _serialize_content(content)

        assert len(serialized) == 1
        assert serialized[0]["type"] == "text"

    def test_dict_thinking_blocks_stripped(self):
        """Dict-style thinking blocks are also filtered."""
        thinking = {"type": "thinking", "thinking": "some reasoning"}
        text = {"type": "text", "text": "Result"}

        content = [thinking, text]
        serialized = _serialize_content(content)

        assert len(serialized) == 1
        assert serialized[0]["type"] == "text"
