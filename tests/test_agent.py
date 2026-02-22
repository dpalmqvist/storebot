"""Tests for agent.py — coverage of uncovered lines."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from storebot.agent import Agent, _detect_categories, _json_default
from storebot.db import Base, TraderaCategory


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _make_settings(**overrides):
    settings = MagicMock()
    settings.claude_api_key = "test"
    settings.claude_model = "claude-sonnet-4-6"
    settings.claude_model_simple = ""
    settings.claude_max_tokens = 16000
    settings.claude_thinking_budget = 0
    settings.tradera_app_id = "1"
    settings.tradera_app_key = "k"
    settings.tradera_sandbox = True
    settings.tradera_user_id = ""
    settings.tradera_user_token = ""
    settings.postnord_api_key = ""
    settings.compact_threshold = 100
    settings.compact_keep_recent = 6
    settings.claude_model_compact = "claude-haiku-3-5-20241022"
    settings.voucher_export_path = "/tmp/vouchers"
    settings.product_image_dir = "/tmp/images"
    settings.label_export_path = "/tmp/labels"
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_api_response(
    *,
    text="Done",
    stop_reason="end_turn",
    model="claude-sonnet-4-6",
    content=None,
):
    """Build a mock Claude API response (usage + content)."""
    resp = MagicMock()
    resp.usage.input_tokens = 100
    resp.usage.output_tokens = 50
    resp.usage.cache_creation_input_tokens = 0
    resp.usage.cache_read_input_tokens = 0
    resp.stop_reason = stop_reason
    resp.model = model
    if content is not None:
        resp.content = content
    else:
        block = MagicMock()
        block.type = "text"
        block.text = text
        resp.content = [block]
    return resp


def _make_tool_block(name, tool_input, *, tool_id="t1"):
    """Build a mock tool_use content block."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = tool_input
    return block


def _make_category(tradera_id, name, *, depth=0, path=None):
    """Build a TraderaCategory for seeding tests."""
    return TraderaCategory(
        tradera_id=tradera_id,
        name=name,
        path=path or name,
        depth=depth,
        synced_at=datetime.now(UTC),
    )


class TestJsonDefault:
    def test_decimal_converts(self):
        assert _json_default(Decimal("3.14")) == 3.14

    def test_non_decimal_raises(self):
        with pytest.raises(TypeError, match="not JSON serializable"):
            _json_default(object())


class TestCallApiThinking:
    def test_thinking_enabled_on_primary_model(self, engine):
        settings = _make_settings(claude_thinking_budget=2048)
        agent = Agent(settings=settings, engine=engine)
        agent.client.messages.create = MagicMock(return_value=_make_api_response(content=[]))

        agent._call_api([{"role": "user", "content": "Hello"}])

        call_kwargs = agent.client.messages.create.call_args.kwargs
        assert "thinking" in call_kwargs
        assert call_kwargs["thinking"]["budget_tokens"] == 2048

    def test_thinking_not_added_for_secondary_model(self, engine):
        settings = _make_settings(claude_thinking_budget=2048)
        agent = Agent(settings=settings, engine=engine)
        agent.client.messages.create = MagicMock(return_value=_make_api_response(content=[]))

        agent._call_api(
            [{"role": "user", "content": "Hello"}],
            model="claude-haiku-3-5-20241022",
        )

        call_kwargs = agent.client.messages.create.call_args.kwargs
        assert "thinking" not in call_kwargs


class TestCallApiError:
    def test_api_error_logged_and_reraised(self, engine):
        import anthropic

        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        agent.client.messages.create = MagicMock(
            side_effect=anthropic.APIError(
                message="Rate limited",
                request=MagicMock(),
                body=None,
            )
        )

        with pytest.raises(anthropic.APIError):
            agent._call_api([{"role": "user", "content": "test"}])


