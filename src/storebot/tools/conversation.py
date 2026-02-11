import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from storebot.db import ConversationMessage
from storebot.tools.image import encode_image_base64

logger = logging.getLogger(__name__)

# Sentinel used to replace base64 data in stored image blocks
IMAGE_PLACEHOLDER_TYPE = "image_from_path"


def _serialize_content(content):
    """Serialize message content for JSON storage.

    Handles Anthropic ContentBlock objects (TextBlock, ToolUseBlock, etc.)
    by calling .model_dump() on them. Strips base64 image data and replaces
    with a placeholder referencing the file path.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        serialized = []
        for block in content:
            # Anthropic SDK objects have model_dump()
            if hasattr(block, "model_dump"):
                serialized.append(block.model_dump())
            elif isinstance(block, dict):
                # Already a dict — check for base64 image data to strip
                if (
                    block.get("type") == "image"
                    and isinstance(block.get("source"), dict)
                    and block["source"].get("type") == "base64"
                ):
                    # Replace with placeholder — actual path stored in image_paths column
                    serialized.append({"type": IMAGE_PLACEHOLDER_TYPE})
                else:
                    serialized.append(block)
            else:
                serialized.append(block)
        return serialized
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
            idx = text.find(marker)
            if idx != -1:
                end = text.find("]", idx)
                if end != -1:
                    paths_str = text[idx + len(marker) : end]
                    return [p.strip() for p in paths_str.split(",") if p.strip()]
    return None


def _reconstruct_image_blocks(content, image_paths):
    """Replace image placeholders with re-encoded image data from disk."""
    if not isinstance(content, list) or not image_paths:
        return content

    result = []
    path_idx = 0
    for block in content:
        if isinstance(block, dict) and block.get("type") == IMAGE_PLACEHOLDER_TYPE:
            if path_idx < len(image_paths):
                path = image_paths[path_idx]
                path_idx += 1
                try:
                    data, media_type = encode_image_base64(path)
                    result.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        }
                    )
                except (FileNotFoundError, OSError):
                    logger.warning("Image file missing, using placeholder: %s", path)
                    result.append(
                        {
                            "type": "text",
                            "text": f"[Bild saknas: {path}]",
                        }
                    )
            else:
                result.append({"type": "text", "text": "[Bild saknas]"})
        else:
            result.append(block)
    return result


class ConversationService:
    def __init__(self, engine: sa.Engine, max_messages: int = 20, timeout_minutes: int = 60):
        self.engine = engine
        self.max_messages = max_messages
        self.timeout_minutes = timeout_minutes

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
        """Load recent conversation history for a chat, respecting timeout and max messages."""
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

        if not rows:
            return []

        # Take last N messages
        rows = rows[-self.max_messages :]

        messages = []
        for row in rows:
            content = row.content
            if row.image_paths:
                content = _reconstruct_image_blocks(content, row.image_paths)
            messages.append({"role": row.role, "content": content})

        return messages

    def clear_history(self, chat_id: str) -> None:
        """Delete all conversation messages for a chat."""
        with sa.orm.Session(self.engine) as session:
            session.query(ConversationMessage).filter(
                ConversationMessage.chat_id == str(chat_id),
            ).delete()
            session.commit()
