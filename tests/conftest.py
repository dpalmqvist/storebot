import pytest
import sqlalchemy as sa

from storebot.config import Settings
from storebot.db import Base


@pytest.fixture
def engine():
    """In-memory SQLite database with all tables created."""
    engine = sa.create_engine("sqlite:///:memory:")

    # Enable foreign keys for SQLite
    @sa.event.listens_for(engine, "connect")
    def enable_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """SQLAlchemy session bound to the in-memory database."""
    with sa.orm.Session(engine) as session:
        yield session


@pytest.fixture
def settings():
    """Test settings with dummy values."""
    return Settings(
        claude_api_key="test-key",
        telegram_bot_token="test-token",
        tradera_app_id="test-app-id",
        tradera_app_key="test-app-key",
        database_path=":memory:",
    )
