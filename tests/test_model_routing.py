"""Tests for model routing (#59)."""

from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from storebot.agent import Agent, _COMPLEX_CATEGORIES
from storebot.db import ApiUsage, Base


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _make_settings(**overrides):
    settings = MagicMock()
    settings.claude_api_key = "test"
    settings.claude_model = "claude-sonnet-4-5-20250929"
    settings.claude_model_simple = ""
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


def _make_response(stop_reason="end_turn", text="Hej!", tool_blocks=None, model=None):
    """Build a mock API response."""
    if tool_blocks:
        content = tool_blocks
    else:
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = text
        content = [text_block]
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = content
    resp.usage = MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    resp.model = model or "claude-sonnet-4-5-20250929"
    return resp


# ---------------------------------------------------------------------------
# _select_model unit tests
# ---------------------------------------------------------------------------


class TestSelectModel:
    def test_disabled_when_no_simple_model(self, engine):
        """Empty string → always claude_model."""
        settings = _make_settings(claude_model_simple="")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core"}, has_images=False)
        assert result == "claude-sonnet-4-5-20250929"

    def test_simple_model_for_core_only(self, engine):
        """{"core"}, no images → simple model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core"}, has_images=False)
        assert result == "claude-haiku-4-5-20251001"

    def test_complex_model_for_listing(self, engine):
        """{"core", "listing"} → claude_model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core", "listing"}, has_images=False)
        assert result == "claude-sonnet-4-5-20250929"

    def test_complex_model_for_order(self, engine):
        """{"core", "order"} → claude_model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core", "order"}, has_images=False)
        assert result == "claude-sonnet-4-5-20250929"

    def test_complex_model_for_accounting(self, engine):
        """{"core", "accounting"} → claude_model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core", "accounting"}, has_images=False)
        assert result == "claude-sonnet-4-5-20250929"

    def test_complex_model_for_analytics(self, engine):
        """{"core", "analytics"} → claude_model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core", "analytics"}, has_images=False)
        assert result == "claude-sonnet-4-5-20250929"

    def test_complex_model_when_images_present(self, engine):
        """Images → claude_model regardless of categories."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core"}, has_images=True)
        assert result == "claude-sonnet-4-5-20250929"

    def test_complex_model_when_thinking_enabled(self, engine):
        """Budget >= 1024 → claude_model."""
        settings = _make_settings(
            claude_model_simple="claude-haiku-4-5-20251001",
            claude_thinking_budget=2048,
        )
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core"}, has_images=False)
        assert result == "claude-sonnet-4-5-20250929"

    def test_simple_model_for_research_only(self, engine):
        """{"core", "research"} → simple model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core", "research"}, has_images=False)
        assert result == "claude-haiku-4-5-20251001"

    def test_simple_model_for_scout(self, engine):
        """{"core", "scout"} → simple model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core", "scout"}, has_images=False)
        assert result == "claude-haiku-4-5-20251001"

    def test_simple_model_for_marketing(self, engine):
        """{"core", "marketing"} → simple model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core", "marketing"}, has_images=False)
        assert result == "claude-haiku-4-5-20251001"

    def test_mixed_simple_and_complex(self, engine):
        """{"core", "research", "listing"} → claude_model (listing is complex)."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        result = agent._select_model({"core", "research", "listing"}, has_images=False)
        assert result == "claude-sonnet-4-5-20250929"


# ---------------------------------------------------------------------------
# Integration tests — handle_message
# ---------------------------------------------------------------------------


