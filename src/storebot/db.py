from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from storebot.config import get_settings


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft/listed/sold/archived
    acquisition_cost: Mapped[float | None] = mapped_column(Float)
    listing_price: Mapped[float | None] = mapped_column(Float)
    sold_price: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String)  # tradera/blocket/market/estate_sale
    condition: Mapped[str | None] = mapped_column(String)
    dimensions: Mapped[str | None] = mapped_column(String)
    materials: Mapped[str | None] = mapped_column(String)
    era: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    images: Mapped[list["ProductImage"]] = relationship(back_populates="product")
    listings: Mapped[list["PlatformListing"]] = relationship(back_populates="product")
    orders: Mapped[list["Order"]] = relationship(back_populates="product")


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped["Product"] = relationship(back_populates="images")


class PlatformListing(Base):
    __tablename__ = "platform_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # tradera/blocket
    external_id: Mapped[str | None] = mapped_column(String)
    listing_url: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(
        String, default="draft"
    )  # draft/approved/active/ended/sold
    listing_type: Mapped[str | None] = mapped_column(String)  # auction/buy_it_now
    listing_title: Mapped[str | None] = mapped_column(String)
    listing_description: Mapped[str | None] = mapped_column(Text)
    start_price: Mapped[float | None] = mapped_column(Float)
    buy_it_now_price: Mapped[float | None] = mapped_column(Float)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    tradera_category_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)
    listed_at: Mapped[datetime | None] = mapped_column(DateTime)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    views: Mapped[int | None] = mapped_column(Integer)
    watchers: Mapped[int | None] = mapped_column(Integer)

    product: Mapped["Product"] = relationship(back_populates="listings")
    snapshots: Mapped[list["ListingSnapshot"]] = relationship(back_populates="listing")


class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("platform_listings.id"), nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0)
    watchers: Mapped[int] = mapped_column(Integer, default=0)
    bids: Mapped[int] = mapped_column(Integer, default=0)
    current_price: Mapped[float | None] = mapped_column(Float)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    listing: Mapped["PlatformListing"] = relationship(back_populates="snapshots")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(String)
    buyer_name: Mapped[str | None] = mapped_column(String)
    buyer_address: Mapped[str | None] = mapped_column(Text)
    sale_price: Mapped[float | None] = mapped_column(Float)
    platform_fee: Mapped[float | None] = mapped_column(Float)
    shipping_cost: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String, default="pending"
    )  # pending/shipped/delivered/returned
    voucher_id: Mapped[int | None] = mapped_column(ForeignKey("vouchers.id"))
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime)

    product: Mapped["Product"] = relationship(back_populates="orders")


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_name: Mapped[str] = mapped_column(String, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_user_id: Mapped[str | None] = mapped_column(String)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # "user" or "assistant"
    content: Mapped[dict | str | list | None] = mapped_column(JSON)
    image_paths: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), index=True
    )


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str] = mapped_column(String, default="both")  # tradera/blocket/both
    category: Mapped[str | None] = mapped_column(String)
    max_price: Mapped[float | None] = mapped_column(Float)
    region: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    details: Mapped[dict | None] = mapped_column(JSON)

    seen_items: Mapped[list["SeenItem"]] = relationship(back_populates="saved_search")


class SeenItem(Base):
    __tablename__ = "seen_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    saved_search_id: Mapped[int] = mapped_column(ForeignKey("saved_searches.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # tradera/blocket
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String)
    price: Mapped[float | None] = mapped_column(Float)
    url: Mapped[str | None] = mapped_column(String)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    saved_search: Mapped["SavedSearch"] = relationship(back_populates="seen_items")


class Voucher(Base):
    __tablename__ = "vouchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voucher_number: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    rows: Mapped[list["VoucherRow"]] = relationship(back_populates="voucher")


class VoucherRow(Base):
    __tablename__ = "voucher_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voucher_id: Mapped[int] = mapped_column(ForeignKey("vouchers.id"), nullable=False)
    account_number: Mapped[int] = mapped_column(Integer, nullable=False)
    account_name: Mapped[str] = mapped_column(String, nullable=False)
    debit: Mapped[float] = mapped_column(Float, default=0.0)
    credit: Mapped[float] = mapped_column(Float, default=0.0)

    voucher: Mapped["Voucher"] = relationship(back_populates="rows")


def _configure_sqlite(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def _load_sqlite_vec(dbapi_connection, connection_record):
    try:
        import sqlite_vec

        dbapi_connection.enable_load_extension(True)
        sqlite_vec.load(dbapi_connection)
        dbapi_connection.enable_load_extension(False)
    except (ImportError, Exception):
        pass  # sqlite-vec not installed or unavailable


def create_engine(database_path: str | None = None) -> sa.Engine:
    if database_path is None:
        database_path = get_settings().database_path

    Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    engine = sa.create_engine(f"sqlite:///{database_path}")
    event.listen(engine, "connect", _configure_sqlite)
    event.listen(engine, "connect", _load_sqlite_vec)

    return engine


def _find_alembic_ini() -> Path | None:
    """Locate alembic.ini relative to the project root (two levels above src/storebot/)."""
    candidate = Path(__file__).resolve().parents[2] / "alembic.ini"
    return candidate if candidate.exists() else None


def init_db(database_path: str | None = None) -> sa.Engine:
    """Initialize the database, applying Alembic migrations if available.

    Falls back to create_all() when alembic.ini is not found (e.g. in
    deployed environments without migration files).
    """
    engine = create_engine(database_path)

    alembic_ini = _find_alembic_ini()
    if alembic_ini is None:
        Base.metadata.create_all(engine)
        return engine

    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(alembic_ini))
    if database_path:
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(alembic_cfg, "head")

    return engine
