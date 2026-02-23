"""Tests for the Audit Log TUI Viewer data queries and app."""

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.orm import Session
from textual.widgets import DataTable, Input, Select

from storebot.db import AgentAction, Base, Product
from storebot.tui.log_viewer import (
    AuditLogScreen,
    LogViewerApp,
    ProductListScreen,
    _details_str,
    _fetch_distinct,
    _format_ts,
    _truncate,
    fetch_audit_rows,
    fetch_product_rows,
    main,
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


# ---------------------------------------------------------------------------
# Helper for Textual app tests
# ---------------------------------------------------------------------------


def _make_test_db(tmp_path) -> str:
    db_path = str(tmp_path / "tui_test.db")
    eng = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    with Session(eng) as session:
        _seed_data(session)
    eng.dispose()
    return db_path


# ---------------------------------------------------------------------------
# Textual TUI integration tests
# ---------------------------------------------------------------------------


async def _wait_for_screen(app, screen_cls, pilot, *, timeout: float = 2.0):
    """Wait until app.screen is an instance of *screen_cls*."""
    deadline = time.monotonic() + timeout
    while not isinstance(app.screen, screen_cls):
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Timed out waiting for {screen_cls.__name__}, got {type(app.screen).__name__}"
            )
        await pilot.pause(delay=0.05)


def test_product_list_screen_renders(tmp_path):
    """Cover ProductListScreen compose, on_mount, _load_data, LogViewerApp.on_mount."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            table = app.screen.query_one("#product-table", DataTable)
            assert table.row_count == 4  # "All products" + 3 seeded

    asyncio.run(_run())


def test_product_list_filter(tmp_path):
    """Cover _filter_changed and filtered _load_data."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            input_widget = app.screen.query_one("#title-filter", Input)
            input_widget.value = "byrå"
            await pilot.pause(delay=0.1)
            table = app.screen.query_one("#product-table", DataTable)
            assert table.row_count == 2  # "All products" + 1 matching

    asyncio.run(_run())


async def _select_product_row(app, pilot, row: int = 0):
    """Focus table, move cursor to row, and trigger selection → AuditLogScreen."""
    table = app.screen.query_one("#product-table", DataTable)
    table.focus()
    table.move_cursor(row=row)
    table.action_select_cursor()
    await _wait_for_screen(app, AuditLogScreen, pilot)


def test_product_row_select_pushes_audit_screen(tmp_path):
    """Cover _row_selected — push AuditLogScreen for all products."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=0)
            log_table = app.screen.query_one("#log-table", DataTable)
            assert log_table.row_count == 5

    asyncio.run(_run())


def test_product_row_select_specific_product(tmp_path):
    """Cover _row_selected with a specific product ID."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=3)  # product 1 — 3 actions
            log_table = app.screen.query_one("#log-table", DataTable)
            assert log_table.row_count == 3

    asyncio.run(_run())


def test_audit_log_screen_compose_and_mount(tmp_path):
    """Cover AuditLogScreen __init__, compose, on_mount, _get_filter, _load_data."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=0)
            agent_filter = app.screen.query_one("#agent-filter", Select)
            action_filter = app.screen.query_one("#action-filter", Select)
            assert agent_filter is not None
            assert action_filter is not None

    asyncio.run(_run())


def test_audit_log_filter_change(tmp_path):
    """Cover AuditLogScreen._filter_changed."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=0)
            agent_filter = app.screen.query_one("#agent-filter", Select)
            agent_filter.value = "listing_agent"
            await pilot.pause(delay=0.1)
            log_table = app.screen.query_one("#log-table", DataTable)
            assert log_table.row_count == 2

    asyncio.run(_run())


