import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa

from storebot.db import ConversationMessage
from storebot.tools.image import encode_image_base64

logger = logging.getLogger(__name__)

# Sentinel used to replace base64 data in stored image blocks
IMAGE_PLACEHOLDER_TYPE = "image_from_path"


def _is_base64_image_block(block: dict) -> bool:
    """Check if a content block is a base64-encoded image."""
    return (
        block.get("type") == "image"
        and isinstance(block.get("source"), dict)
        and block["source"].get("type") == "base64"
    )


def _serialize_block(block):
    """Serialize a single content block for JSON storage.

    Skips thinking/redacted_thinking blocks (transient per-turn reasoning).
    Anthropic SDK objects are converted via model_dump().
    Base64 image data is replaced with a lightweight placeholder.
    """
    block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
    if block_type in ("thinking", "redacted_thinking"):
        return None

    if hasattr(block, "model_dump"):
        return block.model_dump()
    if isinstance(block, dict) and _is_base64_image_block(block):
        return {"type": IMAGE_PLACEHOLDER_TYPE}
    return block


def _serialize_content(content):
    """Serialize message content for JSON storage.

    Handles Anthropic ContentBlock objects (TextBlock, ToolUseBlock, etc.)
    by calling .model_dump() on them. Strips base64 image data and replaces
    with a placeholder referencing the file path. Filters out thinking blocks.
    """
    if isinstance(content, list):
        return [b for b in (_serialize_block(block) for block in content) if b is not None]
    return content


def _extract_image_paths(content):
    """Extract image file paths from user message content.

    Looks for the "[Bildernas sökvägar: ...]" text block appended by
    agent.handle_message() when images are present.
    """
    if not isinstance(content, list):
        return None

    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            marker = "[Bildernas sökvägar: "
            # Use rfind to get the LAST marker (the one appended by agent code),
            # not a user-injected one earlier in the text
            idx = text.rfind(marker)
            if idx != -1:
                end = text.find("]", idx)
                if end != -1:
                    paths_str = text[idx + len(marker) : end]
                    paths = [p.strip() for p in paths_str.split(",") if p.strip()]
                    return _validate_image_paths(paths)
    return None


def _validate_image_paths(paths: list[str]) -> list[str] | None:
    """Validate that image paths are within the allowed photos directory.

    Prevents path traversal attacks where a user could inject arbitrary
    file paths via the image path marker in message text.
    """
    allowed_dir = Path("data/photos").resolve()
    validated = []
    for p in paths:
        try:
            resolved = Path(p).resolve()
            if resolved.is_relative_to(allowed_dir):
                validated.append(p)
            else:
                logger.warning("Rejected image path outside allowed directory: %s", p)
        except (ValueError, OSError):
            logger.warning("Rejected invalid image path: %s", p)
    return validated if validated else None


def _encode_image_or_placeholder(path: str) -> dict:
    """Re-encode an image from disk, or return a placeholder if the file is missing."""
    try:
        data, media_type = encode_image_base64(path)
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    except (FileNotFoundError, OSError):
        logger.warning("Image file missing, using placeholder: %s", path)
        return {"type": "text", "text": f"[Bild saknas: {path}]"}


def _reconstruct_image_blocks(content, image_paths):
    """Replace image placeholders with re-encoded image data from disk."""
    if not isinstance(content, list) or not image_paths:
        return content

    path_iter = iter(image_paths)
    result = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == IMAGE_PLACEHOLDER_TYPE:
            path = next(path_iter, None)
            if path:
                result.append(_encode_image_or_placeholder(path))
            else:
                result.append({"type": "text", "text": "[Bild saknas]"})
        else:
            result.append(block)
    return result


def _is_tool_result_message(msg: dict) -> bool:
    """Check if a message contains tool_result blocks."""
    content = msg.get("content")
    if isinstance(content, list):
        return any(
            isinstance(block, dict) and block.get("type") == "tool_result" for block in content
        )
    return False


def _trim_orphaned_tool_messages(messages: list[dict]) -> list[dict]:
    """Drop leading messages until we find a user text message (not a tool_result).

    When max_messages truncation drops an assistant message containing tool_use
    blocks, the corresponding user tool_result message becomes orphaned.  The
    Claude API rejects conversations that start with orphaned tool_results.
    This function scans forward and drops messages until it finds a clean
    conversation boundary: a user message with plain text content.
    """
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and not _is_tool_result_message(msg):
            if i > 0:
                logger.info(
                    "Dropped %d orphaned tool-exchange messages from conversation start", i
                )
            return messages[i:]
    return []


class ConversationService:
    def __init__(
        self,
        engine: sa.Engine,
        max_messages: int = 60,
        timeout_minutes: int = 60,
        max_content_bytes: int = 1_000_000,
    ):
        self.engine = engine
        self.max_messages = max_messages
        self.timeout_minutes = timeout_minutes
        self.max_content_bytes = max_content_bytes

    def save_messages(self, chat_id: str, messages: list[dict]) -> None:
        """Save a list of message dicts to the database."""
        with sa.orm.Session(self.engine) as session:
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content")
                image_paths = _extract_image_paths(content)
                serialized = _serialize_content(content)

                row = ConversationMessage(
                    chat_id=str(chat_id),
                    role=role,
                    content=serialized,
                    image_paths=image_paths,
                )
                session.add(row)
            session.commit()

    def load_history(self, chat_id: str) -> list[dict]:
        """Load recent conversation history for a chat, respecting timeout, max messages,
        and max content size to prevent excessive API payloads."""
        cutoff = datetime.now(UTC) - timedelta(minutes=self.timeout_minutes)

        with sa.orm.Session(self.engine) as session:
            rows = (
                session.query(ConversationMessage)
                .filter(
                    ConversationMessage.chat_id == str(chat_id),
                    ConversationMessage.created_at >= cutoff,
                )
                .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
                .all()
            )

            # Iterate newest-first so truncation drops oldest messages,
            # keeping the most recent context for the agent.
            messages = []
            total_bytes = 0
            for row in reversed(rows[-self.max_messages :]):
                content = row.content
                if row.image_paths:
                    content = _reconstruct_image_blocks(content, row.image_paths)
                size = len(str(content).encode("utf-8", errors="replace"))
                if total_bytes + size > self.max_content_bytes and messages:
                    logger.info(
                        "Truncating conversation history at %d bytes (limit %d)",
                        total_bytes,
                        self.max_content_bytes,
                    )
                    break
                total_bytes += size
                messages.append({"role": row.role, "content": content})
            messages.reverse()

        return _trim_orphaned_tool_messages(messages)

    def replace_history(self, chat_id: str, messages: list[dict]) -> None:
        """Replace all conversation messages with compacted history.

        Not thread-safe: a concurrent read between DELETE and INSERT could
        see empty history. Acceptable for single-user deployment (Raspberry Pi).
        """
        with sa.orm.Session(self.engine) as session:
            session.query(ConversationMessage).filter(
                ConversationMessage.chat_id == str(chat_id),
            ).delete()
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content")
                image_paths = _extract_image_paths(content)
                serialized = _serialize_content(content)
                session.add(
                    ConversationMessage(
                        chat_id=str(chat_id),
                        role=role,
                        content=serialized,
                        image_paths=image_paths,
                    )
                )
            session.commit()

    def clear_history(self, chat_id: str) -> None:
        """Delete all conversation messages for a chat."""
        with sa.orm.Session(self.engine) as session:
            session.query(ConversationMessage).filter(
                ConversationMessage.chat_id == str(chat_id),
            ).delete()
            session.commit()
