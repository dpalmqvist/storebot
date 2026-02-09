import sqlalchemy as sa

from storebot.db import Order, PlatformListing, Product, ProductImage


def test_tables_created(engine):
    """All expected tables exist after create_all."""
    tables = sa.inspect(engine).get_table_names()

    expected = [
        "products",
        "product_images",
        "platform_listings",
        "orders",
        "agent_actions",
        "notifications",
    ]
    for table in expected:
        assert table in tables, f"Missing table: {table}"


def test_insert_and_query_product(session):
    """Can insert and query a Product."""
    product = Product(title="Ekmatstol 1940-tal", description="Renoverad ekmatstol", status="draft")
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


def test_product_cascade_relationships(session):
    """Product relationships load correctly."""
    product = Product(title="Antikt skåp", status="listed", listing_price=2500.0)
    session.add(product)
    session.flush()

    session.add(ProductImage(product_id=product.id, file_path="/photos/skap1.jpg", is_primary=True))
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
