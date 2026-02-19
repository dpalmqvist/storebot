import sqlalchemy as sa

from storebot.db import (
    Order,
    PlatformListing,
    Product,
    ProductImage,
    TraderaCategory,
    create_engine,
)


def test_tables_created(engine):
    """All expected tables exist after create_all."""
    tables = sa.inspect(engine).get_table_names()

    expected = [
        "products",
        "product_images",
        "platform_listings",
        "listing_snapshots",
        "orders",
        "vouchers",
        "voucher_rows",
        "agent_actions",
        "notifications",
        "conversation_messages",
        "saved_searches",
        "seen_items",
        "tradera_categories",
    ]
    for table in expected:
        assert table in tables, f"Missing table: {table}"


def test_insert_and_query_product(session):
    """Can insert and query a Product."""
    product = Product(
        title="Ekmatstol 1940-tal", description="Renoverad ekmatstol", status="draft"
    )
    session.add(product)
    session.commit()

    result = session.query(Product).filter_by(title="Ekmatstol 1940-tal").one()
    assert result.id is not None
    assert result.status == "draft"
    assert result.description == "Renoverad ekmatstol"


def test_product_image_foreign_key(session):
    """ProductImage correctly links to Product via foreign key."""
    product = Product(title="Mässingsljusstake", status="draft")
    session.add(product)
    session.flush()

    image = ProductImage(product_id=product.id, file_path="/photos/stake.jpg", is_primary=True)
    session.add(image)
    session.commit()

    result = session.query(ProductImage).filter_by(product_id=product.id).one()
    assert result.file_path == "/photos/stake.jpg"
    assert result.is_primary is True
    assert result.product.title == "Mässingsljusstake"


def test_platform_listing_draft_columns(session):
    """PlatformListing supports draft workflow columns."""
    product = Product(title="Ektaburett", status="draft")
    session.add(product)
    session.flush()

    listing = PlatformListing(
        product_id=product.id,
        platform="tradera",
        status="draft",
        listing_type="auction",
        listing_title="Ektaburett 1940-tal, renoverad",
        listing_description="Vacker ektaburett i fint skick.",
        start_price=300.0,
        buy_it_now_price=800.0,
        duration_days=7,
        tradera_category_id=344,
        details={"condition": "good", "shipping": "buyer_pays"},
    )
    session.add(listing)
    session.commit()

    result = session.query(PlatformListing).filter_by(id=listing.id).one()
    assert result.status == "draft"
    assert result.listing_type == "auction"
    assert result.listing_title == "Ektaburett 1940-tal, renoverad"
    assert result.listing_description == "Vacker ektaburett i fint skick."
    assert result.start_price == 300.0
    assert result.buy_it_now_price == 800.0
    assert result.duration_days == 7
    assert result.tradera_category_id == 344
    assert result.details == {"condition": "good", "shipping": "buyer_pays"}
    assert result.created_at is not None


def test_product_cascade_relationships(session):
    """Product relationships load correctly."""
    product = Product(title="Antikt skåp", status="listed", listing_price=2500.0)
    session.add(product)
    session.flush()

    session.add(
        ProductImage(product_id=product.id, file_path="/photos/skap1.jpg", is_primary=True)
    )
    session.add(
        PlatformListing(
            product_id=product.id, platform="tradera", external_id="12345", status="active"
        )
    )
    session.add(
        Order(
            product_id=product.id,
            platform="tradera",
            sale_price=2400.0,
            status="pending",
        )
    )
    session.commit()

    loaded = session.query(Product).filter_by(id=product.id).one()
    assert len(loaded.images) == 1
    assert len(loaded.listings) == 1
    assert len(loaded.orders) == 1
    assert loaded.listings[0].platform == "tradera"


def test_wal_journal_mode(tmp_path):
    """create_engine configures WAL journal mode on file-based databases."""
    db_path = str(tmp_path / "test.db")
    engine = create_engine(database_path=db_path)
    with engine.connect() as conn:
        result = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        assert result == "wal"


def test_busy_timeout(tmp_path):
    """create_engine sets a 5000ms busy timeout."""
    db_path = str(tmp_path / "test.db")
    engine = create_engine(database_path=db_path)
    with engine.connect() as conn:
        result = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
        assert result == 5000


def test_foreign_keys_enabled(tmp_path):
    """create_engine enables foreign keys."""
    db_path = str(tmp_path / "test.db")
    engine = create_engine(database_path=db_path)
    with engine.connect() as conn:
        result = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
        assert result == 1


def test_tradera_category_model(session):
    """TraderaCategory stores category hierarchy fields."""
    from datetime import UTC, datetime

    cat = TraderaCategory(
        tradera_id=344,
        parent_tradera_id=100,
        name="Soffor & fåtöljer",
        path="Möbler > Vardagsrum > Soffor & fåtöljer",
        depth=2,
        description="Soffor, fåtöljer och sittmöbler för vardagsrum",
        synced_at=datetime.now(UTC),
    )
    session.add(cat)
    session.commit()

    result = session.query(TraderaCategory).filter_by(tradera_id=344).one()
    assert result.name == "Soffor & fåtöljer"
    assert result.path == "Möbler > Vardagsrum > Soffor & fåtöljer"
    assert result.depth == 2
    assert result.parent_tradera_id == 100
    assert result.description is not None
