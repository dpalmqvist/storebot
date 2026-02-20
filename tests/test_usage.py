"""Tests for API token/cost tracking (#56)."""

from decimal import Decimal
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from storebot.db import ApiUsage, Base
from storebot.agent import Agent, _estimate_cost_sek
from storebot.tools.analytics import AnalyticsService

FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0)


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


# --- ApiUsage model CRUD ---


class TestApiUsageModel:
    def test_create_and_read(self, engine):
        with Session(engine) as session:
            session.add(
                ApiUsage(
                    chat_id="123",
                    model="claude-sonnet-4-6",
                    input_tokens=1000,
                    output_tokens=500,
                    cache_creation_input_tokens=200,
                    cache_read_input_tokens=800,
                    tool_calls=3,
                    estimated_cost_sek=0.15,
                )
            )
            session.commit()

        with Session(engine) as session:
            row = session.query(ApiUsage).first()
            assert row.chat_id == "123"
            assert row.input_tokens == 1000
            assert row.output_tokens == 500
            assert row.cache_creation_input_tokens == 200
            assert row.cache_read_input_tokens == 800
            assert row.tool_calls == 3
            assert row.estimated_cost_sek == Decimal("0.1500")

    def test_null_chat_id(self, engine):
        with Session(engine) as session:
            session.add(
                ApiUsage(
                    chat_id=None,
                    model="test-model",
                    input_tokens=100,
                    output_tokens=50,
                )
            )
            session.commit()

        with Session(engine) as session:
            row = session.query(ApiUsage).first()
            assert row.chat_id is None

    def test_created_at_auto_set(self, engine):
        with Session(engine) as session:
            session.add(ApiUsage(model="test-model", input_tokens=0, output_tokens=0))
            session.commit()

        with Session(engine) as session:
            row = session.query(ApiUsage).first()
            assert row.created_at is not None


# --- Cost estimation ---


class TestEstimateCostSek:
    def test_known_model(self):
        cost = _estimate_cost_sek(
            model="claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=100_000,
            cache_creation=0,
            cache_read=0,
        )
        # 1M * 3.0/1M + 100K * 15.0/1M = 3.0 + 1.5 = 4.5 USD * 10.5 = 47.25 SEK
        assert cost == Decimal("47.2500")

    def test_cache_pricing(self):
        cost = _estimate_cost_sek(
            model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
            cache_creation=1_000_000,
            cache_read=1_000_000,
        )
        # 1M * 3.75/1M + 1M * 0.30/1M = 3.75 + 0.30 = 4.05 USD * 10.5 = 42.525
        assert cost == Decimal("42.5250")

    def test_unknown_model_falls_back_to_sonnet(self):
        cost = _estimate_cost_sek(
            model="unknown-model-xyz",
            input_tokens=1_000_000,
            output_tokens=0,
            cache_creation=0,
            cache_read=0,
        )
        # Falls back to Sonnet: 1M * 3.0/1M = 3.0 USD * 10.5 = 31.5 SEK
        assert cost == Decimal("31.5000")

    def test_zero_tokens(self):
        cost = _estimate_cost_sek("claude-sonnet-4-6", 0, 0, 0, 0)
        assert cost == Decimal("0.0000")

    def test_returns_decimal(self):
        cost = _estimate_cost_sek("claude-sonnet-4-6", 1000, 500, 0, 0)
        assert isinstance(cost, Decimal)

    def test_haiku_model(self):
        cost = _estimate_cost_sek(
            model="claude-haiku-3-5-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_creation=0,
            cache_read=0,
        )
        # 1M * 0.80/1M + 1M * 4.0/1M = 0.80 + 4.0 = 4.80 USD * 10.5 = 50.4 SEK
        assert cost == Decimal("50.4000")


# --- _store_usage integration ---


