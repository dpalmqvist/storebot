from unittest.mock import MagicMock, patch

import pytest

from storebot.cli import (
    _extract_json_array,
    _parse_redirect_url,
    _update_env_file,
    authorize_tradera,
    generate_category_descriptions,
    sync_categories,
)
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

        assert result["user_id"] == "1943555"
        assert result["token"] == "fe67c960-9a2a-4c4d-80de-afc42dfcf674"
        assert "2027-08-13" in result["expires"]

    def test_no_user_id(self):
        url = "http://localhost:8080/auth/accept?token=abc-def"
        result = _parse_redirect_url(url)

        assert result["user_id"] is None
        assert result["token"] == "abc-def"

    def test_user_id_only(self):
        url = "http://localhost:8080/auth/accept?userId=123"
        result = _parse_redirect_url(url)

        assert result["user_id"] == "123"
        assert "token" not in result

    def test_handles_whitespace(self):
        url = "  http://localhost:8080/auth/accept?userId=42&token=abc  "
        result = _parse_redirect_url(url)

        assert result["user_id"] == "42"
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

    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_successful_flow_saves_to_env(
        self, mock_input, mock_settings_cls, mock_tradera_cls, tmp_path, monkeypatch
    ):
        mock_settings_cls.return_value = _mock_settings()
        mock_tradera = MagicMock()
        mock_tradera.fetch_token.return_value = {
            "token": "fetched-real-token",
            "expires": "2027-06-01",
        }
        mock_tradera_cls.return_value = mock_tradera

        redirect = "http://localhost:8080/auth/accept?userId=999"
        mock_input.side_effect = [redirect, "y"]

        env_file = tmp_path / ".env"
        env_file.write_text("TRADERA_USER_TOKEN=\n")
        monkeypatch.chdir(tmp_path)

        authorize_tradera()

        content = env_file.read_text()
        assert "TRADERA_USER_TOKEN=fetched-real-token" in content
        assert "TRADERA_USER_ID=999" in content
        mock_tradera.fetch_token.assert_called_once()

    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_successful_flow_no_save(
        self, mock_input, mock_settings_cls, mock_tradera_cls, capsys
    ):
        mock_settings_cls.return_value = _mock_settings()
        mock_tradera = MagicMock()
        mock_tradera.fetch_token.return_value = {
            "token": "fetched-real-token",
            "expires": "2027-06-01",
        }
        mock_tradera_cls.return_value = mock_tradera

        redirect = "http://localhost:8080/auth/accept?userId=999"
        mock_input.side_effect = [redirect, "n"]

        authorize_tradera()

        output = capsys.readouterr().out
        # "Not saved" path prints full token for manual copy
        assert "TRADERA_USER_TOKEN=fetched-real-token" in output
        assert "TRADERA_USER_ID=999" in output

    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_empty_url_exits(self, mock_input, mock_settings_cls):
        mock_settings_cls.return_value = _mock_settings()
        mock_input.side_effect = [""]

        with pytest.raises(SystemExit) as exc_info:
            authorize_tradera()
        assert exc_info.value.code == 1

    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_fallback_to_redirect_token(
        self, mock_input, mock_settings_cls, mock_tradera_cls, tmp_path, monkeypatch
    ):
        """When FetchToken fails but redirect URL has a token, use that."""
        mock_settings_cls.return_value = _mock_settings()
        mock_tradera = MagicMock()
        mock_tradera.fetch_token.return_value = {
            "error": "FetchToken response missing AuthToken",
        }
        mock_tradera_cls.return_value = mock_tradera

        redirect = "http://localhost:8080/auth/accept?userId=999&token=url-token"
        mock_input.side_effect = [redirect, "y"]

        env_file = tmp_path / ".env"
        env_file.write_text("TRADERA_USER_TOKEN=\n")
        monkeypatch.chdir(tmp_path)

        authorize_tradera()

        content = env_file.read_text()
        assert "TRADERA_USER_TOKEN=url-token" in content
        assert "TRADERA_USER_ID=999" in content

    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.Settings")
    @patch("builtins.input")
    def test_fetch_token_error_no_fallback_exits(
        self, mock_input, mock_settings_cls, mock_tradera_cls
    ):
        """When FetchToken fails and redirect URL has no token, exit."""
        mock_settings_cls.return_value = _mock_settings()
        mock_tradera = MagicMock()
        mock_tradera.fetch_token.return_value = {"error": "Token not found"}
        mock_tradera_cls.return_value = mock_tradera

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


