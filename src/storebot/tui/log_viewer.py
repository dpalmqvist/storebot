"""Audit Log TUI Viewer — two-screen Textual app for reviewing agent_actions."""

from __future__ import annotations

import json
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Select, Static

from storebot.db import AgentAction, Product, create_engine

_NONE_SENTINEL = "__none__"


# ---------------------------------------------------------------------------
# Data-access helpers
# ---------------------------------------------------------------------------


def fetch_product_rows(session: Session, title_filter: str = "") -> list[tuple]:
    """Return (id, title, status, category, action_count) for every product."""
    stmt = (
        sa.select(
            Product.id,
            Product.title,
            Product.status,
            Product.category,
            sa.func.count(AgentAction.id).label("action_count"),
        )
        .outerjoin(AgentAction, AgentAction.product_id == Product.id)
        .group_by(Product.id, Product.title, Product.status, Product.category)
        .order_by(Product.id.desc())
    )
    if title_filter:
        stmt = stmt.where(Product.title.ilike(f"%{title_filter}%"))
    return list(session.execute(stmt).all())


def fetch_audit_rows(
    session: Session,
    product_id: int | None = None,
    agent_name: str | None = None,
    action_type: str | None = None,
    sort_column: str = "executed_at",
    sort_desc: bool = True,
) -> list[tuple]:
    """Return audit log rows, optionally filtered."""
    stmt = sa.select(
        AgentAction.id,
        AgentAction.executed_at,
        AgentAction.agent_name,
        AgentAction.action_type,
        AgentAction.product_id,
        AgentAction.details,
    )
    if product_id is not None:
        stmt = stmt.where(AgentAction.product_id == product_id)
    if agent_name:
        stmt = stmt.where(AgentAction.agent_name == agent_name)
    if action_type:
        stmt = stmt.where(AgentAction.action_type == action_type)

    col_map = {
        "executed_at": AgentAction.executed_at,
        "agent_name": AgentAction.agent_name,
        "action_type": AgentAction.action_type,
        "product_id": AgentAction.product_id,
    }
    order_col = col_map.get(sort_column, AgentAction.executed_at)
    stmt = stmt.order_by(order_col.desc() if sort_desc else order_col.asc())
    return list(session.execute(stmt).all())


def _fetch_distinct(session: Session, column: sa.orm.MappedColumn) -> list[str]:
    """Return sorted distinct values for a column."""
    rows = session.execute(sa.select(column).distinct().order_by(column)).all()
    return [r[0] for r in rows if r[0] is not None]


def _format_ts(ts: datetime | None) -> str:
    if ts is None:
        return ""
    return ts.strftime("%Y-%m-%d %H:%M")


def _truncate(text: str, length: int = 60) -> str:
    if len(text) <= length:
        return text
    return text[: length - 1] + "\u2026"