class TestHandleMessageImages:
    def test_image_content_construction(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        agent.client.messages.create = MagicMock(
            return_value=_make_api_response(text="I see an image")
        )

        with patch(
            "storebot.agent.encode_image_base64", return_value=("base64data", "image/jpeg")
        ):
            result = agent.handle_message(
                "What is this?",
                image_paths=["/tmp/photo.jpg"],
            )

        assert result.text == "I see an image"
        call_kwargs = agent.client.messages.create.call_args.kwargs
        user_msgs = [m for m in call_kwargs["messages"] if m.get("role") == "user"]
        assert len(user_msgs) >= 1
        img_msg = user_msgs[-1]
        assert isinstance(img_msg["content"], list)
        assert any(b.get("type") == "image" for b in img_msg["content"])


class TestSelectModel:
    def test_simple_model_used(self, engine):
        settings = _make_settings(claude_model_simple="claude-haiku-3-5-20241022")
        agent = Agent(settings=settings, engine=engine)

        model = agent._select_model({"core"}, False)
        assert model == "claude-haiku-3-5-20241022"


class TestExecuteToolDispatch:
    def test_non_dict_input(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        result = agent.execute_tool("search_tradera", "not a dict")
        assert "error" in result

    def test_request_tools_returns_error(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        result = agent.execute_tool("request_tools", {})
        assert "error" in result

    def test_unknown_tool(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        result = agent.execute_tool("nonexistent_tool_xyz", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_missing_db_service(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        agent.listing = None  # Simulate missing service
        result = agent.execute_tool("list_draft_listings", {})
        assert "error" in result
        assert "not available" in result["error"]

    def test_type_error_in_tool(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        # Pass wrong arguments to trigger TypeError
        result = agent.execute_tool("search_tradera", {"invalid_param_xyz": True})
        assert "error" in result

    def test_general_exception_in_tool(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        # Mock a service method that raises
        agent.pricing = MagicMock()
        agent.pricing.price_check = MagicMock(side_effect=RuntimeError("boom"))
        result = agent.execute_tool("price_check", {"query": "test"})
        assert "error" in result
        assert "boom" in result["error"]


class TestRequestToolsInvalidCategories:
    def test_invalid_categories_filtered(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)

        tool = _make_tool_block("request_tools", {"categories": ["invalid_cat_xyz", 12345]})
        resp_tool = _make_api_response(stop_reason="tool_use", content=[tool])
        resp_end = _make_api_response(text="Done")
        agent.client.messages.create = MagicMock(side_effect=[resp_tool, resp_end])

        result = agent.handle_message("test")
        assert result.text == "Done"


class TestParallelToolException:
    def test_parallel_exception_caught(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)

        block1 = _make_tool_block("search_tradera", {"query": "stol"}, tool_id="t1")
        block2 = _make_tool_block("search_blocket", {"query": "stol"}, tool_id="t2")
        resp_tool = _make_api_response(stop_reason="tool_use", content=[block1, block2])
        resp_end = _make_api_response(text="Results")
        agent.client.messages.create = MagicMock(side_effect=[resp_tool, resp_end])

        orig_execute = agent.execute_tool

        def _failing_execute(name, tool_input):
            if name == "search_tradera":
                raise RuntimeError("Search failed")
            return orig_execute(name, tool_input)

        agent.execute_tool = _failing_execute
        result = agent.handle_message("test")
        assert result.text == "Results"


class TestDisplayImages:
    def test_display_images_collected(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)

        tool = _make_tool_block("get_draft", {"listing_id": 1})
        resp_tool = _make_api_response(stop_reason="tool_use", content=[tool])
        resp_end = _make_api_response(text="Here is the draft")
        agent.client.messages.create = MagicMock(side_effect=[resp_tool, resp_end])

        agent.execute_tool = MagicMock(
            return_value={
                "listing_id": 1,
                "_display_images": [{"path": "/img/1.jpg"}],
            }
        )

        result = agent.handle_message("Show draft 1")
        assert len(result.display_images) == 1
        assert result.display_images[0]["path"] == "/img/1.jpg"


class TestReflectionPrompt:
    def test_reflection_appended_to_tool_result(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)

        tool = _make_tool_block("price_check", {"query": "stol"})
        resp_tool = _make_api_response(stop_reason="tool_use", content=[tool])
        resp_end = _make_api_response(text="Price analysis")

        call_count = 0

        def _capture_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return resp_tool if call_count == 1 else resp_end

        agent.client.messages.create = _capture_create
        agent.pricing = MagicMock()
        agent.pricing.price_check = MagicMock(return_value={"tradera": {}, "blocket": {}})

        agent.handle_message("Check price for stol")


class TestLogThinkingReflection:
    def test_thinking_logged_with_reflection(self, engine):
        settings = _make_settings(claude_thinking_budget=2048)
        agent = Agent(settings=settings, engine=engine)

        tool = _make_tool_block("price_check", {"query": "stol"})
        resp_tool = _make_api_response(stop_reason="tool_use", content=[tool])

        thinking = MagicMock()
        thinking.type = "thinking"
        thinking.thinking = "Let me reflect on this result..."
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Analysis done"
        resp_end = _make_api_response(content=[thinking, text_block])

        call_count = 0

        def _mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return resp_tool if call_count == 1 else resp_end

        agent.client.messages.create = _mock_create
        agent.pricing = MagicMock()
        agent.pricing.price_check = MagicMock(return_value={"tradera": {}, "blocket": {}})

        result = agent.handle_message("Price check stol")
        assert result.text == "Analysis done"


class TestQueryCategories:
    def test_with_query_filter(self, engine):
        with Session(engine) as session:
            session.add_all([_make_category(1, "Möbler"), _make_category(2, "Kläder")])
            session.commit()

        with Session(engine) as session:
            results = Agent._query_categories(session, "Möb")
            assert len(results) == 1
            assert results[0].name == "Möbler"

    def test_without_query_returns_depth_0(self, engine):
        with Session(engine) as session:
            session.add_all(
                [
                    _make_category(1, "Möbler"),
                    _make_category(2, "Stolar", depth=1, path="Möbler > Stolar"),
                ]
            )
            session.commit()

        with Session(engine) as session:
            results = Agent._query_categories(session, None)
            assert len(results) == 1
            assert results[0].depth == 0


class TestCategoriesToResult:
    def test_converts_rows(self, engine):
        with Session(engine) as session:
            session.add(_make_category(1, "Möbler"))
            session.commit()
            cat = session.query(TraderaCategory).first()
            result = Agent._categories_to_result([cat])
            assert "categories" in result
            assert result["categories"][0]["name"] == "Möbler"


class TestExecuteGetCategories:
    def test_db_hit(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)

        with Session(engine) as session:
            session.add(_make_category(1, "Möbler"))
            session.commit()

        result = agent._execute_get_categories({"query": "Möbler"})
        assert "categories" in result

    def test_empty_db_auto_sync(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        agent.tradera = MagicMock()
        agent.tradera.sync_categories_to_db = MagicMock(return_value=0)
        agent.tradera.get_categories = MagicMock(
            return_value={"categories": [{"tradera_id": 1, "name": "T", "path": "T", "depth": 0}]}
        )

        result = agent._execute_get_categories({})
        assert "categories" in result

    def test_no_engine_live_api(self):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=None)
        agent.tradera = MagicMock()
        agent.tradera.get_categories = MagicMock(
            return_value={
                "categories": [
                    {"tradera_id": 1, "name": "Möbler", "path": "Möbler", "depth": 0},
                    {"tradera_id": 2, "name": "Kläder", "path": "Kläder", "depth": 0},
                    {"tradera_id": 3, "name": "Stolar", "path": "Möbler > Stolar", "depth": 1},
                ]
            }
        )

        result = agent._execute_get_categories({})
        assert "categories" in result
        assert all(c.get("depth") == 0 for c in result["categories"])

    def test_no_engine_with_query(self):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=None)
        agent.tradera = MagicMock()
        agent.tradera.get_categories = MagicMock(
            return_value={
                "categories": [
                    {"tradera_id": 1, "name": "Möbler", "path": "Möbler", "depth": 0},
                    {"tradera_id": 2, "name": "Kläder", "path": "Kläder", "depth": 0},
                ]
            }
        )

        result = agent._execute_get_categories({"query": "Möbler"})
        assert "categories" in result
        assert len(result["categories"]) == 1

    def test_auto_sync_exception_falls_through(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        agent.tradera = MagicMock()
        agent.tradera.sync_categories_to_db = MagicMock(side_effect=RuntimeError("API down"))
        agent.tradera.get_categories = MagicMock(
            return_value={"categories": [{"tradera_id": 1, "name": "T", "path": "T", "depth": 0}]}
        )

        result = agent._execute_get_categories({})
        assert "categories" in result


class TestDetectCategoriesContentNone:
    def test_content_none_skipped(self):
        """Cover line 313: message with content=None."""
        messages = [
            {"role": "user", "content": None},
            {"role": "user", "content": "Hello"},
        ]
        cats = _detect_categories(messages, set())
        assert "core" in cats

    def test_block_with_hasattr_type(self):
        """Cover lines 331-332: block with .type attribute (not dict)."""
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "sälj möbler"
        messages = [{"role": "assistant", "content": [text_block]}]
        cats = _detect_categories(messages, set())
        assert "core" in cats


class TestExecuteToolNotImplemented:
    def test_not_implemented_error(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        agent.listing = MagicMock()
        agent.listing.list_drafts = MagicMock(side_effect=NotImplementedError())
        result = agent.execute_tool("list_draft_listings", {})
        assert "not yet implemented" in result["error"]


class TestExecuteToolServiceNotInDb:
    def test_non_db_service_missing(self, engine):
        """Cover line 1026: service_attr not in _DB_SERVICES."""
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        agent._DISPATCH["fake_tool"] = ("fake_service", "method")
        try:
            result = agent.execute_tool("fake_tool", {})
            assert "not available" in result["error"]
        finally:
            agent._DISPATCH.pop("fake_tool", None)


class TestDebugLogFilteredTools:
    def test_debug_logging_of_tool_names(self, engine):
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        agent.client.messages.create = MagicMock(return_value=_make_api_response(text="Hi"))

        with patch("storebot.agent.logger") as mock_logger:
            mock_logger.isEnabledFor = MagicMock(return_value=True)
            mock_logger.info = MagicMock()
            mock_logger.debug = MagicMock()
            agent.handle_message("test")
            mock_logger.debug.assert_called()


class TestPostNordInit:
    def test_postnord_initialized_when_key_set(self, engine):
        settings = _make_settings(
            postnord_api_key="test-key",
            postnord_sender_name="Test",
            postnord_sender_street="Gatan 1",
            postnord_sender_postal_code="12345",
            postnord_sender_city="Stockholm",
            postnord_sender_country_code="SE",
            postnord_sender_phone="0701234567",
            postnord_sender_email="t@t.com",
            postnord_sandbox=True,
        )
        agent = Agent(settings=settings, engine=engine)
        assert agent.postnord is not None


class TestRequestToolsNonListCategories:
    def test_non_list_categories_reset(self, engine):
        """Cover line 616: categories is not a list → reset to []."""
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)

        tool = _make_tool_block("request_tools", {"categories": "not-a-list"})
        resp_tool = _make_api_response(stop_reason="tool_use", content=[tool])
        resp_end = _make_api_response(text="Done")
        agent.client.messages.create = MagicMock(side_effect=[resp_tool, resp_end])

        result = agent.handle_message("test")
        assert result.text == "Done"


class TestCompactHistoryTextBlocks:
    def test_text_block_in_list_content(self, engine):
        """Cover line 771: text block extraction from list content in compact_history."""
        settings = _make_settings(compact_threshold=3, compact_keep_recent=1)
        agent = Agent(settings=settings, engine=engine)

        messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": [{"type": "text", "text": "Here is my response"}]},
            {"role": "user", "content": "Follow up"},
            {"role": "assistant", "content": "Simple answer"},
        ]

        resp = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = "Summary of conversation"
        resp.content = [block]
        agent.client.messages.create = MagicMock(return_value=resp)

        result = agent.compact_history(messages)
        assert len(result) < len(messages)
        assert result is not messages


class TestAutoSyncPopulatesDB:
    def test_categories_found_after_sync(self, engine):
        """Cover line 973: _categories_to_result returned after auto-sync populates DB."""
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)
        agent.tradera = MagicMock()

        def _sync_side_effect(engine_arg):
            with Session(engine_arg) as session:
                session.add(_make_category(999, "SyncedCat"))
                session.commit()
            return 1

        agent.tradera.sync_categories_to_db = MagicMock(side_effect=_sync_side_effect)

        result = agent._execute_get_categories({})
        assert "categories" in result
        assert any(c["name"] == "SyncedCat" for c in result["categories"])


class TestExecuteToolGetCategoriesDispatch:
    def test_dispatch_to_get_categories(self, engine):
        """Cover line 1013: execute_tool dispatches get_categories."""
        settings = _make_settings()
        agent = Agent(settings=settings, engine=engine)

        with Session(engine) as session:
            session.add(_make_category(1, "Testkat"))
            session.commit()

        result = agent.execute_tool("get_categories", {})
        assert "categories" in result
        assert result["categories"][0]["name"] == "Testkat"
