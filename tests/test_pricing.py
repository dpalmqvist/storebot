from unittest.mock import MagicMock, patch

import pytest

from storebot.tools.pricing import (
    PricingService,
    _compute_stats,
    _compute_suggested_range,
    _normalize_comparable,
)


@pytest.fixture
def tradera():
    return MagicMock()


@pytest.fixture
def blocket():
    return MagicMock()


@pytest.fixture
def service(tradera, blocket):
    return PricingService(tradera=tradera, blocket=blocket)


def _tradera_items():
    return [
        {"id": 1, "title": "Antik stol", "price": 800, "url": "https://tradera.com/1"},
        {"id": 2, "title": "Gammal stol", "price": 600, "url": "https://tradera.com/2"},
        {"id": 3, "title": "Pinnstol", "price": 400, "url": "https://tradera.com/3"},
    ]


def _blocket_items():
    return [
        {"id": "10", "title": "Stol retro", "price": 500, "url": "https://blocket.se/10"},
        {"id": "11", "title": "Köksstol", "price": 700, "url": "https://blocket.se/11"},
    ]


class TestPriceCheck:
    def test_combined_aggregation(self, service, tradera, blocket):
        tradera.search.return_value = {"total": 3, "items": _tradera_items()}
        blocket.search.return_value = {"total": 2, "items": _blocket_items()}

        result = service.price_check("stol")

        assert result["query"] == "stol"
        assert result["product_id"] is None
        assert result["tradera"]["count"] == 3
        assert result["blocket"]["count"] == 2
        assert result["combined_stats"]["count"] == 5
        assert len(result["comparables"]) == 5

    def test_tradera_error_degrades_gracefully(self, service, tradera, blocket):
        tradera.search.side_effect = Exception("SOAP timeout")
        blocket.search.return_value = {"total": 2, "items": _blocket_items()}

        result = service.price_check("stol")

        assert result["tradera"]["count"] == 0
        assert "error" in result["tradera"]
        assert result["blocket"]["count"] == 2
        assert result["combined_stats"]["count"] == 2

    def test_blocket_error_degrades_gracefully(self, service, tradera, blocket):
        tradera.search.return_value = {"total": 3, "items": _tradera_items()}
        blocket.search.side_effect = Exception("401 Unauthorized")

        result = service.price_check("stol")

        assert result["tradera"]["count"] == 3
        assert result["blocket"]["count"] == 0
        assert "error" in result["blocket"]
        assert result["combined_stats"]["count"] == 3

    def test_no_results_from_either(self, service, tradera, blocket):
        tradera.search.return_value = {"total": 0, "items": []}
        blocket.search.return_value = {"total": 0, "items": []}

        result = service.price_check("unicorn")

        assert result["combined_stats"]["count"] == 0
        assert result["suggested_range"] == {"low": 0, "high": 0}
        assert result["comparables"] == []

    def test_category_passed_to_tradera_as_int(self, service, tradera, blocket):
        tradera.search.return_value = {"total": 0, "items": []}
        blocket.search.return_value = {"total": 0, "items": []}

        service.price_check("stol", category="344")

        tradera.search.assert_called_once_with(
            query="stol", category=344, search_in_description=True
        )

    def test_category_passed_to_blocket_as_string(self, service, tradera, blocket):
        tradera.search.return_value = {"total": 0, "items": []}
        blocket.search.return_value = {"total": 0, "items": []}

        service.price_check("stol", category="0.78")

        blocket.search.assert_called_once_with(query="stol", category="0.78")

    def test_invalid_category_skipped_for_tradera(self, service, tradera, blocket):
        tradera.search.return_value = {"total": 0, "items": []}
        blocket.search.return_value = {"total": 0, "items": []}

        service.price_check("stol", category="not-a-number")

        # Tradera should be called without category since it can't convert
        tradera.search.assert_called_once_with(query="stol", search_in_description=True)
        # Blocket gets it as-is
        blocket.search.assert_called_once_with(query="stol", category="not-a-number")

    def test_zero_prices_excluded(self, service, tradera, blocket):
        items = [
            {"id": 1, "title": "Free item", "price": 0, "url": ""},
            {"id": 2, "title": "Paid item", "price": 500, "url": ""},
        ]
        tradera.search.return_value = {"total": 2, "items": items}
        blocket.search.return_value = {"total": 0, "items": []}

        result = service.price_check("test")

        assert result["combined_stats"]["count"] == 1
        assert result["combined_stats"]["min"] == 500

    def test_product_id_included_in_result(self, service, tradera, blocket):
        tradera.search.return_value = {"total": 0, "items": []}
        blocket.search.return_value = {"total": 0, "items": []}

        result = service.price_check("stol", product_id=42)

        assert result["product_id"] == 42


