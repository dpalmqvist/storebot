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


class TestUpdateProduct:
    def test_update_single_field(self, service, product, engine):
        result = service.update_product(product, acquisition_cost=150.0)

        assert "error" not in result
        assert result["updated_fields"] == ["acquisition_cost"]

        with Session(engine) as session:
            p = session.get(Product, product)
            assert p.acquisition_cost == 150.0

    def test_update_multiple_fields(self, service, product, engine):
        result = service.update_product(
            product,
            description="Ny beskrivning",
            category="möbler",
            weight_grams=3500,
        )

        assert "error" not in result
        assert sorted(result["updated_fields"]) == ["category", "description", "weight_grams"]

        with Session(engine) as session:
            p = session.get(Product, product)
            assert p.description == "Ny beskrivning"
            assert p.category == "möbler"
            assert p.weight_grams == 3500

    def test_not_found(self, service):
        result = service.update_product(9999, title="Nope")
        assert "error" in result
        assert "9999" in result["error"]

    def test_no_fields_returns_current(self, service, product):
        result = service.update_product(product)

        assert "error" not in result
        assert result["product_id"] == product
        assert result["updated_fields"] == []

    def test_clear_field_to_none(self, service, product, engine):
        service.update_product(product, era="1950-tal")
        result = service.update_product(product, era=None)

        assert "error" not in result
        assert "era" in result["updated_fields"]

        with Session(engine) as session:
            p = session.get(Product, product)
            assert p.era is None

    def test_negative_acquisition_cost_rejected(self, service, product):
        result = service.update_product(product, acquisition_cost=-10.0)
        assert "error" in result
        assert "acquisition_cost" in result["error"]

    def test_zero_weight_rejected(self, service, product):
        result = service.update_product(product, weight_grams=0)
        assert "error" in result
        assert "weight_grams" in result["error"]

    def test_no_fields_skips_audit_log(self, service, product, engine):
        service.update_product(product)

        with Session(engine) as session:
            count = session.query(AgentAction).filter_by(action_type="update_product").count()
            assert count == 0

    def test_logs_agent_action(self, service, product, engine):
        service.update_product(product, era="1950-tal")

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="update_product").one()
            assert action.agent_name == "listing"
            assert action.details["updated_fields"] == ["era"]
            assert action.product_id == product


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

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_passes_shipping_options_to_tradera(
        self, mock_encode, mock_optimize, pub_service, approved_listing, engine
    ):
        listing_id, _ = approved_listing
        mock_optimize.return_value = "/tmp/optimized.jpg"
        mock_encode.return_value = ("base64data", "image/jpeg")

        shipping_opts = [
            {"cost": 59, "shipping_product_id": 10, "shipping_provider_id": 1},
        ]
        with Session(engine) as session:
            listing = session.get(PlatformListing, listing_id)
            listing.details = {
                "shipping_options": shipping_opts,
                "shipping_condition": "PostBefordran",
            }
            session.commit()

        pub_service.publish_listing(listing_id)

        call_kwargs = pub_service.tradera.create_listing.call_args.kwargs
        assert call_kwargs["shipping_options"] == shipping_opts
        assert call_kwargs["shipping_condition"] == "PostBefordran"
        assert call_kwargs["shipping_cost"] is None

    @patch("storebot.tools.listing.optimize_for_upload")
    @patch("storebot.tools.listing.encode_image_base64")
    def test_passes_flat_shipping_cost_from_details(
        self, mock_encode, mock_optimize, pub_service, approved_listing, engine
    ):
        listing_id, _ = approved_listing
        mock_optimize.return_value = "/tmp/optimized.jpg"
        mock_encode.return_value = ("base64data", "image/jpeg")

        with Session(engine) as session:
            listing = session.get(PlatformListing, listing_id)
            listing.details = {"shipping_cost": 49}
            session.commit()

        pub_service.publish_listing(listing_id)

        call_kwargs = pub_service.tradera.create_listing.call_args.kwargs
        assert call_kwargs["shipping_cost"] == 49
        assert call_kwargs["shipping_options"] is None


