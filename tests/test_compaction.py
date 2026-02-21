"""Tests for context compaction (#58)."""

from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from storebot.agent import Agent, _detect_categories, _parse_category_tag
from storebot.db import Base, ConversationMessage
from storebot.tools.conversation import ConversationService


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _make_settings(**overrides):
    settings = MagicMock()
    settings.claude_api_key = "test"
    settings.claude_model = "claude-sonnet-4-6"
    settings.claude_max_tokens = 16000
    settings.claude_thinking_budget = 0
    settings.tradera_app_id = "1"
    settings.tradera_app_key = "k"
    settings.tradera_sandbox = True
    settings.tradera_user_id = None
    settings.tradera_user_token = None
    settings.postnord_api_key = None
    settings.compact_threshold = 20
    settings.compact_keep_recent = 6
    settings.claude_model_compact = "claude-haiku-3-5-20241022"
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_messages(count):
    """Create a list of alternating user/assistant messages."""
    msgs = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}"})
    return msgs


class TestCompactHistory:
    def test_below_threshold_returns_unchanged(self, engine):
        """10 messages, threshold=20 → same list returned."""
        settings = _make_settings(compact_threshold=20)
        agent = Agent(settings=settings, engine=engine)

        messages = _make_messages(10)
        result = agent.compact_history(messages)
        assert result is messages  # same object

    def test_above_threshold_summarizes(self, engine):
        """Mock Haiku call, verify summary + recent structure."""
        settings = _make_settings(compact_threshold=10, compact_keep_recent=4)
        agent = Agent(settings=settings, engine=engine)

        messages = _make_messages(14)  # 14 > 10 threshold

        summary_block = MagicMock()
        summary_block.type = "text"
        summary_block.text = "Sammanfattning: diskuterade produkter och priser."

        mock_response = MagicMock()
        mock_response.content = [summary_block]

        with patch.object(agent.client.messages, "create", return_value=mock_response):
            result = agent.compact_history(messages)

        # Should be: 1 summary + 4 recent = 5 messages
        assert result is not messages
        assert len(result) == 5
        assert "[Sammanfattning av tidigare konversation]" in result[0]["content"]

    def test_preserves_recent_messages(self, engine):
        """Last N messages kept verbatim."""
        settings = _make_settings(compact_threshold=10, compact_keep_recent=4)
        agent = Agent(settings=settings, engine=engine)

        messages = _make_messages(14)

        summary_block = MagicMock()
        summary_block.type = "text"
        summary_block.text = "Sammanfattning."

        mock_response = MagicMock()
        mock_response.content = [summary_block]

        with patch.object(agent.client.messages, "create", return_value=mock_response):
            result = agent.compact_history(messages)

        # Last 4 messages preserved
        assert result[-4:] == messages[-4:]

    def test_summary_has_prefix(self, engine):
        """Verify [Sammanfattning av tidigare konversation] prefix."""
        settings = _make_settings(compact_threshold=10, compact_keep_recent=4)
        agent = Agent(settings=settings, engine=engine)

        messages = _make_messages(14)

        summary_block = MagicMock()
        summary_block.type = "text"
        summary_block.text = "En sammanfattning."

        mock_response = MagicMock()
        mock_response.content = [summary_block]

        with patch.object(agent.client.messages, "create", return_value=mock_response):
            result = agent.compact_history(messages)

        assert result[0]["content"].startswith("[Sammanfattning av tidigare konversation]")

    def test_api_failure_returns_original(self, engine):
        """API error → original list (same object) returned."""
        settings = _make_settings(compact_threshold=10, compact_keep_recent=4)
        agent = Agent(settings=settings, engine=engine)

        messages = _make_messages(14)

        with patch.object(agent.client.messages, "create", side_effect=Exception("API error")):
            result = agent.compact_history(messages)

        assert result is messages

    def test_empty_summary_returns_original(self, engine):
        """Empty response → original list (same object) returned."""
        settings = _make_settings(compact_threshold=10, compact_keep_recent=4)
        agent = Agent(settings=settings, engine=engine)

        messages = _make_messages(14)

        empty_block = MagicMock()
        empty_block.type = "text"
        empty_block.text = ""

        mock_response = MagicMock()
        mock_response.content = [empty_block]

        with patch.object(agent.client.messages, "create", return_value=mock_response):
            result = agent.compact_history(messages)

        assert result is messages

    def test_trims_orphaned_tool_results_in_recent(self, engine):
        """Orphaned tool_results cleaned from recent window."""
        settings = _make_settings(compact_threshold=6, compact_keep_recent=3)
        agent = Agent(settings=settings, engine=engine)

        messages = [
            {"role": "user", "content": "Message 0"},
            {"role": "assistant", "content": "Message 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Message 3"},
            {"role": "user", "content": "Message 4"},
            {"role": "assistant", "content": "Message 5"},
            # Recent window starts here — orphaned tool_result first
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "x", "content": "res"}],
            },
            {"role": "assistant", "content": "Message 7"},
            {"role": "user", "content": "Message 8"},
        ]

        summary_block = MagicMock()
        summary_block.type = "text"
        summary_block.text = "Sammanfattning."

        mock_response = MagicMock()
        mock_response.content = [summary_block]

        with patch.object(agent.client.messages, "create", return_value=mock_response):
            result = agent.compact_history(messages)

        # The orphaned tool_result should be trimmed
        # Result: summary + 2 non-orphaned messages
        assert result[0]["content"].startswith("[Sammanfattning")
        for msg in result[1:]:
            content = msg.get("content")
            if isinstance(content, list):
                assert not any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                )

    def test_tool_results_truncated_in_summary_input(self, engine):
        """Long tool results truncated to 200 chars in summary input."""
        settings = _make_settings(compact_threshold=4, compact_keep_recent=2)
        agent = Agent(settings=settings, engine=engine)

        long_result = "x" * 500
        messages = [
            {"role": "user", "content": "Message 0"},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": long_result}],
            },
            {"role": "assistant", "content": "Message 2"},
            {"role": "user", "content": "Message 3"},
            {"role": "assistant", "content": "Message 4"},
        ]

        captured_messages = []

        def capture_create(**kwargs):
            captured_messages.append(kwargs["messages"][0]["content"])
            summary_block = MagicMock()
            summary_block.type = "text"
            summary_block.text = "Sammanfattning."
            resp = MagicMock()
            resp.content = [summary_block]
            return resp

        with patch.object(agent.client.messages, "create", side_effect=capture_create):
            agent.compact_history(messages)

        # The captured input should contain truncated version
        input_text = captured_messages[0]
        assert "..." in input_text
        # Should not contain the full 500-char string
        assert long_result not in input_text

    def test_uses_compact_model(self, engine):
        """Verify claude_model_compact is used, not main model."""
        settings = _make_settings(
            compact_threshold=4,
            compact_keep_recent=2,
            claude_model_compact="claude-haiku-3-5-20241022",
        )
        agent = Agent(settings=settings, engine=engine)

        messages = _make_messages(6)

        summary_block = MagicMock()
        summary_block.type = "text"
        summary_block.text = "Sammanfattning."

        mock_response = MagicMock()
        mock_response.content = [summary_block]

        with patch.object(agent.client.messages, "create", return_value=mock_response) as mock:
            agent.compact_history(messages)

            call_kwargs = mock.call_args[1]
            assert call_kwargs["model"] == "claude-haiku-3-5-20241022"

    def test_compaction_embeds_tool_categories(self, engine):
        """Categories from tool_use blocks in old messages are embedded in summary."""
        settings = _make_settings(compact_threshold=4, compact_keep_recent=2)
        agent = Agent(settings=settings, engine=engine)

        messages = [
            {"role": "user", "content": "Publicera annons 2"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "update_draft_listing", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
            },
            {"role": "assistant", "content": "Klart!"},
            {"role": "user", "content": "Tack"},
            {"role": "assistant", "content": "Varsågod"},
        ]

        summary_block = MagicMock()
        summary_block.type = "text"
        summary_block.text = "Användaren publicerade en annons."

        mock_response = MagicMock()
        mock_response.content = [summary_block]

        with patch.object(agent.client.messages, "create", return_value=mock_response):
            result = agent.compact_history(messages)

        summary_content = result[0]["content"]
        assert "[Aktiva kategorier: listing]" in summary_content

    def test_detect_categories_reads_compacted_tag(self, engine):
        """_detect_categories restores categories from compacted summary tag."""
        messages = [
            {
                "role": "user",
                "content": (
                    "[Sammanfattning av tidigare konversation]\n\n"
                    "Diskuterade annonser.\n\n"
                    "[Aktiva kategorier: listing, order]"
                ),
            },
            {"role": "user", "content": "Vad är status?"},
        ]
        cats = _detect_categories(messages, set())
        assert "listing" in cats
        assert "order" in cats
        assert "core" in cats

    def test_detect_categories_ignores_invalid_tags(self, engine):
        """Invalid category names in the tag are ignored."""
        messages = [
            {
                "role": "user",
                "content": (
                    "[Sammanfattning av tidigare konversation]\n\n"
                    "Sammanfattning.\n\n"
                    "[Aktiva kategorier: listing, bogus_category]"
                ),
            },
        ]
        cats = _detect_categories(messages, set())
        assert "listing" in cats
        assert "bogus_category" not in cats

    def test_compaction_preserves_categories_from_earlier_compaction(self, engine):
        """Categories from a previous compaction are carried forward."""
        settings = _make_settings(compact_threshold=4, compact_keep_recent=2)
        agent = Agent(settings=settings, engine=engine)

        messages = [
            {
                "role": "user",
                "content": (
                    "[Sammanfattning av tidigare konversation]\n\n"
                    "Tidigare: ordrar och annonser.\n\n"
                    "[Aktiva kategorier: listing, order]"
                ),
            },
            {"role": "assistant", "content": "OK"},
            {"role": "user", "content": "Bra"},
            {"role": "assistant", "content": "Fint"},
            {"role": "user", "content": "Nästa steg"},
            {"role": "assistant", "content": "Klart"},
        ]

        summary_block = MagicMock()
        summary_block.type = "text"
        summary_block.text = "Sammanfattning av ordrar."

        mock_response = MagicMock()
        mock_response.content = [summary_block]

        with patch.object(agent.client.messages, "create", return_value=mock_response):
            result = agent.compact_history(messages)

        summary_content = result[0]["content"]
        assert "listing" in summary_content
        assert "order" in summary_content

    def test_detect_categories_handles_malformed_tag(self, engine):
        """Malformed category tag (missing closing bracket) doesn't crash."""
        messages = [
            {
                "role": "user",
                "content": "[Aktiva kategorier: scout, analytics",
            },
        ]
        # Should not raise ValueError — malformed tag is silently ignored
        cats = _detect_categories(messages, set())
        assert "core" in cats
        # _parse_category_tag returns empty for malformed tag; keywords may
        # still match (e.g. "scout" is a keyword), but analytics is not
        assert "analytics" not in cats

    def test_parse_category_tag_empty_cases(self, engine):
        """_parse_category_tag handles edge cases gracefully."""
        assert _parse_category_tag("") == set()
        assert _parse_category_tag("no tag here") == set()
        assert _parse_category_tag(42) == set()
        assert _parse_category_tag("[Aktiva kategorier: listing]") == {"listing"}
        assert _parse_category_tag("[Aktiva kategorier: ") == set()  # no closing ]


