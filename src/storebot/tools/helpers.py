"""Shared helpers for tool modules."""

from datetime import UTC, datetime

from storebot.db import AgentAction


def naive_now() -> datetime:
    """Current UTC time as a naive datetime (for comparison with SQLite-stored values)."""
    return datetime.now(UTC).replace(tzinfo=None)


def log_action(
    session,
    agent_name: str,
    action_type: str,
    details: dict,
    product_id: int | None = None,
    requires_approval: bool = False,
    approved_at: datetime | None = None,
):
    """Create and add an AgentAction audit record to the session."""
    session.add(
        AgentAction(
            agent_name=agent_name,
            action_type=action_type,
            product_id=product_id,
            details=details,
            requires_approval=requires_approval,
            approved_at=approved_at,
            executed_at=datetime.now(UTC),
        )
    )
