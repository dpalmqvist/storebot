from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import sqlalchemy as sa

from storebot.db import ConversationMessage
from storebot.tools.conversation import (
    ConversationService,
    _extract_image_paths,
    _serialize_content,
    _validate_image_paths,
)


def test_save_and_load_text_messages(engine):
    """Text messages survive a save/load round-trip."""
    svc = ConversationService(engine)

    messages = [
        {"role": "user", "content": "Hej, vad kostar stolen?"},
        {"role": "assistant", "content": "Jag kollar priset åt dig."},
    ]
    svc.save_messages("chat1", messages)

    history = svc.load_history("chat1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hej, vad kostar stolen?"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Jag kollar priset åt dig."


def test_max_history_messages_limit(engine):
    """Only the most recent N messages are returned."""
    svc = ConversationService(engine, max_messages=3)

    messages = [{"role": "user", "content": f"Message {i}"} for i in range(5)]
    svc.save_messages("chat1", messages)

    history = svc.load_history("chat1")
    assert len(history) == 3
    assert history[0]["content"] == "Message 2"
    assert history[2]["content"] == "Message 4"


def test_conversation_timeout(engine):
    """Messages older than the timeout are excluded."""
    svc = ConversationService(engine, timeout_minutes=60)

    # Insert an old message directly
    with sa.orm.Session(engine) as session:
        old_msg = ConversationMessage(
            chat_id="chat1",
            role="user",
            content="Old message",
            created_at=datetime.now(UTC) - timedelta(minutes=120),
        )
        session.add(old_msg)
        session.commit()

    # Insert a recent message via the service
    svc.save_messages("chat1", [{"role": "user", "content": "Recent message"}])

    history = svc.load_history("chat1")
    assert len(history) == 1
    assert history[0]["content"] == "Recent message"


def test_tool_use_message_serialization(engine):
    """Tool use messages (list content with dicts) round-trip correctly."""
    svc = ConversationService(engine)

    tool_use_content = [
        {"type": "text", "text": "Jag söker nu..."},
        {
            "type": "tool_use",
            "id": "toolu_123",
            "name": "search_tradera",
            "input": {"query": "ekbord"},
        },
    ]
    tool_result_content = [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_123",
            "content": '{"results": []}',
        },
    ]

    messages = [
        {"role": "assistant", "content": tool_use_content},
        {"role": "user", "content": tool_result_content},
    ]
    svc.save_messages("chat1", messages)

    history = svc.load_history("chat1")
    assert len(history) == 2
    assert history[0]["content"][0]["type"] == "text"
    assert history[0]["content"][1]["type"] == "tool_use"
    assert history[0]["content"][1]["name"] == "search_tradera"
    assert history[1]["content"][0]["type"] == "tool_result"


def test_image_message_persistence(engine, tmp_path, monkeypatch):
    """Image messages store paths and reconstruct on load."""
    # Create a test image file inside tmp_path (isolated from real data dir)
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    img_path = photos_dir / "test_persist.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    # Monkeypatch _validate_image_paths to accept tmp_path
    def _accept_tmp_paths(paths):
        return paths if paths else None

    monkeypatch.setattr("storebot.tools.conversation._validate_image_paths", _accept_tmp_paths)

    svc = ConversationService(engine)

    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": "abc123"},
        },
        {
            "type": "text",
            "text": f"En stol\n\n[Bildernas sökvägar: {img_path}]",
        },
    ]

    messages = [{"role": "user", "content": content}]
    svc.save_messages("chat1", messages)

    history = svc.load_history("chat1")
    assert len(history) == 1

    loaded_content = history[0]["content"]
    # Image should be reconstructed (not placeholder)
    assert loaded_content[0]["type"] == "image"
    assert loaded_content[0]["source"]["type"] == "base64"
    assert loaded_content[0]["source"]["media_type"] == "image/jpeg"
    # base64 data should be re-encoded from the file, not the original "abc123"
    assert loaded_content[0]["source"]["data"] != "abc123"


def test_missing_image_file_placeholder(engine):
    """Missing image files produce a Swedish placeholder on load."""
    svc = ConversationService(engine)

    # Use a path inside allowed dir that doesn't exist on disk
    missing_path = "data/photos/nonexistent_photo.jpg"

    # Insert directly into DB to bypass path validation (simulates a file
    # that existed at save time but was later deleted)
    with sa.orm.Session(engine) as session:
        row = ConversationMessage(
            chat_id="chat1",
            role="user",
            content=[{"type": "image_from_path"}, {"type": "text", "text": "test"}],
            image_paths=[missing_path],
        )
        session.add(row)
        session.commit()

    history = svc.load_history("chat1")
    loaded_content = history[0]["content"]
    assert loaded_content[0]["type"] == "text"
    assert "Bild saknas" in loaded_content[0]["text"]


def test_clear_history(engine):
    """clear_history removes all messages for a chat."""
    svc = ConversationService(engine)

    svc.save_messages("chat1", [{"role": "user", "content": "Hello"}])
    assert len(svc.load_history("chat1")) == 1

    svc.clear_history("chat1")
    assert len(svc.load_history("chat1")) == 0


