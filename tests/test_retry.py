from unittest.mock import MagicMock, patch

import pytest
import requests
import zeep.exceptions

from storebot.retry import _is_retryable, retry_on_transient


class TestIsRetryable:
    def test_connection_error_is_retryable(self):
        assert _is_retryable(requests.ConnectionError("refused")) is True

    def test_timeout_is_retryable(self):
        assert _is_retryable(requests.Timeout("timed out")) is True

    def test_transport_error_5xx_is_retryable(self):
        exc = zeep.exceptions.TransportError(status_code=503, message="Service Unavailable")
        assert _is_retryable(exc) is True

    def test_transport_error_500_is_retryable(self):
        exc = zeep.exceptions.TransportError(status_code=500, message="Internal Server Error")
        assert _is_retryable(exc) is True

    def test_transport_error_401_not_retryable(self):
        exc = zeep.exceptions.TransportError(status_code=401, message="Unauthorized")
        assert _is_retryable(exc) is False

    def test_transport_error_403_not_retryable(self):
        exc = zeep.exceptions.TransportError(status_code=403, message="Forbidden")
        assert _is_retryable(exc) is False

    def test_transport_error_400_not_retryable(self):
        exc = zeep.exceptions.TransportError(status_code=400, message="Bad Request")
        assert _is_retryable(exc) is False

    def test_http_error_5xx_is_retryable(self):
        resp = MagicMock()
        resp.status_code = 502
        exc = requests.HTTPError(response=resp)
        assert _is_retryable(exc) is True

    def test_http_error_404_not_retryable(self):
        resp = MagicMock()
        resp.status_code = 404
        exc = requests.HTTPError(response=resp)
        assert _is_retryable(exc) is False

    def test_value_error_not_retryable(self):
        assert _is_retryable(ValueError("bad value")) is False

    def test_generic_exception_not_retryable(self):
        assert _is_retryable(Exception("something")) is False


class TestRetryDecorator:
    @patch("storebot.retry.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep):
        call_count = 0

        @retry_on_transient(max_retries=3, base_delay=1.0)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise requests.ConnectionError("refused")
            return "success"

        result = flaky()
        assert result == "success"
        assert call_count == 3
        assert mock_sleep.call_count == 2
        # Exponential backoff: 1s, 2s
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("storebot.retry.time.sleep")
    def test_retries_on_timeout(self, mock_sleep):
        call_count = 0

        @retry_on_transient(max_retries=2, base_delay=0.5)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise requests.Timeout("timed out")
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count == 2

    @patch("storebot.retry.time.sleep")
    def test_no_retry_on_value_error(self, mock_sleep):
        @retry_on_transient(max_retries=3)
        def bad():
            raise ValueError("bad")

        with pytest.raises(ValueError, match="bad"):
            bad()
        mock_sleep.assert_not_called()

    @patch("storebot.retry.time.sleep")
    def test_no_retry_on_401_transport_error(self, mock_sleep):
        @retry_on_transient(max_retries=3)
        def unauthorized():
            raise zeep.exceptions.TransportError(status_code=401, message="Unauthorized")

        with pytest.raises(zeep.exceptions.TransportError):
            unauthorized()
        mock_sleep.assert_not_called()

    @patch("storebot.retry.time.sleep")
    def test_exhausts_retries_and_raises(self, mock_sleep):
        @retry_on_transient(max_retries=2, base_delay=1.0)
        def always_fails():
            raise requests.ConnectionError("refused")

        with pytest.raises(requests.ConnectionError, match="refused"):
            always_fails()
        assert mock_sleep.call_count == 2

    @patch("storebot.retry.time.sleep")
    def test_succeeds_first_try_no_sleep(self, mock_sleep):
        @retry_on_transient(max_retries=3)
        def works():
            return 42

        assert works() == 42
        mock_sleep.assert_not_called()

    @patch("storebot.retry.time.sleep")
    def test_exponential_backoff_values(self, mock_sleep):
        call_count = 0

        @retry_on_transient(max_retries=3, base_delay=1.0)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise requests.ConnectionError("refused")
            return "ok"

        result = flaky()
        assert result == "ok"
        # Delays: 1*2^0=1, 1*2^1=2, 1*2^2=4
        assert mock_sleep.call_args_list[0][0][0] == 1.0
        assert mock_sleep.call_args_list[1][0][0] == 2.0
        assert mock_sleep.call_args_list[2][0][0] == 4.0

    @patch("storebot.retry.time.sleep")
    def test_retries_on_5xx_transport_error(self, mock_sleep):
        call_count = 0

        @retry_on_transient(max_retries=2)
        def flaky_soap():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise zeep.exceptions.TransportError(
                    status_code=503, message="Service Unavailable"
                )
            return "ok"

        assert flaky_soap() == "ok"
        assert call_count == 2