def _create_product_with_listing(engine, product_status, listing_status, listing_title="Test"):
    """Create a product with an associated PlatformListing. Returns the product ID."""
    with Session(engine) as session:
        p = Product(title=listing_title, status=product_status)
        session.add(p)
        session.flush()
        session.add(
            PlatformListing(
                product_id=p.id,
                platform="tradera",
                status=listing_status,
                listing_type="auction",
                listing_title=listing_title,
                listing_description="Test",
            )
        )
        session.commit()
        return p.id


class TestGetProductImages:
    def test_by_product_id(self, service, product, tmp_path, engine):
        img1 = tmp_path / "photo1.jpg"
        img1.write_bytes(b"fake1")
        img2 = tmp_path / "photo2.jpg"
        img2.write_bytes(b"fake2")

        service.save_product_image(product, str(img1), is_primary=True)
        service.save_product_image(product, str(img2))

        result = service.get_product_images(product_id=product)

        assert "error" not in result
        assert result["product_id"] == product
        assert result["image_count"] == 2
        assert len(result["images"]) == 2
        # Primary image first
        assert result["images"][0]["is_primary"] is True
        assert len(result["_display_images"]) == 2
        assert "huvudbild" in result["_display_images"][0]["caption"]

    def test_by_listing_id(self, service, product, tmp_path, engine):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"fake")
        service.save_product_image(product, str(img), is_primary=True)

        draft = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
        )

        result = service.get_product_images(listing_id=draft["listing_id"])

        assert "error" not in result
        assert result["product_id"] == product
        assert result["image_count"] == 1

    def test_no_images(self, service, product):
        result = service.get_product_images(product_id=product)

        assert "error" not in result
        assert result["image_count"] == 0
        assert result["images"] == []
        assert result["_display_images"] == []

    def test_product_not_found(self, service):
        result = service.get_product_images(product_id=9999)
        assert "error" in result
        assert "9999" in result["error"]

    def test_listing_not_found(self, service):
        result = service.get_product_images(listing_id=9999)
        assert "error" in result
        assert "9999" in result["error"]

    def test_no_id_given(self, service):
        result = service.get_product_images()
        assert "error" in result

    def test_missing_file_excluded_from_display(self, service, product, tmp_path, engine):
        img_exists = tmp_path / "exists.jpg"
        img_exists.write_bytes(b"real")
        missing_path = str(tmp_path / "gone.jpg")

        service.save_product_image(product, str(img_exists), is_primary=True)
        # Manually insert a record with a missing file
        with Session(engine) as session:
            session.add(ProductImage(product_id=product, file_path=missing_path))
            session.commit()

        result = service.get_product_images(product_id=product)

        assert result["image_count"] == 2
        assert len(result["images"]) == 2
        # Only the existing file should be in _display_images
        assert len(result["_display_images"]) == 1
        assert result["_display_images"][0]["path"] == str(img_exists)

    def test_primary_image_ordering(self, service, product, tmp_path):
        img1 = tmp_path / "first.jpg"
        img1.write_bytes(b"first")
        img2 = tmp_path / "primary.jpg"
        img2.write_bytes(b"primary")

        service.save_product_image(product, str(img1))
        service.save_product_image(product, str(img2), is_primary=True)

        result = service.get_product_images(product_id=product)

        # Primary should come first despite being added second
        assert result["images"][0]["file_path"] == str(img2)
        assert result["images"][0]["is_primary"] is True


