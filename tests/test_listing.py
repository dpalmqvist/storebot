from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from storebot.db import AgentAction, PlatformListing, Product, ProductImage
from storebot.tools.listing import ListingService, _validate_draft


@pytest.fixture
def service(engine):
    return ListingService(engine=engine)


@pytest.fixture
def product(engine):
    """Create a test product and return its ID."""
    with Session(engine) as session:
        p = Product(
            title="Ektaburett 1940-tal", description="Renoverad ektaburett", status="draft"
        )
        session.add(p)
        session.commit()
        return p.id


@pytest.fixture
def draft_listing(service, product):
    """Create a draft listing and return the result."""
    return service.create_draft(
        product_id=product,
        listing_type="auction",
        listing_title="Ektaburett 1940-tal, renoverad",
        listing_description="Vacker ektaburett i fint skick från 1940-talet.",
        start_price=300.0,
        duration_days=7,
        tradera_category_id=344,
    )


class TestCreateDraft:
    def test_valid_auction(self, service, product):
        result = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Ektaburett 1940-tal",
            listing_description="Renoverad ektaburett.",
            start_price=300.0,
            duration_days=7,
        )

        assert "error" not in result
        assert result["status"] == "draft"
        assert result["listing_id"] is not None
        assert "preview" in result

    def test_valid_buy_it_now(self, service, product):
        result = service.create_draft(
            product_id=product,
            listing_type="buy_it_now",
            listing_title="Ektaburett",
            listing_description="Fin taburett.",
            buy_it_now_price=800.0,
        )

        assert "error" not in result
        assert result["status"] == "draft"

    def test_missing_product(self, service):
        result = service.create_draft(
            product_id=9999,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
        )

        assert "error" in result
        assert "9999" in result["error"]

    def test_auction_without_start_price(self, service, product):
        result = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
        )

        assert result["error"] == "Validation failed"
        assert any("start_price" in e for e in result["details"])

    def test_buy_it_now_without_price(self, service, product):
        result = service.create_draft(
            product_id=product,
            listing_type="buy_it_now",
            listing_title="Test",
            listing_description="Test",
        )

        assert result["error"] == "Validation failed"
        assert any("buy_it_now_price" in e for e in result["details"])

    def test_invalid_listing_type(self, service, product):
        result = service.create_draft(
            product_id=product,
            listing_type="unknown",
            listing_title="Test",
            listing_description="Test",
        )

        assert result["error"] == "Validation failed"
        assert any("listing_type" in e for e in result["details"])

    def test_invalid_duration(self, service, product):
        result = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
            duration_days=6,
        )

        assert result["error"] == "Validation failed"
        assert any("duration_days" in e for e in result["details"])

    def test_logs_agent_action(self, service, product, engine):
        service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
        )

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="create_draft").one()
            assert action.agent_name == "listing"
            assert action.product_id == product
            assert action.requires_approval is True
            assert action.details["listing_type"] == "auction"

    def test_with_details_json(self, service, product, engine):
        details = {"condition": "good", "shipping": "buyer_pays"}
        result = service.create_draft(
            product_id=product,
            listing_type="buy_it_now",
            listing_title="Test",
            listing_description="Test",
            buy_it_now_price=500.0,
            details=details,
        )

        with Session(engine) as session:
            listing = session.get(PlatformListing, result["listing_id"])
            assert listing.details == details


class TestListDrafts:
    def test_lists_drafts(self, service, draft_listing):
        result = service.list_drafts()

        assert result["count"] == 1
        assert result["listings"][0]["listing_title"] == "Ektaburett 1940-tal, renoverad"

    def test_empty_results(self, service):
        result = service.list_drafts()

        assert result["count"] == 0
        assert result["listings"] == []

    def test_filter_by_status(self, service, draft_listing):
        # Approve the draft
        service.approve_draft(draft_listing["listing_id"])

        assert service.list_drafts(status="draft")["count"] == 0
        assert service.list_drafts(status="approved")["count"] == 1

    def test_multiple_drafts(self, service, product):
        service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="First",
            listing_description="First draft",
            start_price=100.0,
        )
        service.create_draft(
            product_id=product,
            listing_type="buy_it_now",
            listing_title="Second",
            listing_description="Second draft",
            buy_it_now_price=500.0,
        )

        result = service.list_drafts()
        assert result["count"] == 2