class TestStoreUsage:
    def test_stores_usage_row(self, engine):
        settings = MagicMock()
        settings.claude_api_key = "test"
        settings.claude_model = "claude-sonnet-4-6"
        settings.tradera_app_id = "1"
        settings.tradera_app_key = "k"
        settings.tradera_sandbox = True
        settings.tradera_user_id = None
        settings.tradera_user_token = None
        settings.blocket_bearer_token = None
        settings.postnord_api_key = None

        agent = Agent(settings=settings, engine=engine)
        agent._store_usage(
            chat_id="456",
            model="claude-sonnet-4-6",
            input_tokens=5000,
            output_tokens=2000,
            cache_creation=100,
            cache_read=4000,
            tool_calls=2,
        )

        with Session(engine) as session:
            row = session.query(ApiUsage).first()
            assert row is not None
            assert row.chat_id == "456"
            assert row.input_tokens == 5000
            assert row.output_tokens == 2000
            assert row.cache_creation_input_tokens == 100
            assert row.cache_read_input_tokens == 4000
            assert row.tool_calls == 2
            assert row.estimated_cost_sek > 0

    def test_store_usage_no_engine(self):
        settings = MagicMock()
        settings.claude_api_key = "test"
        settings.claude_model = "test"
        settings.tradera_app_id = "1"
        settings.tradera_app_key = "k"
        settings.tradera_sandbox = True
        settings.tradera_user_id = None
        settings.tradera_user_token = None
        settings.blocket_bearer_token = None
        settings.postnord_api_key = None

        agent = Agent(settings=settings, engine=None)
        # Should not raise even without engine
        agent._store_usage("123", "model", 100, 50, 0, 0, 1)

    def test_store_usage_db_error_does_not_raise(self, engine):
        settings = MagicMock()
        settings.claude_api_key = "test"
        settings.claude_model = "test"
        settings.tradera_app_id = "1"
        settings.tradera_app_key = "k"
        settings.tradera_sandbox = True
        settings.tradera_user_id = None
        settings.tradera_user_token = None
        settings.blocket_bearer_token = None
        settings.postnord_api_key = None

        agent = Agent(settings=settings, engine=engine)
        # Patch Session to raise
        with patch("storebot.agent.Session", side_effect=Exception("db error")):
            agent._store_usage("123", "model", 100, 50, 0, 0, 1)  # Should not raise


# --- handle_message token accumulation ---


class TestHandleMessageAccumulation:
    def test_tokens_accumulated_across_calls(self, engine):
        """Verify that token counts from multiple _call_api calls are summed."""
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

        agent = Agent(settings=settings, engine=engine)

        # Mock two API calls: first returns tool_use, second returns text
        usage1 = MagicMock()
        usage1.input_tokens = 1000
        usage1.output_tokens = 200
        usage1.cache_creation_input_tokens = 50
        usage1.cache_read_input_tokens = 900

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_tradera"
        tool_block.input = {"query": "test"}
        tool_block.id = "tool_1"

        response1 = MagicMock()
        response1.stop_reason = "tool_use"
        response1.content = [tool_block]
        response1.usage = usage1
        response1.model = "claude-sonnet-4-6"

        usage2 = MagicMock()
        usage2.input_tokens = 1500
        usage2.output_tokens = 300
        usage2.cache_creation_input_tokens = 0
        usage2.cache_read_input_tokens = 950

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hittade 5 resultat."

        response2 = MagicMock()
        response2.stop_reason = "end_turn"
        response2.content = [text_block]
        response2.usage = usage2
        response2.model = "claude-sonnet-4-6"

        agent._call_api = MagicMock(side_effect=[response1, response2])
        agent.execute_tool = MagicMock(return_value={"results": [{"id": 1}], "total_count": 1})

        result = agent.handle_message("sök efter stol", chat_id="789")
        assert result.text == "Hittade 5 resultat."

        with Session(engine) as session:
            row = session.query(ApiUsage).first()
            assert row is not None
            assert row.chat_id == "789"
            assert row.input_tokens == 2500  # 1000 + 1500
            assert row.output_tokens == 500  # 200 + 300
            assert row.cache_creation_input_tokens == 50
            assert row.cache_read_input_tokens == 1850  # 900 + 950
            assert row.tool_calls == 1
            assert row.model == "claude-sonnet-4-6"

    def test_stores_response_model_not_settings(self, engine):
        """Verify that the actual response model is stored, not the settings alias."""
        settings = MagicMock()
        settings.claude_api_key = "test"
        settings.claude_model = "claude-sonnet-latest"  # alias in settings
        settings.claude_model_simple = ""
        settings.claude_thinking_budget = 0
        settings.tradera_app_id = "1"
        settings.tradera_app_key = "k"
        settings.tradera_sandbox = True
        settings.tradera_user_id = None
        settings.tradera_user_token = None
        settings.blocket_bearer_token = None
        settings.postnord_api_key = None

        agent = Agent(settings=settings, engine=engine)

        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 0

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hej!"

        response = MagicMock()
        response.stop_reason = "end_turn"
        response.content = [text_block]
        response.usage = usage
        response.model = "claude-sonnet-4-6"  # concrete model from API

        agent._call_api = MagicMock(return_value=response)

        agent.handle_message("hej", chat_id="test")

        with Session(engine) as session:
            row = session.query(ApiUsage).first()
            assert row.model == "claude-sonnet-4-6"  # not "claude-sonnet-latest"