class TestArchiveProduct:
    def test_archive_draft(self, service, product, engine):
        result = service.archive_product(product)

        assert "error" not in result
        assert result["status"] == "archived"
        assert result["previous_status"] == "draft"

        with Session(engine) as session:
            p = session.get(Product, product)
            assert p.status == "archived"
            assert p.previous_status == "draft"

    def test_archive_listed(self, service, engine):
        with Session(engine) as session:
            p = Product(title="Listed item", status="listed")
            session.add(p)
            session.commit()
            pid = p.id

        result = service.archive_product(pid)

        assert "error" not in result
        assert result["previous_status"] == "listed"

    def test_not_found(self, service):
        result = service.archive_product(9999)
        assert "error" in result
        assert "9999" in result["error"]

    def test_already_archived(self, service, product):
        service.archive_product(product)
        result = service.archive_product(product)

        assert "error" in result
        assert "already archived" in result["error"]

    def test_blocked_by_active_listing(self, service, engine):
        pid = _create_product_with_listing(engine, "listed", "active")

        result = service.archive_product(pid)

        assert "error" in result
        assert "active listing" in result["error"]

    def test_allowed_with_ended_listing(self, service, engine):
        pid = _create_product_with_listing(engine, "draft", "ended")

        result = service.archive_product(pid)

        assert "error" not in result
        assert result["status"] == "archived"

    def test_logs_agent_action(self, service, product, engine):
        service.archive_product(product)

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="archive_product").one()
            assert action.agent_name == "listing"
            assert action.product_id == product
            assert action.details["previous_status"] == "draft"


class TestUnarchiveProduct:
    def test_restores_draft(self, service, product, engine):
        service.archive_product(product)
        result = service.unarchive_product(product)

        assert "error" not in result
        assert result["status"] == "draft"

        with Session(engine) as session:
            p = session.get(Product, product)
            assert p.status == "draft"
            assert p.previous_status is None

    def test_restores_listed(self, service, engine):
        with Session(engine) as session:
            p = Product(title="Listed item", status="listed")
            session.add(p)
            session.commit()
            pid = p.id

        service.archive_product(pid)
        result = service.unarchive_product(pid)

        assert result["status"] == "listed"

    def test_not_found(self, service):
        result = service.unarchive_product(9999)
        assert "error" in result
        assert "9999" in result["error"]

    def test_not_archived_error(self, service, product):
        result = service.unarchive_product(product)

        assert "error" in result
        assert "not archived" in result["error"]

    def test_fallback_to_draft_when_previous_status_none(self, service, engine):
        with Session(engine) as session:
            p = Product(title="No previous", status="archived", previous_status=None)
            session.add(p)
            session.commit()
            pid = p.id

        result = service.unarchive_product(pid)

        assert result["status"] == "draft"

    def test_logs_agent_action(self, service, product, engine):
        service.archive_product(product)
        service.unarchive_product(product)

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="unarchive_product").one()
            assert action.agent_name == "listing"
            assert action.product_id == product
            assert action.details["restored_status"] == "draft"


class TestArchiveFiltering:
    def test_search_excludes_archived_by_default(self, service, engine):
        with Session(engine) as session:
            session.add(Product(title="Visible", status="draft"))
            session.add(Product(title="Hidden", status="archived"))
            session.commit()

        result = service.search_products()
        assert result["count"] == 1
        assert result["products"][0]["title"] == "Visible"

    def test_search_explicit_status_archived(self, service, engine):
        with Session(engine) as session:
            session.add(Product(title="Visible", status="draft"))
            session.add(Product(title="Hidden", status="archived"))
            session.commit()

        result = service.search_products(status="archived")
        assert result["count"] == 1
        assert result["products"][0]["title"] == "Hidden"

    def test_search_include_archived_true(self, service, engine):
        with Session(engine) as session:
            session.add(Product(title="Visible", status="draft"))
            session.add(Product(title="Hidden", status="archived"))
            session.commit()

        result = service.search_products(include_archived=True)
        assert result["count"] == 2

    def test_list_drafts_excludes_archived_products(self, service, engine):
        _create_product_with_listing(engine, "draft", "draft", "Active listing")
        _create_product_with_listing(engine, "archived", "draft", "Archived listing")

        result = service.list_drafts()
        assert result["count"] == 1
        assert result["listings"][0]["listing_title"] == "Active listing"

    def test_create_draft_blocked_for_archived_product(self, service, engine):
        with Session(engine) as session:
            p = Product(title="Archived", status="archived")
            session.add(p)
            session.commit()
            pid = p.id

        result = service.create_draft(
            product_id=pid,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
        )

        assert "error" in result
        assert "archived" in result["error"]


