"""Tests for the Audit Log TUI Viewer data queries and app."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from storebot.db import AgentAction, Product
from storebot.tui.log_viewer import (
    LogViewerApp,
    _details_str,
    _fetch_distinct,
    _format_ts,
    _truncate,
    fetch_audit_rows,
    fetch_product_rows,
)


def _seed_data(session: Session) -> None:
    """Insert sample products and agent_actions for testing."""
    p1 = Product(id=1, title="Antik byrå", status="listed", category="Möbler")
    p2 = Product(id=2, title="Kopparkittel", status="sold", category="Koppar")
    p3 = Product(id=3, title="Trälåda", status="draft", category="Diverse")
    session.add_all([p1, p2, p3])
    session.flush()

    actions = [
        AgentAction(
            agent_name="listing_agent",
            action_type="create_draft",
            product_id=1,
            details={"title": "Antik byrå i ek"},
            executed_at=datetime(2026, 1, 10, 12, 0, tzinfo=UTC),
        ),
        AgentAction(
            agent_name="pricing_agent",
            action_type="price_check",
            product_id=1,
            details={"suggested_range": [200, 500]},
            executed_at=datetime(2026, 1, 11, 9, 0, tzinfo=UTC),
        ),
        AgentAction(
            agent_name="listing_agent",
            action_type="publish_listing",
            product_id=1,
            details={"platform": "tradera"},
            executed_at=datetime(2026, 1, 12, 14, 30, tzinfo=UTC),
        ),
        AgentAction(
            agent_name="order_agent",
            action_type="create_sale_voucher",
            product_id=2,
            details={"voucher": "V-2026-001"},
            executed_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
        ),
        AgentAction(
            agent_name="scout_agent",
            action_type="run_search",
            product_id=None,
            details={"query": "antik lampa"},
            executed_at=datetime(2026, 2, 5, 8, 0, tzinfo=UTC),
        ),
    ]
    session.add_all(actions)
    session.commit()


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


def test_format_ts_none():
    assert _format_ts(None) == ""


def test_format_ts():
    ts = datetime(2026, 1, 15, 14, 30, tzinfo=UTC)
    assert _format_ts(ts) == "2026-01-15 14:30"


def test_truncate_short():
    assert _truncate("hello", 10) == "hello"


def test_truncate_long():
    text = "a" * 70
    result = _truncate(text, 60)
    assert len(result) == 60
    assert result.endswith("\u2026")


def test_details_str_none():
    assert _details_str(None) == ""


def test_details_str_dict():
    result = _details_str({"key": "value"})
    assert "key" in result


# ---------------------------------------------------------------------------
# Product list query tests
# ---------------------------------------------------------------------------


def test_fetch_product_rows(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_product_rows(session)

    assert len(rows) == 3
    ids = [r[0] for r in rows]
    assert ids == [3, 2, 1]

    action_counts = {r[0]: r[4] for r in rows}
    assert action_counts[1] == 3
    assert action_counts[2] == 1
    assert action_counts[3] == 0


def test_fetch_product_rows_filter(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_product_rows(session, title_filter="byrå")

    assert len(rows) == 1
    assert rows[0][1] == "Antik byrå"


def test_fetch_product_rows_filter_no_match(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_product_rows(session, title_filter="zzz_nonexistent")

    assert len(rows) == 0


# ---------------------------------------------------------------------------
# Audit log query tests
# ---------------------------------------------------------------------------


def test_fetch_audit_rows_all(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_audit_rows(session)

    assert len(rows) == 5
    timestamps = [r[1] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)


def test_fetch_audit_rows_by_product(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_audit_rows(session, product_id=1)

    assert len(rows) == 3
    assert all(r[4] == 1 for r in rows)


def test_fetch_audit_rows_by_agent(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_audit_rows(session, agent_name="listing_agent")

    assert len(rows) == 2
    assert all(r[2] == "listing_agent" for r in rows)


def test_fetch_audit_rows_by_action_type(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_audit_rows(session, action_type="price_check")

    assert len(rows) == 1
    assert rows[0][3] == "price_check"


def test_fetch_audit_rows_combined_filters(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_audit_rows(
            session, product_id=1, agent_name="listing_agent", action_type="create_draft"
        )

    assert len(rows) == 1
    assert rows[0][2] == "listing_agent"
    assert rows[0][3] == "create_draft"


def test_fetch_audit_rows_sort_asc(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_audit_rows(session, sort_desc=False)

    timestamps = [r[1] for r in rows]
    assert timestamps == sorted(timestamps)


def test_fetch_audit_rows_sort_by_agent(engine):
    with Session(engine) as session:
        _seed_data(session)
        rows = fetch_audit_rows(session, sort_column="agent_name", sort_desc=False)

    agents = [r[2] for r in rows]
    assert agents == sorted(agents)


# ---------------------------------------------------------------------------
# Distinct value queries
# ---------------------------------------------------------------------------


def test_fetch_distinct_agents(engine):
    with Session(engine) as session:
        _seed_data(session)
        agents = _fetch_distinct(session, AgentAction.agent_name)

    assert sorted(agents) == ["listing_agent", "order_agent", "pricing_agent", "scout_agent"]


def test_fetch_distinct_action_types(engine):
    with Session(engine) as session:
        _seed_data(session)
        types = _fetch_distinct(session, AgentAction.action_type)

    assert "create_draft" in types
    assert "price_check" in types
    assert "run_search" in types


# ---------------------------------------------------------------------------
# App instantiation test
# ---------------------------------------------------------------------------


def test_app_creates(tmp_path):
    """LogViewerApp can be instantiated with a custom db path."""
    db_path = str(tmp_path / "test.db")
    app = LogViewerApp(database_path=db_path)
    assert app.db_engine is not None
    assert db_path in str(app.db_engine.url)