class TestComputeStats:
    def test_normal_prices(self):
        stats = _compute_stats([100, 200, 300, 400, 500])

        assert stats["min"] == 100
        assert stats["max"] == 500
        assert stats["median"] == 300
        assert stats["mean"] == 300.0
        assert stats["count"] == 5

    def test_empty_prices(self):
        stats = _compute_stats([])

        assert stats == {"min": 0, "max": 0, "median": 0, "mean": 0, "count": 0}

    def test_single_price(self):
        stats = _compute_stats([750])

        assert stats["min"] == 750
        assert stats["max"] == 750
        assert stats["median"] == 750
        assert stats["mean"] == 750.0
        assert stats["count"] == 1

    def test_mean_rounded(self):
        stats = _compute_stats([100, 200, 300])

        assert stats["mean"] == 200.0


class TestComputeSuggestedRange:
    def test_enough_items_uses_quartiles(self):
        # 4+ items: use 25th-75th percentile
        prices = [100, 200, 300, 400, 500, 600, 700, 800]
        result = _compute_suggested_range(prices)

        # Q1 = median of [100,200,300,400] = 250
        # Q3 = median of [500,600,700,800] = 650
        assert result["low"] == 250
        assert result["high"] == 650

    def test_fewer_than_4_items_uses_min_max(self):
        result = _compute_suggested_range([200, 500, 800])

        assert result["low"] == 200
        assert result["high"] == 800

    def test_empty_returns_zeros(self):
        result = _compute_suggested_range([])

        assert result == {"low": 0, "high": 0}

    def test_single_item(self):
        result = _compute_suggested_range([500])

        assert result["low"] == 500
        assert result["high"] == 500

    def test_exactly_four_items(self):
        prices = [100, 200, 300, 400]
        result = _compute_suggested_range(prices)

        # Q1 = median of [100,200] = 150
        # Q3 = median of [300,400] = 350
        assert result["low"] == 150
        assert result["high"] == 350


class TestNormalizeComparable:
    def test_tradera_item(self):
        item = {"id": 123, "title": "Byrå", "price": 1200, "url": "https://tradera.com/123"}
        result = _normalize_comparable(item, "tradera")

        assert result == {
            "source": "tradera",
            "id": "123",
            "title": "Byrå",
            "price": 1200,
            "url": "https://tradera.com/123",
        }

    def test_blocket_item(self):
        item = {"id": "456", "title": "Lampa", "price": 350, "url": "https://blocket.se/456"}
        result = _normalize_comparable(item, "blocket")

        assert result == {
            "source": "blocket",
            "id": "456",
            "title": "Lampa",
            "price": 350,
            "url": "https://blocket.se/456",
        }

    def test_missing_fields_get_defaults(self):
        result = _normalize_comparable({}, "tradera")

        assert result == {
            "source": "tradera",
            "id": "",
            "title": "",
            "price": 0,
            "url": "",
        }


class TestAgentActionLogging:
    def test_logs_when_product_id_provided(self, tradera, blocket):
        engine = MagicMock()
        service = PricingService(tradera=tradera, blocket=blocket, engine=engine)
        tradera.search.return_value = {"total": 0, "items": []}
        blocket.search.return_value = {"total": 0, "items": []}

        with patch("storebot.tools.pricing.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            service.price_check("stol", product_id=42)

            mock_session.add.assert_called_once()
            action = mock_session.add.call_args[0][0]
            assert action.agent_name == "pricing"
            assert action.action_type == "price_check"
            assert action.product_id == 42
            mock_session.commit.assert_called_once()

    def test_no_logging_without_product_id(self, service, tradera, blocket):
        tradera.search.return_value = {"total": 0, "items": []}
        blocket.search.return_value = {"total": 0, "items": []}

        with patch("storebot.tools.pricing.Session") as mock_session_cls:
            service.price_check("stol")

            mock_session_cls.assert_not_called()

    def test_no_logging_without_engine(self, tradera, blocket):
        service = PricingService(tradera=tradera, blocket=blocket, engine=None)
        tradera.search.return_value = {"total": 0, "items": []}
        blocket.search.return_value = {"total": 0, "items": []}

        with patch("storebot.tools.pricing.Session") as mock_session_cls:
            service.price_check("stol", product_id=42)

            mock_session_cls.assert_not_called()

    def test_logging_failure_does_not_break_price_check(self, tradera, blocket):
        engine = MagicMock()
        service = PricingService(tradera=tradera, blocket=blocket, engine=engine)
        tradera.search.return_value = {"total": 1, "items": _tradera_items()[:1]}
        blocket.search.return_value = {"total": 0, "items": []}

        with patch("storebot.tools.pricing.Session") as mock_session_cls:
            mock_session_cls.side_effect = Exception("DB error")

            result = service.price_check("stol", product_id=42)

            # Should still return valid result despite logging failure
            assert result["tradera"]["count"] == 1
            assert result["product_id"] == 42


class TestPriceCheckNoBlocket:
    def test_blocket_none(self, tradera):
        service = PricingService(tradera=tradera, blocket=None)
        tradera.search.return_value = {"total": 1, "items": _tradera_items()[:1]}

        result = service.price_check("stol")
        assert result["blocket"]["count"] == 0
        assert "error" in result["blocket"]