class TestGetProduct:
    def test_all_fields_returned(self, service, engine):
        with Session(engine) as session:
            p = Product(
                title="Ektaburett",
                description="Renoverad",
                category="möbler",
                status="draft",
                acquisition_cost=100.0,
                source="loppis",
                condition="bra skick",
                dimensions="40x40x45 cm",
                weight_grams=3500,
                materials="ek",
                era="1940-tal",
            )
            session.add(p)
            session.commit()
            pid = p.id

        result = service.get_product(pid)

        assert "error" not in result
        assert result["product_id"] == pid
        assert result["title"] == "Ektaburett"
        assert result["description"] == "Renoverad"
        assert result["category"] == "möbler"
        assert result["status"] == "draft"
        assert result["acquisition_cost"] == 100.0
        assert result["source"] == "loppis"
        assert result["condition"] == "bra skick"
        assert result["dimensions"] == "40x40x45 cm"
        assert result["weight_grams"] == 3500
        assert result["materials"] == "ek"
        assert result["era"] == "1940-tal"
        assert result["created_at"] is not None

    def test_image_and_listing_counts(self, service, engine, tmp_path):
        with Session(engine) as session:
            p = Product(title="Test", status="listed")
            session.add(p)
            session.flush()
            session.add(ProductImage(product_id=p.id, file_path="/fake/1.jpg"))
            session.add(ProductImage(product_id=p.id, file_path="/fake/2.jpg"))
            session.add(
                PlatformListing(
                    product_id=p.id,
                    platform="tradera",
                    status="active",
                    listing_type="auction",
                    listing_title="T",
                    listing_description="D",
                )
            )
            session.add(
                PlatformListing(
                    product_id=p.id,
                    platform="tradera",
                    status="ended",
                    listing_type="auction",
                    listing_title="T2",
                    listing_description="D2",
                )
            )
            session.commit()
            pid = p.id

        result = service.get_product(pid)

        assert result["image_count"] == 2
        assert result["active_listing_count"] == 1

    def test_not_found(self, service):
        result = service.get_product(9999)
        assert "error" in result
        assert "9999" in result["error"]

    def test_zero_counts_when_no_images_or_listings(self, service, product):
        result = service.get_product(product)
        assert result["image_count"] == 0
        assert result["active_listing_count"] == 0