# --- usage_report ---


def _insert_usage(engine, chat_id="123", created_at=None, **kwargs):
    defaults = {
        "model": "claude-sonnet-4-6",
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "tool_calls": 1,
        "estimated_cost_sek": 0.05,
    }
    defaults.update(kwargs)
    with Session(engine) as session:
        row = ApiUsage(chat_id=chat_id, created_at=created_at or FIXED_NOW, **defaults)
        session.add(row)
        session.commit()


class TestUsageReport:
    def test_with_sample_data(self, engine):
        _insert_usage(engine, created_at=datetime(2026, 6, 10))
        _insert_usage(
            engine, created_at=datetime(2026, 6, 12), input_tokens=2000, output_tokens=800
        )

        svc = AnalyticsService(engine=engine)
        result = svc.usage_report("2026-06")

        assert result["total_turns"] == 2
        assert result["total_input_tokens"] == 3000
        assert result["total_output_tokens"] == 1300
        assert result["total_cost_sek"] == 0.10
        assert result["total_tool_calls"] == 2
        assert len(result["daily"]) == 2
        assert "2026-06-10" in result["daily"]
        assert "2026-06-12" in result["daily"]

    def test_empty_period(self, engine):
        svc = AnalyticsService(engine=engine)
        result = svc.usage_report("2026-06")

        assert result["total_turns"] == 0
        assert result["total_input_tokens"] == 0
        assert result["total_output_tokens"] == 0
        assert result["total_cost_sek"] == 0.0
        assert result["daily"] == {}

    def test_period_filtering(self, engine):
        _insert_usage(engine, created_at=datetime(2026, 5, 15))  # May — outside
        _insert_usage(engine, created_at=datetime(2026, 6, 15))  # June — inside

        svc = AnalyticsService(engine=engine)
        result = svc.usage_report("2026-06")

        assert result["total_turns"] == 1

    def test_averages(self, engine):
        _insert_usage(
            engine,
            created_at=datetime(2026, 6, 1),
            input_tokens=1000,
            output_tokens=200,
            estimated_cost_sek=0.10,
        )
        _insert_usage(
            engine,
            created_at=datetime(2026, 6, 2),
            input_tokens=3000,
            output_tokens=800,
            estimated_cost_sek=0.30,
        )

        svc = AnalyticsService(engine=engine)
        result = svc.usage_report("2026-06")

        assert result["avg_input_per_turn"] == 2000
        assert result["avg_output_per_turn"] == 500
        assert result["avg_cost_per_turn_sek"] == 0.2

    def test_daily_breakdown_aggregation(self, engine):
        # Two entries on the same day
        _insert_usage(
            engine,
            created_at=datetime(2026, 6, 10, 10, 0),
            input_tokens=1000,
            output_tokens=200,
            estimated_cost_sek=0.05,
        )
        _insert_usage(
            engine,
            created_at=datetime(2026, 6, 10, 14, 0),
            input_tokens=3000,
            output_tokens=600,
            estimated_cost_sek=0.15,
        )

        svc = AnalyticsService(engine=engine)
        result = svc.usage_report("2026-06")

        day = result["daily"]["2026-06-10"]
        assert day["turns"] == 2
        assert day["input_tokens"] == 4000
        assert day["output_tokens"] == 800
        assert day["cost_sek"] == 0.20


# --- _format_usage ---


class TestFormatUsage:
    def test_output_contains_key_fields(self):
        data = {
            "period": "2026-06",
            "total_turns": 42,
            "total_tool_calls": 15,
            "total_input_tokens": 100000,
            "total_output_tokens": 50000,
            "total_cache_creation_tokens": 5000,
            "total_cache_read_tokens": 80000,
            "total_cost_sek": 12.50,
            "avg_cost_per_turn_sek": 0.2976,
            "daily": {
                "2026-06-10": {
                    "turns": 5,
                    "input_tokens": 20000,
                    "output_tokens": 10000,
                    "cost_sek": 2.50,
                },
            },
        }
        text = AnalyticsService._format_usage(data)
        assert "API-användning" in text
        assert "42" in text
        assert "12.50 kr" in text
        assert "2026-06-10" in text
        assert "100,000" in text  # Thousand separator
