from unittest.mock import MagicMock, patch

import pytest

from storebot.cli import _update_env_file, authorize_tradera
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


def _mock_token_response(user_id=42, token="my-token", expires="2027-06-01"):
    """Create a mock TraderaClient with a successful fetch_token response."""
    mock_client = MagicMock()
    mock_client.fetch_token.return_value = {
        "user_id": user_id,
        "token": token,
        "expires": expires,
    }
    return mock_client


class TestFetchToken:
    def test_fetch_token_success(self, tradera_client):
        response = MagicMock()
        response.UserId = 99999
        response.Token = "abc-token-xyz"
        response.ExpirationDate = "2027-01-01T00:00:00"
        tradera_client._public_client.service.FetchToken.return_value = response

        result = tradera_client.fetch_token("test-secret-key")

        assert result["user_id"] == 99999
        assert result["token"] == "abc-token-xyz"
        assert result["expires"] == "2027-01-01T00:00:00"

        call_kwargs = tradera_client._public_client.service.FetchToken.call_args.kwargs
        assert call_kwargs["UserId"] == 0
        assert call_kwargs["Token"] == "test-secret-key"

    def test_fetch_token_missing_fields(self, tradera_client):
        response = MagicMock()
        response.UserId = None
        response.Token = None
        response.ExpirationDate = None
        tradera_client._public_client.service.FetchToken.return_value = response

        result = tradera_client.fetch_token("test-secret-key")

        assert "error" in result

    def test_fetch_token_exception(self, tradera_client):
        tradera_client._public_client.service.FetchToken.side_effect = Exception("SOAP fault")

        result = tradera_client.fetch_token("test-secret-key")

        assert "error" in result
        assert "SOAP fault" in result["error"]


class TestAuthorizeTraderaCLI:
    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.Settings")
    def test_missing_app_id_exits(self, mock_settings_cls, mock_client_cls):
        mock_settings_cls.return_value = _mock_settings(tradera_app_id="")

        with pytest.raises(SystemExit) as exc_info:
            authorize_tradera()
        assert exc_info.value.code == 1

    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.Settings")
    def test_missing_public_key_exits(self, mock_settings_cls, mock_client_cls):
        mock_settings_cls.return_value = _mock_settings(tradera_public_key="")

        with pytest.raises(SystemExit) as exc_info:
            authorize_tradera()
        assert exc_info.value.code == 1

    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_successful_flow_saves_to_env(
        self, mock_input, mock_settings_cls, mock_client_cls, tmp_path, monkeypatch
    ):
        mock_settings_cls.return_value = _mock_settings()
        mock_client_cls.return_value = _mock_token_response()

        mock_input.side_effect = ["", "y"]

        env_file = tmp_path / ".env"
        env_file.write_text("TRADERA_USER_ID=\nTRADERA_USER_TOKEN=\n")
        monkeypatch.chdir(tmp_path)

        authorize_tradera()

        content = env_file.read_text()
        assert "TRADERA_USER_ID=42" in content
        assert "TRADERA_USER_TOKEN=my-token" in content

    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_successful_flow_no_save(self, mock_input, mock_settings_cls, mock_client_cls, capsys):
        mock_settings_cls.return_value = _mock_settings()
        mock_client_cls.return_value = _mock_token_response()

        mock_input.side_effect = ["", "n"]

        authorize_tradera()

        output = capsys.readouterr().out
        assert "TRADERA_USER_ID=42" in output
        assert "TRADERA_USER_TOKEN=my-token" in output

    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_fetch_token_error_exits(self, mock_input, mock_settings_cls, mock_client_cls):
        mock_settings_cls.return_value = _mock_settings()

        mock_client = MagicMock()
        mock_client.fetch_token.return_value = {"error": "Token not found"}
        mock_client_cls.return_value = mock_client

        mock_input.side_effect = [""]

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