class TestReplaceHistory:
    def test_replace_history_clears_and_saves(self, engine):
        """ConversationService.replace_history works correctly."""
        svc = ConversationService(engine=engine)

        # Save initial messages
        svc.save_messages(
            "chat1",
            [
                {"role": "user", "content": "old message 1"},
                {"role": "assistant", "content": "old response 1"},
            ],
        )

        # Replace with new messages
        svc.replace_history(
            "chat1",
            [
                {"role": "user", "content": "compacted summary"},
                {"role": "assistant", "content": "new response"},
            ],
        )

        with Session(engine) as session:
            rows = (
                session.query(ConversationMessage)
                .filter(ConversationMessage.chat_id == "chat1")
                .order_by(ConversationMessage.id)
                .all()
            )
            assert len(rows) == 2
            assert rows[0].content == "compacted summary"
            assert rows[1].content == "new response"

    def test_replace_history_preserves_image_paths(self, engine):
        """Image path extraction in replace_history."""
        import tempfile
        from pathlib import Path

        svc = ConversationService(engine=engine)

        # Create a temporary directory matching the expected path
        with tempfile.TemporaryDirectory() as tmp:
            photos_dir = Path(tmp) / "data" / "photos"
            photos_dir.mkdir(parents=True)

            # Patch _validate_image_paths to allow test paths
            with patch(
                "storebot.tools.conversation._validate_image_paths",
                return_value=[str(photos_dir / "test.jpg")],
            ):
                msg = {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": "abc",
                            },
                        },
                        {
                            "type": "text",
                            "text": f"Bild [Bildernas sökvägar: {photos_dir / 'test.jpg'}]",
                        },
                    ],
                }
                svc.replace_history("chat2", [msg])

            with Session(engine) as session:
                row = (
                    session.query(ConversationMessage)
                    .filter(ConversationMessage.chat_id == "chat2")
                    .first()
                )
                assert row is not None
                assert row.image_paths is not None
                assert len(row.image_paths) == 1