class TestExtractJsonArray:
    def test_plain_json(self):
        assert _extract_json_array('[{"id": 1}]') == '[{"id": 1}]'

    def test_markdown_code_block(self):
        text = '```json\n[{"id": 1}]\n```'
        assert _extract_json_array(text) == '[{"id": 1}]'

    def test_prose_prefix(self):
        text = 'Here is the JSON:\n[{"id": 1}]'
        assert _extract_json_array(text) == '[{"id": 1}]'

    def test_no_array(self):
        assert _extract_json_array("no json here") == "no json here"


class TestGenerateCategoryDescriptions:
    def test_generates_descriptions(self, engine):
        from datetime import UTC, datetime

        from sqlalchemy.orm import Session

        from storebot.db import TraderaCategory

        with Session(engine) as session:
            session.add(
                TraderaCategory(
                    tradera_id=10,
                    name="Möbler",
                    path="Möbler",
                    depth=0,
                    synced_at=datetime.now(UTC),
                )
            )
            session.add(
                TraderaCategory(
                    tradera_id=20,
                    name="Soffor",
                    path="Möbler > Soffor",
                    depth=1,
                    synced_at=datetime.now(UTC),
                )
            )
            session.commit()

        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = '[{"tradera_id": 10, "description": "Alla typer av möbler"}, {"tradera_id": 20, "description": "Soffor och sittmöbler"}]'
        mock_response.content = [mock_block]

        with patch("storebot.cli.anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            count = generate_category_descriptions(engine, "test-key", "haiku")

        assert count == 2
        with Session(engine) as session:
            cat = session.query(TraderaCategory).filter_by(tradera_id=10).one()
            assert cat.description == "Alla typer av möbler"

    def test_skips_already_described(self, engine):
        from datetime import UTC, datetime

        from sqlalchemy.orm import Session

        from storebot.db import TraderaCategory

        with Session(engine) as session:
            session.add(
                TraderaCategory(
                    tradera_id=10,
                    name="Möbler",
                    path="Möbler",
                    depth=0,
                    description="Already has description",
                    synced_at=datetime.now(UTC),
                )
            )
            session.commit()

        count = generate_category_descriptions(engine, "test-key", "haiku")
        assert count == 0


class TestSyncCategories:
    @patch("storebot.cli.Settings")
    def test_missing_app_id_exits(self, mock_settings_cls):
        mock_settings_cls.return_value = _mock_settings(tradera_app_id="")

        with pytest.raises(SystemExit) as exc_info:
            sync_categories()
        assert exc_info.value.code == 1

    @patch("storebot.cli.Settings")
    def test_missing_app_key_exits(self, mock_settings_cls):
        mock_settings_cls.return_value = _mock_settings(tradera_app_key="")

        with pytest.raises(SystemExit) as exc_info:
            sync_categories()
        assert exc_info.value.code == 1

    @patch("storebot.cli.Settings")
    def test_missing_claude_key_exits(self, mock_settings_cls):
        settings = _mock_settings()
        settings.claude_api_key = ""
        mock_settings_cls.return_value = settings

        with pytest.raises(SystemExit) as exc_info:
            sync_categories()
        assert exc_info.value.code == 1

    @patch("storebot.cli.generate_category_descriptions")
    @patch("storebot.cli.TraderaClient")
    @patch("storebot.cli.init_db")
    @patch("storebot.cli.Settings")
    def test_successful_sync(
        self, mock_settings_cls, mock_init_db, mock_tradera_cls, mock_gen_desc, capsys
    ):
        settings = _mock_settings()
        settings.claude_api_key = "test-key"
        settings.claude_model_simple = ""
        settings.claude_model_compact = "claude-haiku-3-5-20241022"
        mock_settings_cls.return_value = settings

        mock_engine = MagicMock()
        mock_init_db.return_value = mock_engine

        mock_tradera = MagicMock()
        mock_tradera.sync_categories_to_db.return_value = 150
        mock_tradera_cls.return_value = mock_tradera

        mock_gen_desc.return_value = 120

        sync_categories()

        output = capsys.readouterr().out
        assert "150 categories" in output
        assert "120 descriptions" in output
        mock_tradera.sync_categories_to_db.assert_called_once_with(mock_engine)
        mock_gen_desc.assert_called_once_with(mock_engine, "test-key", "claude-haiku-3-5-20241022")