class TestGetDraft:
    def test_get_existing(self, service, draft_listing):
        result = service.get_draft(draft_listing["listing_id"])

        assert result["id"] == draft_listing["listing_id"]
        assert result["listing_title"] == "Ektaburett 1940-tal, renoverad"
        assert result["product_title"] == "Ektaburett 1940-tal"
        assert result["listing_type"] == "auction"
        assert result["start_price"] == 300.0

    def test_not_found(self, service):
        result = service.get_draft(9999)

        assert "error" in result
        assert "9999" in result["error"]


class TestUpdateDraft:
    def test_update_price(self, service, draft_listing):
        result = service.update_draft(draft_listing["listing_id"], start_price=500.0)

        assert "error" not in result
        assert result["status"] == "draft"

        detail = service.get_draft(draft_listing["listing_id"])
        assert detail["start_price"] == 500.0

    def test_update_title(self, service, draft_listing):
        result = service.update_draft(draft_listing["listing_id"], listing_title="Ny titel")

        assert "error" not in result
        detail = service.get_draft(draft_listing["listing_id"])
        assert detail["listing_title"] == "Ny titel"

    def test_cannot_edit_approved(self, service, draft_listing):
        service.approve_draft(draft_listing["listing_id"])

        result = service.update_draft(draft_listing["listing_id"], start_price=500.0)
        assert "error" in result
        assert "approved" in result["error"]

    def test_unknown_fields_rejected(self, service, draft_listing):
        result = service.update_draft(draft_listing["listing_id"], fake_field="value")

        assert "error" in result
        assert "fake_field" in result["error"]

    def test_revalidation_on_update(self, service, draft_listing):
        # Change type to buy_it_now without setting buy_it_now_price
        result = service.update_draft(draft_listing["listing_id"], listing_type="buy_it_now")

        assert result["error"] == "Validation failed"
        assert any("buy_it_now_price" in e for e in result["details"])

    def test_not_found(self, service):
        result = service.update_draft(9999, start_price=100.0)

        assert "error" in result

    def test_logs_agent_action(self, service, draft_listing, engine):
        service.update_draft(draft_listing["listing_id"], start_price=500.0)

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="update_draft").one()
            assert action.agent_name == "listing"
            assert "start_price" in action.details["updated_fields"]


class TestApproveDraft:
    def test_approve(self, service, draft_listing):
        result = service.approve_draft(draft_listing["listing_id"])

        assert result["status"] == "approved"

    def test_cannot_approve_non_draft(self, service, draft_listing):
        service.approve_draft(draft_listing["listing_id"])

        result = service.approve_draft(draft_listing["listing_id"])
        assert "error" in result
        assert "approved" in result["error"]

    def test_not_found(self, service):
        result = service.approve_draft(9999)
        assert "error" in result

    def test_sets_approved_at(self, service, draft_listing, engine):
        service.approve_draft(draft_listing["listing_id"])

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="approve_draft").one()
            assert action.approved_at is not None


class TestRejectDraft:
    def test_reject_deletes_listing(self, service, draft_listing, engine):
        listing_id = draft_listing["listing_id"]
        result = service.reject_draft(listing_id, reason="Priset för högt")

        assert result["status"] == "rejected"
        assert result["reason"] == "Priset för högt"

        with Session(engine) as session:
            assert session.get(PlatformListing, listing_id) is None

    def test_reject_logs_reason(self, service, draft_listing, engine):
        service.reject_draft(draft_listing["listing_id"], reason="Dålig beskrivning")

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="reject_draft").one()
            assert action.details["reason"] == "Dålig beskrivning"

    def test_cannot_reject_non_draft(self, service, draft_listing):
        service.approve_draft(draft_listing["listing_id"])

        result = service.reject_draft(draft_listing["listing_id"])
        assert "error" in result

    def test_not_found(self, service):
        result = service.reject_draft(9999)
        assert "error" in result