class TestRelistProduct:
    @pytest.fixture
    def ended_listing(self, service, product, engine):
        """Create an ended listing to relist from."""
        draft = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Original titel",
            listing_description="Original beskrivning",
            start_price=200.0,
            duration_days=7,
            tradera_category_id=344,
            details={"shipping_cost": 59},
        )
        with Session(engine) as session:
            listing = session.get(PlatformListing, draft["listing_id"])
            listing.status = "ended"
            session.commit()
        return draft["listing_id"]

    def test_copies_fields_from_source(self, service, ended_listing, engine):
        result = service.relist_product(ended_listing)

        assert "error" not in result
        assert result["status"] == "draft"
        assert result["source_listing_id"] == ended_listing
        assert result["listing_id"] != ended_listing

        with Session(engine) as session:
            new = session.get(PlatformListing, result["listing_id"])
            assert new.listing_title == "Original titel"
            assert new.listing_description == "Original beskrivning"
            assert new.listing_type == "auction"
            assert new.start_price == 200.0
            assert new.duration_days == 7
            assert new.tradera_category_id == 344
            assert new.details == {"shipping_cost": 59}

    def test_overrides_work(self, service, ended_listing, engine):
        result = service.relist_product(
            ended_listing,
            listing_title="Ny titel",
            start_price=350.0,
            duration_days=10,
        )

        assert "error" not in result

        with Session(engine) as session:
            new = session.get(PlatformListing, result["listing_id"])
            assert new.listing_title == "Ny titel"
            assert new.start_price == 350.0
            assert new.duration_days == 10
            # Non-overridden fields kept
            assert new.listing_description == "Original beskrivning"
            assert new.tradera_category_id == 344

    def test_rejects_draft(self, service, draft_listing):
        result = service.relist_product(draft_listing["listing_id"])
        assert "error" in result
        assert "draft" in result["error"]

    def test_rejects_active(self, service, product, engine):
        draft = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Active",
            listing_description="Test",
            start_price=100.0,
        )
        with Session(engine) as session:
            listing = session.get(PlatformListing, draft["listing_id"])
            listing.status = "active"
            session.commit()

        result = service.relist_product(draft["listing_id"])
        assert "error" in result
        assert "active" in result["error"]

    def test_accepts_sold(self, service, product, engine):
        draft = service.create_draft(
            product_id=product,
            listing_type="buy_it_now",
            listing_title="Sold item",
            listing_description="Test",
            buy_it_now_price=500.0,
        )
        with Session(engine) as session:
            listing = session.get(PlatformListing, draft["listing_id"])
            listing.status = "sold"
            session.commit()

        result = service.relist_product(draft["listing_id"])
        assert "error" not in result
        assert result["status"] == "draft"

    def test_rejects_archived_product(self, service, product, engine):
        draft = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
        )
        with Session(engine) as session:
            listing = session.get(PlatformListing, draft["listing_id"])
            listing.status = "ended"
            product_obj = session.get(Product, product)
            product_obj.status = "archived"
            session.commit()

        result = service.relist_product(draft["listing_id"])
        assert "error" in result
        assert "archived" in result["error"]

    def test_not_found(self, service):
        result = service.relist_product(9999)
        assert "error" in result
        assert "9999" in result["error"]

    def test_logs_agent_action(self, service, ended_listing, engine):
        result = service.relist_product(ended_listing)

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="relist_product").one()
            assert action.agent_name == "listing"
            assert action.requires_approval is True
            assert action.details["source_listing_id"] == ended_listing
            assert action.details["new_listing_id"] == result["listing_id"]

    def test_validation_error_on_override(self, service, ended_listing):
        result = service.relist_product(ended_listing, duration_days=6)
        assert "error" in result
        assert "Validation failed" in result["error"]

    def test_details_are_deep_copied(self, service, ended_listing, engine):
        result = service.relist_product(ended_listing)

        with Session(engine) as session:
            source = session.get(PlatformListing, ended_listing)
            new = session.get(PlatformListing, result["listing_id"])
            assert source.details == new.details
            assert source.details is not new.details


class TestDeleteProductImage:
    def test_deletes_image(self, service, product, tmp_path, engine):
        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"fake-jpeg-data")

        save_result = service.save_product_image(product, str(img_path))
        result = service.delete_product_image(save_result["image_id"])

        assert "error" not in result
        assert result["image_id"] == save_result["image_id"]
        assert result["product_id"] == product

        with Session(engine) as session:
            assert session.get(ProductImage, save_result["image_id"]) is None

        assert not img_path.exists()

    def test_promotes_primary(self, service, product, tmp_path, engine):
        img1 = tmp_path / "primary.jpg"
        img1.write_bytes(b"primary")
        img2 = tmp_path / "second.jpg"
        img2.write_bytes(b"second")

        r1 = service.save_product_image(product, str(img1), is_primary=True)
        r2 = service.save_product_image(product, str(img2))

        service.delete_product_image(r1["image_id"])

        with Session(engine) as session:
            remaining = session.get(ProductImage, r2["image_id"])
            assert remaining.is_primary is True

    def test_handles_missing_file(self, service, product, engine):
        with Session(engine) as session:
            img = ProductImage(product_id=product, file_path="/nonexistent/gone.jpg")
            session.add(img)
            session.commit()
            image_id = img.id

        result = service.delete_product_image(image_id)

        assert "error" not in result
        assert result["image_id"] == image_id

    def test_not_found(self, service):
        result = service.delete_product_image(9999)
        assert "error" in result
        assert "9999" in result["error"]

    def test_logs_agent_action(self, service, product, tmp_path, engine):
        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"fake")

        save_result = service.save_product_image(product, str(img_path))
        service.delete_product_image(save_result["image_id"])

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="delete_product_image").one()
            assert action.agent_name == "listing"
            assert action.product_id == product
            assert action.details["image_id"] == save_result["image_id"]

    def test_no_promotion_when_no_images_left(self, service, product, tmp_path, engine):
        img = tmp_path / "only.jpg"
        img.write_bytes(b"only")
        r = service.save_product_image(product, str(img), is_primary=True)

        result = service.delete_product_image(r["image_id"])
        assert "error" not in result

        with Session(engine) as session:
            count = session.query(ProductImage).filter_by(product_id=product).count()
            assert count == 0


