from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from storebot.db import AgentAction, Base, Notification, SavedSearch, SeenItem
from storebot.tools.scout import ScoutService


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def mock_tradera():
    return MagicMock()


@pytest.fixture
def mock_blocket():
    return MagicMock()


@pytest.fixture
def service(engine, mock_tradera, mock_blocket):
    return ScoutService(engine=engine, tradera=mock_tradera, blocket=mock_blocket)


def _tradera_item(id=1, title="Antik byrå", price=500, url="https://tradera.com/item/1"):
    return {"id": id, "title": title, "price": price, "url": url}


def _blocket_item(id="b1", title="Retro lampa", price=300, url="https://blocket.se/item/b1"):
    return {"id": id, "title": title, "price": price, "url": url}


def _make_search_result(*items):
    return {"total": len(items), "items": list(items)}


def _create_search(engine, query="antik byrå", platform="both", **kwargs) -> int:
    with Session(engine) as session:
        search = SavedSearch(query=query, platform=platform, **kwargs)
        session.add(search)
        session.commit()
        return search.id


class TestCreateSearch:
    def test_defaults(self, service):
        result = service.create_search(query="antik byrå")

        assert result["search_id"]
        assert result["query"] == "antik byrå"
        assert result["platform"] == "both"
        assert result["category"] is None
        assert result["max_price"] is None
        assert result["region"] is None

    def test_all_fields(self, service):
        result = service.create_search(
            query="mässing",
            platform="tradera",
            category="123",
            max_price=500.0,
            region="stockholm",
            details={"note": "test"},
        )

        assert result["platform"] == "tradera"
        assert result["category"] == "123"
        assert result["max_price"] == 500.0
        assert result["region"] == "stockholm"

    def test_invalid_platform(self, service):
        result = service.create_search(query="test", platform="ebay")

        assert "error" in result
        assert "Invalid platform" in result["error"]

    def test_logs_agent_action(self, service, engine):
        service.create_search(query="test")

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="create_search").all()
            assert len(actions) == 1
            assert actions[0].agent_name == "scout"
            assert actions[0].details["query"] == "test"


class TestListSearches:
    def test_active_only(self, service, engine):
        _create_search(engine, query="active search")
        _create_search(engine, query="inactive search", is_active=False)

        result = service.list_searches()

        assert result["count"] == 1
        assert result["searches"][0]["query"] == "active search"

    def test_include_inactive(self, service, engine):
        _create_search(engine, query="active")
        _create_search(engine, query="inactive", is_active=False)

        result = service.list_searches(include_inactive=True)

        assert result["count"] == 2

    def test_empty_list(self, service):
        result = service.list_searches()

        assert result["count"] == 0
        assert result["searches"] == []

    def test_ordering(self, service, engine):
        _create_search(engine, query="first")
        _create_search(engine, query="second")

        result = service.list_searches()

        # Ordered by created_at desc — second should be first
        assert result["searches"][0]["query"] == "second"
        assert result["searches"][1]["query"] == "first"


class TestUpdateSearch:
    def test_update_fields(self, service, engine):
        search_id = _create_search(engine)

        result = service.update_search(search_id, query="updated query", max_price=1000.0)

        assert result["query"] == "updated query"
        assert result["max_price"] == 1000.0

    def test_unknown_fields_rejected(self, service, engine):
        search_id = _create_search(engine)

        result = service.update_search(search_id, bogus="value")

        assert "error" in result
        assert "Unknown fields" in result["error"]

    def test_not_found(self, service):
        result = service.update_search(999, query="test")

        assert result["error"] == "Search 999 not found"

    def test_invalid_platform_rejected(self, service, engine):
        search_id = _create_search(engine)

        result = service.update_search(search_id, platform="ebay")

        assert "error" in result
        assert "Invalid platform" in result["error"]

    def test_logs_agent_action(self, service, engine):
        search_id = _create_search(engine)

        service.update_search(search_id, query="updated")

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="update_search").all()
            assert len(actions) == 1
            assert actions[0].details["search_id"] == search_id