class TestModelRoutingIntegration:
    def test_simple_message_uses_simple_model(self, engine):
        """Simple core-only message routes to simple model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        response = _make_response(model="claude-haiku-4-5-20251001")
        agent._call_api = MagicMock(return_value=response)

        agent.handle_message("visa produkt 5", chat_id="test")

        call_kwargs = agent._call_api.call_args
        assert call_kwargs[1]["model"] == "claude-haiku-4-5-20251001"

    def test_listing_message_uses_complex_model(self, engine):
        """'annons' keyword triggers listing category → complex model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        response = _make_response(model="claude-sonnet-4-5-20250929")
        agent._call_api = MagicMock(return_value=response)

        agent.handle_message("skapa en annons för stolen", chat_id="test")

        call_kwargs = agent._call_api.call_args
        assert call_kwargs[1]["model"] == "claude-sonnet-4-5-20250929"

    def test_tool_loop_uses_same_model(self, engine):
        """Both _call_api calls in a tool loop use the same model."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_tradera"
        tool_block.input = {"query": "stol"}
        tool_block.id = "tool_1"

        response1 = _make_response(
            stop_reason="tool_use",
            tool_blocks=[tool_block],
            model="claude-haiku-4-5-20251001",
        )
        response2 = _make_response(model="claude-haiku-4-5-20251001")

        agent._call_api = MagicMock(side_effect=[response1, response2])
        agent.execute_tool = MagicMock(return_value={"results": [], "total_count": 0})

        agent.handle_message("sök stol", chat_id="test")

        # Both calls should use the simple model (only "core"+"research" detected)
        assert agent._call_api.call_count == 2
        for call in agent._call_api.call_args_list:
            assert call[1]["model"] == "claude-haiku-4-5-20251001"

    def test_thinking_disabled_for_simple_model(self, engine):
        """When simple model is selected, thinking kwarg is not passed."""
        settings = _make_settings(
            claude_model_simple="claude-haiku-4-5-20251001",
            claude_thinking_budget=0,
        )
        agent = Agent(settings=settings, engine=engine)

        # Use the real _call_api but mock the client
        mock_response = _make_response(model="claude-haiku-4-5-20251001")
        agent.client = MagicMock()
        agent.client.messages.create.return_value = mock_response

        agent.handle_message("hej", chat_id="test")

        create_kwargs = agent.client.messages.create.call_args[1]
        assert "thinking" not in create_kwargs
        assert create_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_thinking_not_passed_when_simple_model_selected(self, engine):
        """Even if thinking_budget < 1024, simple model means no thinking kwarg."""
        settings = _make_settings(
            claude_model_simple="claude-haiku-4-5-20251001",
            claude_thinking_budget=512,  # below threshold anyway
        )
        agent = Agent(settings=settings, engine=engine)

        mock_response = _make_response(model="claude-haiku-4-5-20251001")
        agent.client = MagicMock()
        agent.client.messages.create.return_value = mock_response

        agent.handle_message("hej", chat_id="test")

        create_kwargs = agent.client.messages.create.call_args[1]
        assert "thinking" not in create_kwargs

    def test_usage_stores_actual_model(self, engine):
        """ApiUsage records the model actually used by the response."""
        settings = _make_settings(claude_model_simple="claude-haiku-4-5-20251001")
        agent = Agent(settings=settings, engine=engine)
        response = _make_response(model="claude-haiku-4-5-20251001")
        agent._call_api = MagicMock(return_value=response)

        agent.handle_message("visa produkt 5", chat_id="test")

        with Session(engine) as session:
            row = session.query(ApiUsage).first()
            assert row is not None
            assert row.model == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestModelRoutingBackwardCompat:
    def test_empty_simple_model_uses_default(self, engine):
        """Default config (empty claude_model_simple) → always claude_model."""
        settings = _make_settings()  # claude_model_simple=""
        agent = Agent(settings=settings, engine=engine)
        response = _make_response()
        agent._call_api = MagicMock(return_value=response)

        agent.handle_message("hej", chat_id="test")

        call_kwargs = agent._call_api.call_args
        assert call_kwargs[1]["model"] == "claude-sonnet-4-5-20250929"


# ---------------------------------------------------------------------------
# _COMPLEX_CATEGORIES constant
# ---------------------------------------------------------------------------


class TestComplexCategories:
    def test_contains_expected_categories(self):
        assert _COMPLEX_CATEGORIES == frozenset({"listing", "order", "accounting", "analytics"})

    def test_is_frozen(self):
        assert isinstance(_COMPLEX_CATEGORIES, frozenset)