class TestCancelListing:
    def test_cancels_active(self, service, product, engine):
        draft = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
        )
        with Session(engine) as session:
            listing = session.get(PlatformListing, draft["listing_id"])
            listing.status = "active"
            product_obj = session.get(Product, product)
            product_obj.status = "listed"
            session.commit()

        result = service.cancel_listing(draft["listing_id"])

        assert "error" not in result
        assert result["status"] == "cancelled"
        assert result["product_status"] == "draft"
        assert "warning" in result

        with Session(engine) as session:
            listing = session.get(PlatformListing, draft["listing_id"])
            assert listing.status == "cancelled"

    def test_reverts_product_status(self, service, product, engine):
        draft = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
        )
        with Session(engine) as session:
            listing = session.get(PlatformListing, draft["listing_id"])
            listing.status = "active"
            p = session.get(Product, product)
            p.status = "listed"
            session.commit()

        service.cancel_listing(draft["listing_id"])

        with Session(engine) as session:
            p = session.get(Product, product)
            assert p.status == "draft"

    def test_keeps_listed_with_other_active(self, service, engine):
        with Session(engine) as session:
            p = Product(title="Multi-listed", status="listed")
            session.add(p)
            session.flush()
            l1 = PlatformListing(
                product_id=p.id,
                platform="tradera",
                status="active",
                listing_type="auction",
                listing_title="L1",
                listing_description="D1",
            )
            l2 = PlatformListing(
                product_id=p.id,
                platform="tradera",
                status="active",
                listing_type="auction",
                listing_title="L2",
                listing_description="D2",
            )
            session.add_all([l1, l2])
            session.commit()
            lid1, pid = l1.id, p.id

        result = service.cancel_listing(lid1)

        assert result["product_status"] == "listed"

        with Session(engine) as session:
            p = session.get(Product, pid)
            assert p.status == "listed"

    def test_does_not_revert_sold_product(self, service, engine):
        with Session(engine) as session:
            p = Product(title="Sold item", status="sold")
            session.add(p)
            session.flush()
            listing = PlatformListing(
                product_id=p.id,
                platform="tradera",
                status="active",
                listing_type="auction",
                listing_title="T",
                listing_description="D",
            )
            session.add(listing)
            session.commit()
            lid, pid = listing.id, p.id

        result = service.cancel_listing(lid)

        assert result["status"] == "cancelled"
        assert result["product_status"] == "sold"

        with Session(engine) as session:
            p = session.get(Product, pid)
            assert p.status == "sold"

    def test_rejects_non_active(self, service, draft_listing):
        result = service.cancel_listing(draft_listing["listing_id"])
        assert "error" in result
        assert "draft" in result["error"]

    def test_rejects_ended(self, service, product, engine):
        draft = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
        )
        with Session(engine) as session:
            listing = session.get(PlatformListing, draft["listing_id"])
            listing.status = "ended"
            session.commit()

        result = service.cancel_listing(draft["listing_id"])
        assert "error" in result
        assert "ended" in result["error"]

    def test_not_found(self, service):
        result = service.cancel_listing(9999)
        assert "error" in result
        assert "9999" in result["error"]

    def test_logs_agent_action(self, service, product, engine):
        draft = service.create_draft(
            product_id=product,
            listing_type="auction",
            listing_title="Test",
            listing_description="Test",
            start_price=100.0,
        )
        with Session(engine) as session:
            listing = session.get(PlatformListing, draft["listing_id"])
            listing.status = "active"
            session.commit()

        service.cancel_listing(draft["listing_id"])

        with Session(engine) as session:
            action = session.query(AgentAction).filter_by(action_type="cancel_listing").one()
            assert action.agent_name == "listing"
            assert action.product_id == product
            assert "Local cancel only" in action.details["note"]