class TestSearchProducts:
    def test_search_by_query(self, service, engine):
        with Session(engine) as session:
            session.add(Product(title="Ektaburett", status="draft"))
            session.add(Product(title="Mässingsljusstake", status="draft"))
            session.commit()

        result = service.search_products(query="ektaburett")
        assert result["count"] == 1
        assert result["products"][0]["title"] == "Ektaburett"

    def test_search_by_status(self, service, engine):
        with Session(engine) as session:
            session.add(Product(title="A", status="draft"))
            session.add(Product(title="B", status="listed"))
            session.commit()

        result = service.search_products(status="listed")
        assert result["count"] == 1
        assert result["products"][0]["title"] == "B"

    def test_search_no_filters(self, service, engine):
        with Session(engine) as session:
            session.add(Product(title="A", status="draft"))
            session.add(Product(title="B", status="listed"))
            session.commit()

        result = service.search_products()
        assert result["count"] == 2

    def test_search_no_results(self, service):
        result = service.search_products(query="nonexistent")
        assert result["count"] == 0
        assert result["products"] == []

    def test_search_by_description(self, service, engine):
        with Session(engine) as session:
            session.add(Product(title="Stol", description="Renoverad ekmatstol", status="draft"))
            session.commit()

        result = service.search_products(query="ekmatstol")
        assert result["count"] == 1


class TestValidateDraft:
    def test_valid_auction(self):
        assert _validate_draft("auction", 100.0, None, 7) == []

    def test_valid_buy_it_now(self):
        assert _validate_draft("buy_it_now", None, 500.0, 7) == []

    def test_invalid_type(self):
        errors = _validate_draft("invalid", 100.0, None, 7)
        assert len(errors) == 1
        assert "listing_type" in errors[0]

    def test_auction_missing_price(self):
        errors = _validate_draft("auction", None, None, 7)
        assert any("start_price" in e for e in errors)

    def test_auction_zero_price(self):
        errors = _validate_draft("auction", 0, None, 7)
        assert any("start_price" in e for e in errors)

    def test_buy_it_now_missing_price(self):
        errors = _validate_draft("buy_it_now", None, None, 7)
        assert any("buy_it_now_price" in e for e in errors)

    def test_invalid_duration(self):
        errors = _validate_draft("auction", 100.0, None, 6)
        assert any("duration_days" in e for e in errors)

    def test_none_duration_ok(self):
        assert _validate_draft("auction", 100.0, None, None) == []


class TestCreateProduct:
    def test_creates_product(self, service, engine):
        result = service.create_product(title="Ektaburett 1940-tal")

        assert "error" not in result
        assert result["product_id"] is not None
        assert result["title"] == "Ektaburett 1940-tal"
        assert result["status"] == "draft"

    def test_with_optional_fields(self, service, engine):
        result = service.create_product(
            title="Mässingsljusstake",
            description="Fin ljusstake i mässing",
            category="inredning",
            condition="bra skick",
            materials="mässing",
            era="1920-tal",
            dimensions="15x15x30 cm",
            source="dödsbo",
            acquisition_cost=50.0,
        )

        assert "error" not in result

        with Session(engine) as session:
            p = session.get(Product, result["product_id"])
            assert p.description == "Fin ljusstake i mässing"
            assert p.category == "inredning"
            assert p.condition == "bra skick"
            assert p.materials == "mässing"
            assert p.era == "1920-tal"
            assert p.acquisition_cost == 50.0

    def test_logs_agent_action(self, service, engine):
        service.create_product(title="Teststol")

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="create_product").one()
            assert action.agent_name == "listing"
            assert action.details["title"] == "Teststol"