def _details_str(details: dict | None) -> str:
    if not details:
        return ""
    return _truncate(json.dumps(details, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Screen 1 — Product List
# ---------------------------------------------------------------------------


class ProductListScreen(Screen):
    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("escape", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(placeholder="Filter by product title\u2026", id="title-filter")
        yield DataTable(id="product-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#product-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "Title", "Status", "Category", "# Actions")
        self._load_data()

    def _load_data(self, title_filter: str = "") -> None:
        table = self.query_one("#product-table", DataTable)
        table.clear()
        table.add_row("*", "All products (unfiltered)", "", "", "", key="all")

        with Session(self.app.db_engine) as session:
            rows = fetch_product_rows(session, title_filter)
        for pid, title, status, category, count in rows:
            table.add_row(
                str(pid),
                _truncate(title or "", 40),
                status or "",
                category or "",
                str(count),
                key=str(pid),
            )

    @on(Input.Changed, "#title-filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self._load_data(event.value.strip())

    @on(DataTable.RowSelected, "#product-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        product_id = None if key == "all" else int(key)
        self.app.push_screen(AuditLogScreen(product_id=product_id))

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# Screen 2 — Audit Log
# ---------------------------------------------------------------------------


class AuditLogScreen(Screen):
    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("escape", "go_back", "Back"),
        Binding("backspace", "go_back", "Back"),
    ]

    def __init__(self, product_id: int | None = None) -> None:
        super().__init__()
        self.product_id = product_id
        self.sort_column = "executed_at"
        self.sort_desc = True
        self._expanded_rows: set[str] = set()
        self._show_product_col = product_id is None

    def compose(self) -> ComposeResult:
        title = "all products" if self._show_product_col else f"product #{self.product_id}"
        yield Header(show_clock=True)
        yield Static(f"Audit log \u2014 {title}", id="screen-title")
        with Horizontal(id="filter-bar"):
            yield Select(
                [("All agents", _NONE_SENTINEL)],
                value=_NONE_SENTINEL,
                id="agent-filter",
                allow_blank=False,
            )
            yield Select(
                [("All actions", _NONE_SENTINEL)],
                value=_NONE_SENTINEL,
                id="action-filter",
                allow_blank=False,
            )
        yield DataTable(id="log-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#log-table", DataTable)
        table.cursor_type = "row"
        columns = ["Timestamp", "Agent", "Action"]
        if self._show_product_col:
            columns.append("Product")
        columns.append("Details")
        table.add_columns(*columns)

        with Session(self.app.db_engine) as session:
            agents = _fetch_distinct(session, AgentAction.agent_name)
            action_types = _fetch_distinct(session, AgentAction.action_type)

        self.query_one("#agent-filter", Select).set_options(
            [("All agents", _NONE_SENTINEL)] + [(a, a) for a in agents]
        )
        self.query_one("#action-filter", Select).set_options(
            [("All actions", _NONE_SENTINEL)] + [(a, a) for a in action_types]
        )
        self._load_data()

    def _get_filter(self, selector: str) -> str | None:
        val = self.query_one(selector, Select).value
        return None if val == _NONE_SENTINEL else val

    def _load_data(self) -> None:
        table = self.query_one("#log-table", DataTable)
        table.clear()
        self._expanded_rows.clear()

        with Session(self.app.db_engine) as session:
            rows = fetch_audit_rows(
                session,
                product_id=self.product_id,
                agent_name=self._get_filter("#agent-filter"),
                action_type=self._get_filter("#action-filter"),
                sort_column=self.sort_column,
                sort_desc=self.sort_desc,
            )

        for aa_id, executed_at, agent_name, action_type, product_id, details in rows:
            cells = [_format_ts(executed_at), agent_name, action_type]
            if self._show_product_col:
                cells.append(str(product_id or ""))
            cells.append(_details_str(details))
            table.add_row(*cells, key=str(aa_id))

    @on(Select.Changed)
    def _filter_changed(self, event: Select.Changed) -> None:
        self._load_data()

    @on(DataTable.RowSelected, "#log-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None or key.endswith("_detail"):
            return

        table = self.query_one("#log-table", DataTable)
        detail_key = f"{key}_detail"

        if key in self._expanded_rows:
            self._expanded_rows.discard(key)
            try:
                table.remove_row(detail_key)
            except Exception:
                pass
            return

        with Session(self.app.db_engine) as session:
            aa = session.get(AgentAction, int(key))
            if aa is None:
                return
            details = aa.details

        formatted = (
            json.dumps(details, indent=2, ensure_ascii=False) if details else "(no details)"
        )
        num_cols = 5 if self._show_product_col else 4
        detail_cells = [formatted] + [""] * (num_cols - 1)
        table.add_row(*detail_cells, key=detail_key)
        self._expanded_rows.add(key)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class LogViewerApp(App):
    CSS = """
    #title-filter {
        dock: top;
        margin: 0 1;
    }
    #screen-title {
        dock: top;
        padding: 0 1;
        background: $primary-background;
        color: $text;
        text-style: bold;
    }
    #filter-bar {
        dock: top;
        height: 3;
        padding: 0 1;
    }
    #filter-bar Select {
        width: 1fr;
        margin-right: 1;
    }
    #log-table, #product-table {
        height: 1fr;
    }
    """

    TITLE = "Storebot Audit Log"

    def __init__(self, database_path: str | None = None) -> None:
        super().__init__()
        self.db_engine = create_engine(database_path)

    def on_mount(self) -> None:
        self.push_screen(ProductListScreen())


def main() -> None:
    app = LogViewerApp()
    app.run()


if __name__ == "__main__":
    main()
