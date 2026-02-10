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
    fortnox_voucher_id: Mapped[str | None] = mapped_column(String)
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


def _enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine(database_path: str | None = None) -> sa.Engine:
    if database_path is None:
        database_path = get_settings().database_path

    Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    engine = sa.create_engine(f"sqlite:///{database_path}")
    event.listen(engine, "connect", _enable_foreign_keys)

    # Load sqlite-vec extension if available
    @event.listens_for(engine, "connect")
    def load_sqlite_vec(dbapi_connection, connection_record):
        try:
            import sqlite_vec

            dbapi_connection.enable_load_extension(True)
            sqlite_vec.load(dbapi_connection)
            dbapi_connection.enable_load_extension(False)
        except (ImportError, Exception):
            pass  # sqlite-vec not installed or unavailable

    return engine


def init_db(database_path: str | None = None) -> sa.Engine:
    engine = create_engine(database_path)
    Base.metadata.create_all(engine)
    return engine