class TestDeleteSearch:
    def test_soft_delete(self, service, engine):
        search_id = _create_search(engine)

        result = service.delete_search(search_id)

        assert result["status"] == "deleted"
        with Session(engine) as session:
            search = session.get(SavedSearch, search_id)
            assert search.is_active is False

    def test_not_found(self, service):
        result = service.delete_search(999)

        assert result["error"] == "Search 999 not found"

    def test_logs_agent_action(self, service, engine):
        search_id = _create_search(engine)

        service.delete_search(search_id)

        with Session(engine) as session:
            actions = session.query(AgentAction).filter_by(action_type="delete_search").all()
            assert len(actions) == 1
            assert actions[0].agent_name == "scout"


class TestRunSearch:
    def test_new_tradera_items(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="tradera")
        mock_tradera.search.return_value = _make_search_result(
            _tradera_item(id=1), _tradera_item(id=2)
        )

        result = service.run_search(search_id)

        assert result["count"] == 2
        assert all(i["platform"] == "tradera" for i in result["new_items"])

    def test_new_blocket_items(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="blocket")
        mock_blocket.search.return_value = _make_search_result(
            _blocket_item(id="b1"), _blocket_item(id="b2")
        )

        result = service.run_search(search_id)

        assert result["count"] == 2
        assert all(i["platform"] == "blocket" for i in result["new_items"])

    def test_both_platforms(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="both")
        mock_tradera.search.return_value = _make_search_result(_tradera_item(id=1))
        mock_blocket.search.return_value = _make_search_result(_blocket_item(id="b1"))

        result = service.run_search(search_id)

        assert result["count"] == 2
        platforms = {i["platform"] for i in result["new_items"]}
        assert platforms == {"tradera", "blocket"}

    def test_deduplication(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="tradera")
        mock_tradera.search.return_value = _make_search_result(_tradera_item(id=1))

        result1 = service.run_search(search_id)
        assert result1["count"] == 1

        # Same item on second run — should be deduplicated
        result2 = service.run_search(search_id)
        assert result2["count"] == 0

    def test_seen_item_persistence(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="tradera")
        mock_tradera.search.return_value = _make_search_result(
            _tradera_item(id=42, title="Byrå", price=500, url="https://tradera.com/42")
        )

        service.run_search(search_id)

        with Session(engine) as session:
            seen = session.query(SeenItem).all()
            assert len(seen) == 1
            assert seen[0].external_id == "42"
            assert seen[0].platform == "tradera"
            assert seen[0].title == "Byrå"
            assert seen[0].price == 500

    def test_last_run_at_updated(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="tradera")
        mock_tradera.search.return_value = _make_search_result()

        service.run_search(search_id)

        with Session(engine) as session:
            search = session.get(SavedSearch, search_id)
            assert search.last_run_at is not None

    def test_inactive_search_error(self, service, engine):
        search_id = _create_search(engine, is_active=False)

        result = service.run_search(search_id)

        assert "error" in result
        assert "inactive" in result["error"]

    def test_not_found(self, service):
        result = service.run_search(999)

        assert result["error"] == "Search 999 not found"

    def test_tradera_exception_handled(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="tradera")
        mock_tradera.search.side_effect = Exception("API error")

        result = service.run_search(search_id)

        assert result["count"] == 0

    def test_blocket_exception_handled(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="blocket")
        mock_blocket.search.side_effect = Exception("API error")

        result = service.run_search(search_id)

        assert result["count"] == 0

    def test_max_price_passed_to_tradera(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="tradera", max_price=500.0)
        mock_tradera.search.return_value = _make_search_result()

        service.run_search(search_id)

        mock_tradera.search.assert_called_once_with(query="antik byrå", max_price=500.0)

    def test_region_passed_to_blocket(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="blocket", region="stockholm")
        mock_blocket.search.return_value = _make_search_result()

        service.run_search(search_id)

        mock_blocket.search.assert_called_once_with(query="antik byrå", region="stockholm")

    def test_category_passed_to_tradera(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="tradera", category="123")
        mock_tradera.search.return_value = _make_search_result()

        service.run_search(search_id)

        mock_tradera.search.assert_called_once_with(query="antik byrå", category=123)

    def test_category_passed_to_blocket(self, service, engine, mock_tradera, mock_blocket):
        search_id = _create_search(engine, platform="blocket", category="möbler")
        mock_blocket.search.return_value = _make_search_result()

        service.run_search(search_id)

        mock_blocket.search.assert_called_once_with(query="antik byrå", category="möbler")


