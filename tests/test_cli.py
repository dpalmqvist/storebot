from unittest.mock import MagicMock, patch

import pytest

from storebot.cli import _parse_redirect_url, _update_env_file, authorize_tradera
from storebot.tools.tradera import TraderaClient


@pytest.fixture
def tradera_client():
    with patch("storebot.tools.tradera.zeep.Client"):
        c = TraderaClient(
            app_id="12345",
            app_key="testkey",
            sandbox=True,
        )
        c._public_client = MagicMock()
        yield c


def _mock_settings(**overrides):
    """Create a mock Settings with standard Tradera fields."""
    settings = MagicMock()
    settings.tradera_app_id = overrides.get("tradera_app_id", "123")
    settings.tradera_app_key = overrides.get("tradera_app_key", "key")
    settings.tradera_public_key = overrides.get("tradera_public_key", "pkey")
    settings.tradera_sandbox = overrides.get("tradera_sandbox", True)
    return settings


class TestFetchToken:
    def test_fetch_token_success(self, tradera_client):
        response = MagicMock()
        response.AuthToken = "abc-token-xyz"
        response.HardExpirationTime = "2027-01-01T00:00:00"
        tradera_client._public_client.service.FetchToken.return_value = response
        tradera_client._public_client.plugins = []

        result = tradera_client.fetch_token("test-secret-key")

        assert result["token"] == "abc-token-xyz"
        assert result["expires"] == "2027-01-01T00:00:00"

        call_kwargs = tradera_client._public_client.service.FetchToken.call_args.kwargs
        assert call_kwargs["userId"] == 0
        assert call_kwargs["secretKey"] == "test-secret-key"

    def test_fetch_token_missing_fields(self, tradera_client):
        response = MagicMock()
        response.AuthToken = None
        response.HardExpirationTime = None
        tradera_client._public_client.service.FetchToken.return_value = response
        tradera_client._public_client.plugins = []

        result = tradera_client.fetch_token("test-secret-key")

        assert "error" in result

    def test_fetch_token_exception(self, tradera_client):
        tradera_client._public_client.service.FetchToken.side_effect = Exception("SOAP fault")
        tradera_client._public_client.plugins = []

        result = tradera_client.fetch_token("test-secret-key")

        assert "error" in result
        assert "SOAP fault" in result["error"]


class TestParseRedirectUrl:
    def test_parse_full_url(self):
        url = (
            "http://localhost:8080/auth/accept"
            "?userId=1943555"
            "&token=fe67c960-9a2a-4c4d-80de-afc42dfcf674"
            "&exp=2027-08-13T16%3a58%3a59.6840692%2b02%3a00"
        )
        result = _parse_redirect_url(url)

        assert result["token"] == "fe67c960-9a2a-4c4d-80de-afc42dfcf674"
        assert result["user_id"] == "1943555"
        assert "2027-08-13" in result["expires"]

    def test_parse_token_only(self):
        url = "http://localhost:8080/auth/accept?token=abc-def"
        result = _parse_redirect_url(url)

        assert result["token"] == "abc-def"
        assert "user_id" not in result
        assert "expires" not in result

    def test_missing_token_returns_error(self):
        url = "http://localhost:8080/auth/accept?userId=123"
        result = _parse_redirect_url(url)

        assert "error" in result

    def test_handles_whitespace(self):
        url = "  http://localhost:8080/auth/accept?token=abc  "
        result = _parse_redirect_url(url)

        assert result["token"] == "abc"


class TestAuthorizeTraderaCLI:
    @patch("storebot.cli.Settings")
    def test_missing_app_id_exits(self, mock_settings_cls):
        mock_settings_cls.return_value = _mock_settings(tradera_app_id="")

        with pytest.raises(SystemExit) as exc_info:
            authorize_tradera()
        assert exc_info.value.code == 1

    @patch("storebot.cli.Settings")
    def test_missing_public_key_exits(self, mock_settings_cls):
        mock_settings_cls.return_value = _mock_settings(tradera_public_key="")

        with pytest.raises(SystemExit) as exc_info:
            authorize_tradera()
        assert exc_info.value.code == 1

    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_successful_flow_saves_to_env(
        self, mock_input, mock_settings_cls, tmp_path, monkeypatch
    ):
        mock_settings_cls.return_value = _mock_settings()
        redirect = "http://localhost:8080/auth/accept?userId=999&token=my-token&exp=2027-06-01"
        mock_input.side_effect = [redirect, "y"]

        env_file = tmp_path / ".env"
        env_file.write_text("TRADERA_USER_TOKEN=\n")
        monkeypatch.chdir(tmp_path)

        authorize_tradera()

        content = env_file.read_text()
        assert "TRADERA_USER_TOKEN=my-token" in content
        assert "TRADERA_USER_ID=999" in content

    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_successful_flow_no_save(self, mock_input, mock_settings_cls, capsys):
        mock_settings_cls.return_value = _mock_settings()
        redirect = "http://localhost:8080/auth/accept?userId=999&token=my-token&exp=2027-06-01"
        mock_input.side_effect = [redirect, "n"]

        authorize_tradera()

        output = capsys.readouterr().out
        assert "TRADERA_USER_TOKEN=my-token" in output
        assert "TRADERA_USER_ID=999" in output

    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_empty_url_exits(self, mock_input, mock_settings_cls):
        mock_settings_cls.return_value = _mock_settings()
        mock_input.side_effect = [""]

        with pytest.raises(SystemExit) as exc_info:
            authorize_tradera()
        assert exc_info.value.code == 1

    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_url_without_token_exits(self, mock_input, mock_settings_cls):
        mock_settings_cls.return_value = _mock_settings()
        mock_input.side_effect = ["http://localhost:8080/auth/accept?userId=123"]

        with pytest.raises(SystemExit) as exc_info:
            authorize_tradera()
        assert exc_info.value.code == 1


class TestUpdateEnvFile:
    def test_update_existing_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=old\nBAR=baz\n")

        _update_env_file(env_file, "FOO", "new")

        content = env_file.read_text()
        assert "FOO=new" in content
        assert "BAR=baz" in content
        assert "FOO=old" not in content

    def test_update_value_with_backslash(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TOKEN=old\n")

        _update_env_file(env_file, "TOKEN", r"abc\1def")

        content = env_file.read_text()
        assert r"TOKEN=abc\1def" in content

    def test_append_new_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n")

        _update_env_file(env_file, "NEW_KEY", "value")

        content = env_file.read_text()
        assert "FOO=bar" in content
        assert "NEW_KEY=value" in content

    def test_create_file_if_missing(self, tmp_path):
        env_file = tmp_path / ".env"

        _update_env_file(env_file, "KEY", "val")

        assert env_file.exists()
        assert env_file.read_text() == "KEY=val\n"