class TestSaveProductImage:
    def test_save_image(self, service, product, tmp_path, engine):
        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"fake-jpeg-data")

        result = service.save_product_image(product, str(img_path))

        assert "error" not in result
        assert result["product_id"] == product
        assert result["image_id"] is not None
        assert result["total_images"] == 1

    def test_product_not_found(self, service, tmp_path):
        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"fake-jpeg-data")

        result = service.save_product_image(9999, str(img_path))
        assert "error" in result
        assert "9999" in result["error"]

    def test_file_not_found(self, service, product):
        result = service.save_product_image(product, "/nonexistent/photo.jpg")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_is_primary_unsets_previous(self, service, product, tmp_path, engine):
        img1 = tmp_path / "photo1.jpg"
        img1.write_bytes(b"fake1")
        img2 = tmp_path / "photo2.jpg"
        img2.write_bytes(b"fake2")

        service.save_product_image(product, str(img1), is_primary=True)
        service.save_product_image(product, str(img2), is_primary=True)

        with Session(engine) as session:
            images = session.query(ProductImage).filter_by(product_id=product).all()
            primary_images = [i for i in images if i.is_primary]
            assert len(primary_images) == 1
            assert primary_images[0].file_path == str(img2)

    def test_logs_agent_action(self, service, product, tmp_path, engine):
        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"fake-jpeg-data")

        service.save_product_image(product, str(img_path))

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="save_product_image").one()
            assert action.agent_name == "listing"
            assert action.product_id == product
            assert action.details["file_path"] == str(img_path)