class TestRunAllSearches:
    def test_runs_all_active(self, service, engine, mock_tradera, mock_blocket):
        _create_search(engine, query="byrå", platform="tradera")
        _create_search(engine, query="lampa", platform="tradera")
        mock_tradera.search.return_value = _make_search_result(_tradera_item(id=1))

        result = service.run_all_searches()

        assert len(result["results"]) == 2
        assert result["total_new"] == 2

    def test_skips_inactive(self, service, engine, mock_tradera, mock_blocket):
        _create_search(engine, query="active", platform="tradera")
        _create_search(engine, query="inactive", platform="tradera", is_active=False)
        mock_tradera.search.return_value = _make_search_result(_tradera_item(id=1))

        result = service.run_all_searches()

        assert len(result["results"]) == 1
        assert result["results"][0]["query"] == "active"

    def test_no_searches(self, service):
        result = service.run_all_searches()

        assert result["total_new"] == 0
        assert result["results"] == []

    def test_notification_created(self, service, engine, mock_tradera, mock_blocket):
        _create_search(engine, platform="tradera")
        mock_tradera.search.return_value = _make_search_result(_tradera_item(id=1))

        service.run_all_searches()

        with Session(engine) as session:
            notifications = session.query(Notification).filter_by(type="scout_digest").all()
            assert len(notifications) == 1

    def test_no_notification_when_no_new_items(self, service, engine, mock_tradera, mock_blocket):
        _create_search(engine, platform="tradera")
        mock_tradera.search.return_value = _make_search_result()

        service.run_all_searches()

        with Session(engine) as session:
            notifications = session.query(Notification).filter_by(type="scout_digest").all()
            assert len(notifications) == 0

    def test_digest_format(self, service, engine, mock_tradera, mock_blocket):
        _create_search(engine, query="byrå", platform="tradera")
        mock_tradera.search.return_value = _make_search_result(
            _tradera_item(id=1, title="Fin byrå", price=500)
        )

        result = service.run_all_searches()

        assert "Dagens scoutrapport" in result["digest"]
        assert "byrå" in result["digest"]
        assert "Fin byrå" in result["digest"]


class TestFormatDigest:
    def test_empty_results(self, service):
        digest = service._format_digest([])

        assert digest == "Inga nya fynd idag."

    def test_all_zero_count(self, service):
        results = [{"query": "test", "count": 0, "new_items": []}]
        digest = service._format_digest(results)

        assert digest == "Inga nya fynd idag."

    def test_price_formatting(self, service):
        results = [
            {
                "query": "byrå",
                "count": 1,
                "new_items": [
                    {"platform": "tradera", "title": "Byrå", "price": 1500.0, "url": ""}
                ],
            }
        ]
        digest = service._format_digest(results)

        assert "1500 kr" in digest

    def test_truncation_at_5_items(self, service):
        items = [
            {"platform": "tradera", "title": f"Item {i}", "price": 100 * i, "url": ""}
            for i in range(8)
        ]
        results = [{"query": "test", "count": 8, "new_items": items}]
        digest = service._format_digest(results)

        assert "...och 3 till" in digest

    def test_no_price(self, service):
        results = [
            {
                "query": "test",
                "count": 1,
                "new_items": [{"platform": "tradera", "title": "Sak", "price": None, "url": ""}],
            }
        ]
        digest = service._format_digest(results)

        assert "kr" not in digest
        assert "Sak" in digest