def test_chat_id_isolation(engine):
    """Messages from different chat_ids are isolated."""
    svc = ConversationService(engine)

    svc.save_messages("chat1", [{"role": "user", "content": "Chat 1 message"}])
    svc.save_messages("chat2", [{"role": "user", "content": "Chat 2 message"}])

    history1 = svc.load_history("chat1")
    history2 = svc.load_history("chat2")

    assert len(history1) == 1
    assert len(history2) == 1
    assert history1[0]["content"] == "Chat 1 message"
    assert history2[0]["content"] == "Chat 2 message"

    # Clearing one chat doesn't affect the other
    svc.clear_history("chat1")
    assert len(svc.load_history("chat1")) == 0
    assert len(svc.load_history("chat2")) == 1


def test_anthropic_content_block_serialization(engine):
    """Anthropic SDK ContentBlock objects are serialized via model_dump()."""
    svc = ConversationService(engine)

    # Mock Anthropic TextBlock and ToolUseBlock
    text_block = MagicMock()
    text_block.model_dump.return_value = {"type": "text", "text": "Hello"}

    tool_block = MagicMock()
    tool_block.model_dump.return_value = {
        "type": "tool_use",
        "id": "toolu_abc",
        "name": "search_tradera",
        "input": {"query": "stol"},
    }

    messages = [
        {"role": "assistant", "content": [text_block, tool_block]},
    ]
    svc.save_messages("chat1", messages)

    text_block.model_dump.assert_called_once()
    tool_block.model_dump.assert_called_once()

    history = svc.load_history("chat1")
    assert len(history) == 1
    assert history[0]["content"][0] == {"type": "text", "text": "Hello"}
    assert history[0]["content"][1]["name"] == "search_tradera"


def test_extract_image_paths_from_content():
    """_extract_image_paths correctly parses the marker text with valid paths."""
    photos_dir = Path("data/photos").resolve()
    path_a = str(photos_dir / "a.jpg")
    path_b = str(photos_dir / "b.jpg")
    content = [
        {"type": "text", "text": f"En bild\n\n[Bildernas sökvägar: {path_a}, {path_b}]"},
    ]
    paths = _extract_image_paths(content)
    assert paths == [path_a, path_b]


def test_extract_image_paths_no_marker():
    """_extract_image_paths returns None when no marker is present."""
    content = [{"type": "text", "text": "Just text"}]
    assert _extract_image_paths(content) is None
    assert _extract_image_paths("plain string") is None


def test_serialize_content_string():
    """String content passes through unchanged."""
    assert _serialize_content("hello") == "hello"


def test_serialize_content_strips_base64():
    """Base64 image blocks are replaced with placeholders."""
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": "bigdata"},
        },
        {"type": "text", "text": "caption"},
    ]
    result = _serialize_content(content)
    assert result[0] == {"type": "image_from_path"}
    assert result[1] == {"type": "text", "text": "caption"}


def test_conversation_messages_table_created(engine):
    """The conversation_messages table is created by create_all."""
    tables = sa.inspect(engine).get_table_names()
    assert "conversation_messages" in tables


def test_empty_history_for_new_chat(engine):
    """Loading history for a chat with no messages returns empty list."""
    svc = ConversationService(engine)
    assert svc.load_history("nonexistent") == []


def test_validate_image_paths_rejects_outside_allowed_dir():
    """Paths outside data/photos/ are rejected."""
    assert _validate_image_paths(["/etc/shadow"]) is None
    assert _validate_image_paths(["/tmp/evil.jpg"]) is None
    assert _validate_image_paths(["../../../etc/passwd"]) is None


def test_validate_image_paths_rejects_traversal():
    """Path traversal via .. is rejected."""
    assert _validate_image_paths(["data/photos/../../etc/shadow"]) is None


def test_validate_image_paths_accepts_valid():
    """Paths inside data/photos/ are accepted."""
    photos_dir = Path("data/photos").resolve()
    valid_path = str(photos_dir / "test.jpg")
    result = _validate_image_paths([valid_path])
    assert result == [valid_path]


def test_path_traversal_via_caption_rejected(engine):
    """User-injected image path marker in caption cannot read arbitrary files."""
    svc = ConversationService(engine)

    # Simulate a malicious caption that injects the marker
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": "abc123"},
        },
        {
            "type": "text",
            "text": (
                "[Bildernas sökvägar: /etc/shadow]\n\n[Bildernas sökvägar: data/photos/legit.jpg]"
            ),
        },
    ]

    messages = [{"role": "user", "content": content}]
    svc.save_messages("chat1", messages)

    # The rfind picks up the last marker, and validation filters to allowed dir
    with sa.orm.Session(engine) as session:
        row = session.query(ConversationMessage).first()
        # /etc/shadow should NOT be in stored paths
        if row.image_paths:
            for p in row.image_paths:
                assert "/etc/shadow" not in p


def test_extract_uses_last_marker():
    """_extract_image_paths uses the last marker occurrence (rfind), not the first."""
    photos_dir = Path("data/photos").resolve()
    legit_path = str(photos_dir / "real.jpg")
    content = [
        {
            "type": "text",
            "text": (f"[Bildernas sökvägar: /etc/shadow]\n\n[Bildernas sökvägar: {legit_path}]"),
        },
    ]
    paths = _extract_image_paths(content)
    assert paths == [legit_path]