class TestPublishListing:
    @pytest.fixture
    def mock_tradera(self):
        tradera = MagicMock()
        tradera.create_listing.return_value = {
            "item_id": 12345,
            "url": "https://www.tradera.com/item/12345",
        }
        tradera.upload_images.return_value = {"item_id": 12345, "images_uploaded": 1}
        return tradera

    @pytest.fixture
    def pub_service(self, engine, mock_tradera):
        return ListingService(engine=engine, tradera=mock_tradera)

    @pytest.fixture
    def approved_listing(self, pub_service, engine, tmp_path):
        """Create an approved listing with a product image."""
        # Create product
        prod_result = pub_service.create_product(title="Antik byrå")
        product_id = prod_result["product_id"]

        # Create and save image
        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"fake-jpeg-data")
        pub_service.save_product_image(product_id, str(img_path), is_primary=True)

        # Create draft
        draft = pub_service.create_draft(
            product_id=product_id,
            listing_type="auction",
            listing_title="Antik byrå 1920-tal",
            listing_description="Vacker byrå",
            start_price=500.0,
            duration_days=7,
            tradera_category_id=344,
        )

        # Approve
        pub_service.approve_draft(draft["listing_id"])
        return draft["listing_id"], product_id

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_success(self, mock_encode, mock_optimize, pub_service, approved_listing, engine):
        listing_id, product_id = approved_listing
        mock_optimize.return_value = "/tmp/optimized.jpg"
        mock_encode.return_value = ("base64data", "image/jpeg")

        result = pub_service.publish_listing(listing_id)

        assert "error" not in result
        assert result["status"] == "active"
        assert result["external_id"] == "12345"
        assert result["url"] == "https://www.tradera.com/item/12345"
        assert result["listed_at"] is not None
        assert result["ends_at"] is not None

        # Verify DB state
        with Session(engine) as session:
            listing = session.get(PlatformListing, listing_id)
            assert listing.status == "active"
            assert listing.external_id == "12345"
            assert listing.listing_url == "https://www.tradera.com/item/12345"
            assert listing.listed_at is not None
            assert listing.ends_at is not None

            product = session.get(Product, product_id)
            assert product.status == "listed"
            assert product.listing_price == 500.0

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_rejects_draft_status(self, mock_encode, mock_optimize, pub_service, engine):
        prod = pub_service.create_product(title="Test")
        draft = pub_service.create_draft(
            product_id=prod["product_id"],
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
            tradera_category_id=100,
        )

        result = pub_service.publish_listing(draft["listing_id"])

        assert "error" in result
        assert "draft" in result["error"]

    def test_not_found(self, pub_service):
        result = pub_service.publish_listing(9999)
        assert "error" in result
        assert "9999" in result["error"]

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_no_images(self, mock_encode, mock_optimize, pub_service, engine):
        prod = pub_service.create_product(title="Test")
        draft = pub_service.create_draft(
            product_id=prod["product_id"],
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
            tradera_category_id=100,
        )
        pub_service.approve_draft(draft["listing_id"])

        result = pub_service.publish_listing(draft["listing_id"])

        assert "error" in result
        assert "image" in result["error"].lower()

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_no_category_id(self, mock_encode, mock_optimize, pub_service, engine):
        prod = pub_service.create_product(title="Test")
        draft = pub_service.create_draft(
            product_id=prod["product_id"],
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
            # No tradera_category_id
        )
        pub_service.approve_draft(draft["listing_id"])

        result = pub_service.publish_listing(draft["listing_id"])

        assert "error" in result
        assert "category" in result["error"].lower()

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_non_tradera_platform(self, mock_encode, mock_optimize, pub_service, engine):
        prod = pub_service.create_product(title="Test")
        draft = pub_service.create_draft(
            product_id=prod["product_id"],
            listing_type="buy_it_now",
            listing_title="Test",
            listing_description="Test",
            buy_it_now_price=500.0,
            platform="blocket",
            tradera_category_id=100,
        )
        pub_service.approve_draft(draft["listing_id"])

        result = pub_service.publish_listing(draft["listing_id"])

        assert "error" in result
        assert "blocket" in result["error"]

    def test_no_tradera_client(self, engine):
        service = ListingService(engine=engine)
        result = service.publish_listing(1)
        assert "error" in result
        assert "not configured" in result["error"]

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_api_error_keeps_approved(
        self, mock_encode, mock_optimize, pub_service, approved_listing, engine
    ):
        listing_id, _ = approved_listing
        mock_optimize.return_value = "/tmp/optimized.jpg"
        mock_encode.return_value = ("base64data", "image/jpeg")
        pub_service.tradera.create_listing.return_value = {"error": "API down"}

        result = pub_service.publish_listing(listing_id)

        assert "error" in result
        assert "API" in result["error"]

        # Listing should still be approved
        with Session(engine) as session:
            listing = session.get(PlatformListing, listing_id)
            assert listing.status == "approved"

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_image_upload_failure_non_fatal(
        self, mock_encode, mock_optimize, pub_service, approved_listing, engine
    ):
        listing_id, _ = approved_listing
        mock_optimize.return_value = "/tmp/optimized.jpg"
        mock_encode.return_value = ("base64data", "image/jpeg")
        pub_service.tradera.upload_images.return_value = {"error": "Upload failed"}

        result = pub_service.publish_listing(listing_id)

        # Should still succeed
        assert "error" not in result
        assert result["status"] == "active"

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_logs_agent_action(
        self, mock_encode, mock_optimize, pub_service, approved_listing, engine
    ):
        listing_id, _ = approved_listing
        mock_optimize.return_value = "/tmp/optimized.jpg"
        mock_encode.return_value = ("base64data", "image/jpeg")

        pub_service.publish_listing(listing_id)

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="publish_listing").one()
            assert action.agent_name == "listing"
            assert action.details["external_id"] == "12345"
            assert action.details["url"] == "https://www.tradera.com/item/12345"

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_buy_it_now_sets_listing_price(self, mock_encode, mock_optimize, engine, tmp_path):
        tradera = MagicMock()
        tradera.create_listing.return_value = {
            "item_id": 555,
            "url": "https://www.tradera.com/item/555",
        }
        tradera.upload_images.return_value = {"item_id": 555, "images_uploaded": 1}
        service = ListingService(engine=engine, tradera=tradera)

        prod = service.create_product(title="Lampa")
        img_path = tmp_path / "lamp.jpg"
        img_path.write_bytes(b"fake")
        service.save_product_image(prod["product_id"], str(img_path), is_primary=True)

        draft = service.create_draft(
            product_id=prod["product_id"],
            listing_type="buy_it_now",
            listing_title="Lampa",
            listing_description="Fin lampa",
            buy_it_now_price=1200.0,
            tradera_category_id=100,
        )
        service.approve_draft(draft["listing_id"])

        mock_optimize.return_value = "/tmp/optimized.jpg"
        mock_encode.return_value = ("base64data", "image/jpeg")

        result = service.publish_listing(draft["listing_id"])

        assert result["status"] == "active"
        with Session(engine) as session:
            product = session.get(Product, prod["product_id"])
            assert product.listing_price == 1200.0