def test_audit_log_expand_collapse_row(tmp_path):
    """Cover _row_selected expand/collapse logic."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=0)

            log_table = app.screen.query_one("#log-table", DataTable)
            initial_count = log_table.row_count
            log_table.focus()
            log_table.move_cursor(row=0)
            log_table.action_select_cursor()
            await pilot.pause(delay=0.1)
            assert log_table.row_count == initial_count + 1

            log_table.move_cursor(row=0)
            log_table.action_select_cursor()
            await pilot.pause(delay=0.1)
            assert log_table.row_count == initial_count

    asyncio.run(_run())


def test_audit_log_select_detail_row_noop(tmp_path):
    """Cover _row_selected when detail row is selected (key ends with _detail)."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=0)

            log_table = app.screen.query_one("#log-table", DataTable)
            log_table.focus()
            log_table.move_cursor(row=0)
            log_table.action_select_cursor()  # expand row 0 → detail appended at end
            await pilot.pause(delay=0.1)
            count_after_expand = log_table.row_count
            # Detail row is appended at the end of the table
            log_table.move_cursor(row=count_after_expand - 1)
            log_table.action_select_cursor()  # select detail row → should be noop
            await pilot.pause(delay=0.1)
            assert log_table.row_count == count_after_expand

    asyncio.run(_run())


def test_audit_log_go_back(tmp_path):
    """Cover action_go_back."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=0)
            await pilot.press("escape")
            await _wait_for_screen(app, ProductListScreen, pilot)
            assert app.screen.query_one("#product-table", DataTable) is not None

    asyncio.run(_run())


def test_quit_from_product_screen(tmp_path):
    """Cover action_quit_app on ProductListScreen (line 146)."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            # Focus the table so 'q' isn't absorbed by the Input widget
            table = app.screen.query_one("#product-table", DataTable)
            table.focus()
            await pilot.press("q")

    asyncio.run(_run())


def test_quit_from_audit_screen(tmp_path):
    """Cover action_quit_app on AuditLogScreen."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=0)
            await pilot.press("q")

    asyncio.run(_run())


def test_audit_log_no_product_col_for_specific_product(tmp_path):
    """Cover _show_product_col=False branch (specific product, no Product column)."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=3)
            log_table = app.screen.query_one("#log-table", DataTable)
            assert len(log_table.columns) == 4

    asyncio.run(_run())


def test_audit_log_collapse_exception_handled(tmp_path):
    """Cover except Exception: pass in collapse path (lines 248-249)."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=0)

            log_table = app.screen.query_one("#log-table", DataTable)
            screen = app.screen
            log_table.focus()
            log_table.move_cursor(row=0)
            log_table.action_select_cursor()  # expand
            await pilot.pause(delay=0.1)

            # Manually remove the detail row so collapse's remove_row raises
            key = list(screen._expanded_rows)[0]
            detail_key = f"{key}_detail"
            log_table.remove_row(detail_key)

            # Now collapse — remove_row will raise, but except block catches it
            log_table.move_cursor(row=0)
            log_table.action_select_cursor()  # collapse
            await pilot.pause(delay=0.1)
            # Should not crash — exception silently caught
            assert key not in screen._expanded_rows

    asyncio.run(_run())


def test_audit_log_expand_missing_action(tmp_path):
    """Cover 'if aa is None: return' branch (line 255)."""
    db_path = _make_test_db(tmp_path)

    async def _run():
        app = LogViewerApp(database_path=db_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.1)
            await _select_product_row(app, pilot, row=0)

            log_table = app.screen.query_one("#log-table", DataTable)
            count_before = log_table.row_count

            # Delete all actions from DB so the row's AgentAction no longer exists
            with Session(app.db_engine) as session:
                session.execute(sa.delete(AgentAction))
                session.commit()

            log_table.focus()
            log_table.move_cursor(row=0)
            log_table.action_select_cursor()  # expand → aa will be None
            await pilot.pause(delay=0.1)
            # Row count unchanged — no detail added since aa was None
            assert log_table.row_count == count_before

    asyncio.run(_run())


def test_main_function():
    """Cover main() (lines 311-312)."""
    with patch("storebot.tui.log_viewer.LogViewerApp") as MockApp:
        mock_app = MockApp.return_value
        mock_app.run = lambda: None
        main()
