"""Tests for parallel tool execution (#54)."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa

from storebot.agent import Agent
from storebot.db import Base


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _make_agent(engine):
    settings = MagicMock()
    settings.claude_api_key = "test"
    settings.claude_model = "claude-sonnet-4-6"
    settings.claude_model_simple = ""
    settings.claude_thinking_budget = 0
    settings.tradera_app_id = "1"
    settings.tradera_app_key = "k"
    settings.tradera_sandbox = True
    settings.tradera_user_id = None
    settings.tradera_user_token = None
    settings.blocket_bearer_token = None
    settings.postnord_api_key = None
    return Agent(settings=settings, engine=engine)


def _make_tool_block(name, tool_input, block_id):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = tool_input
    block.id = block_id
    return block


def _make_text_response(text="Klart."):
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.cache_creation_input_tokens = 0
    usage.cache_read_input_tokens = 0

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text

    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [text_block]
    response.usage = usage
    response.model = "claude-sonnet-4-6"
    return response


def _make_tool_response(tool_blocks):
    usage = MagicMock()
    usage.input_tokens = 200
    usage.output_tokens = 100
    usage.cache_creation_input_tokens = 0
    usage.cache_read_input_tokens = 0

    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = tool_blocks
    response.usage = usage
    response.model = "claude-sonnet-4-6"
    return response


class TestSingleToolNoThreading:
    def test_single_tool_uses_sequential_path(self, engine):
        """1 tool block should NOT use ThreadPoolExecutor."""
        agent = _make_agent(engine)

        tool_block = _make_tool_block("search_tradera", {"query": "stol"}, "t1")
        resp1 = _make_tool_response([tool_block])
        resp2 = _make_text_response()
        agent._call_api = MagicMock(side_effect=[resp1, resp2])
        agent.execute_tool = MagicMock(return_value={"results": [], "total_count": 0})

        with patch("storebot.agent.ThreadPoolExecutor") as mock_pool:
            agent.handle_message("sök stol")
            mock_pool.assert_not_called()

        agent.execute_tool.assert_called_once_with("search_tradera", {"query": "stol"})


class TestParallelExecution:
    def test_parallel_two_tools_preserves_order(self, engine):
        """2 tool blocks should run in parallel and results match by tool_use_id."""
        agent = _make_agent(engine)

        block_a = _make_tool_block("search_tradera", {"query": "stol"}, "ta")
        block_b = _make_tool_block("search_blocket", {"query": "stol"}, "tb")
        resp1 = _make_tool_response([block_a, block_b])
        resp2 = _make_text_response()
        agent._call_api = MagicMock(side_effect=[resp1, resp2])

        results = [
            {"results": [{"id": 1}], "total_count": 1},
            {"results": [{"id": 2}], "total_count": 1},
        ]
        call_count = 0

        def mock_execute(name, inp):
            nonlocal call_count
            r = results[call_count]
            call_count += 1
            return r

        agent.execute_tool = MagicMock(side_effect=mock_execute)

        result = agent.handle_message("sök stol")

        # Both tools executed
        assert agent.execute_tool.call_count == 2
        # Response is valid
        assert result.text == "Klart."

        # Check tool_results in the messages — find the user message with tool_result
        tool_result_msg = [
            m
            for m in result.messages
            if m.get("role") == "user" and isinstance(m.get("content"), list)
        ]
        assert len(tool_result_msg) == 1
        tool_results = tool_result_msg[0]["content"]
        assert tool_results[0]["tool_use_id"] == "ta"
        assert tool_results[1]["tool_use_id"] == "tb"

    def test_parallel_display_images_collected(self, engine):
        """_display_images from parallel tools should be collected in AgentResponse."""
        agent = _make_agent(engine)

        block_a = _make_tool_block("get_product_images", {"product_id": 1}, "ta")
        block_b = _make_tool_block("get_product_images", {"product_id": 2}, "tb")
        resp1 = _make_tool_response([block_a, block_b])
        resp2 = _make_text_response()
        agent._call_api = MagicMock(side_effect=[resp1, resp2])

        img1 = {"path": "/img/1.jpg", "media_type": "image/jpeg"}
        img2 = {"path": "/img/2.jpg", "media_type": "image/jpeg"}

        def mock_execute(name, inp):
            pid = inp.get("product_id", 0)
            if pid == 1:
                return {"images": [], "_display_images": [img1]}
            return {"images": [], "_display_images": [img2]}

        agent.execute_tool = MagicMock(side_effect=mock_execute)

        result = agent.handle_message("visa bilder")
        assert len(result.display_images) == 2
        paths = {d["path"] for d in result.display_images}
        assert paths == {"/img/1.jpg", "/img/2.jpg"}

    def test_parallel_tool_error_does_not_break_others(self, engine):
        """One tool returning error should not affect the other."""
        agent = _make_agent(engine)

        block_a = _make_tool_block("search_tradera", {"query": "stol"}, "ta")
        block_b = _make_tool_block("search_blocket", {"query": "stol"}, "tb")
        resp1 = _make_tool_response([block_a, block_b])
        resp2 = _make_text_response()
        agent._call_api = MagicMock(side_effect=[resp1, resp2])

        def mock_execute(name, inp):
            if name == "search_tradera":
                return {"error": "Timeout"}
            return {"results": [{"id": 2}], "total_count": 1}

        agent.execute_tool = MagicMock(side_effect=mock_execute)

        result = agent.handle_message("sök stol")
        assert result.text == "Klart."
        assert agent.execute_tool.call_count == 2

    def test_max_workers_capped_at_four(self, engine):
        """6 tool blocks should cap max_workers at 4."""
        agent = _make_agent(engine)

        blocks = [_make_tool_block(f"tool_{i}", {}, f"t{i}") for i in range(6)]
        resp1 = _make_tool_response(blocks)
        resp2 = _make_text_response()
        agent._call_api = MagicMock(side_effect=[resp1, resp2])
        agent.execute_tool = MagicMock(return_value={"ok": True})

        with patch("storebot.agent.ThreadPoolExecutor", wraps=ThreadPoolExecutor) as mock_pool:
            agent.handle_message("gör allt")
            mock_pool.assert_called_once_with(max_workers=4)

    def test_parallel_all_tools_executed(self, engine):
        """3 tool blocks should all be executed."""
        agent = _make_agent(engine)

        blocks = [
            _make_tool_block("search_tradera", {"query": "a"}, "t0"),
            _make_tool_block("search_blocket", {"query": "b"}, "t1"),
            _make_tool_block("price_check", {"query": "c"}, "t2"),
        ]
        resp1 = _make_tool_response(blocks)
        resp2 = _make_text_response()
        agent._call_api = MagicMock(side_effect=[resp1, resp2])
        agent.execute_tool = MagicMock(return_value={"ok": True})

        agent.handle_message("sök allt")
        assert agent.execute_tool.call_count == 3
        called_names = [call.args[0] for call in agent.execute_tool.call_args_list]
        assert set(called_names) == {"search_tradera", "search_blocket", "price_check"}
