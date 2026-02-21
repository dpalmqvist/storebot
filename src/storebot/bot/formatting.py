"""Convert Claude Markdown responses to Telegram HTML and handle message splitting."""

import html
import re

TELEGRAM_MAX_MESSAGE_LENGTH = 4000

_FENCED_CODE_RE = re.compile(r"```(?:\w*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_STAR_RE = re.compile(r"\*(.+?)\*")
_ITALIC_UNDER_RE = re.compile(r"(?<!\w)_(.+?)_(?!\w)")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^&gt;\s?(.+)$", re.MULTILINE)
_OPEN_TAG_RE = re.compile(r"<(b|i|s|code|pre|blockquote|a)(?:\s[^>]*)?>")
_CLOSE_TAG_RE = re.compile(r"</(b|i|s|code|pre|blockquote|a)>")


def html_escape(text: str) -> str:
    """Escape HTML special characters for safe Telegram HTML output."""
    return html.escape(text, quote=False)


def markdown_to_telegram_html(text: str) -> str:
    """Convert Claude's Markdown subset to Telegram-supported HTML tags.

    Code blocks are extracted first to avoid processing Markdown inside them,
    then reinserted at the end.
    """
    # Extract fenced code blocks before escaping
    code_blocks: list[str] = []

    def _stash_fenced(m: re.Match) -> str:
        code_blocks.append(html_escape(m.group(1).strip()))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = _FENCED_CODE_RE.sub(_stash_fenced, text)

    # Extract inline code before escaping
    inline_codes: list[str] = []

    def _stash_inline(m: re.Match) -> str:
        inline_codes.append(html_escape(m.group(1)))
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    text = _INLINE_CODE_RE.sub(_stash_inline, text)

    # Escape remaining text, then apply formatting
    text = html_escape(text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_STAR_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC_UNDER_RE.sub(r"<i>\1</i>", text)
    text = _STRIKE_RE.sub(r"<s>\1</s>", text)
    text = _LINK_RE.sub(r'<a href="\2">\1</a>', text)
    text = _HEADER_RE.sub(r"<b>\1</b>", text)
    text = _BLOCKQUOTE_RE.sub(r"<blockquote>\1</blockquote>", text)

    # Reinsert code blocks
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", f"<pre>{block}</pre>")
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{i}\x00", f"<code>{code}</code>")

    return text


def _get_open_tags(text: str) -> list[str]:
    """Return a stack of currently open HTML tags at the end of text.

    Preserves full opening tags (e.g. ``<a href="...">``) so they can be reopened.
    """
    stack: list[str] = []
    for m in _OPEN_TAG_RE.finditer(text):
        stack.append(m.group(0))
    for m in _CLOSE_TAG_RE.finditer(text):
        tag_name = m.group(1)
        for j in range(len(stack) - 1, -1, -1):
            if stack[j].startswith(f"<{tag_name}"):
                stack.pop(j)
                break
    return stack


def _close_tags(tags: list[str]) -> str:
    """Generate closing tags in reverse order for a list of open tags."""
    return "".join(f"</{tag.split()[0].strip('<').rstrip('>')}>" for tag in reversed(tags))


def split_html_message(text: str, max_length: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split HTML text into Telegram-safe chunks, preserving open tag state across boundaries.

    Adds (1/N) headers when splitting is needed. Properly closes and reopens
    HTML tags at split boundaries.
    """
    if not text:
        return [""]

    if len(text) <= max_length:
        return [text]

    estimated_parts = len(text) // max_length + 1
    header_len = len(f"({estimated_parts}/{estimated_parts})\n")
    chunk_size = max_length - header_len

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= chunk_size:
            chunks.append(remaining)
            break

        # Find best split point
        split_at = remaining.rfind("\n\n", 0, chunk_size)
        if split_at < chunk_size // 2:
            split_at = remaining.rfind("\n", 0, chunk_size)
        if split_at < chunk_size // 2:
            split_at = remaining.rfind(" ", 0, chunk_size)
        if split_at < chunk_size // 2:
            split_at = chunk_size

        chunk = remaining[:split_at]
        remaining = remaining[split_at:].lstrip("\n")

        open_tags = _get_open_tags(chunk)
        if open_tags:
            chunk += _close_tags(open_tags)
            remaining = "".join(open_tags) + remaining

        chunks.append(chunk)

    # Re-check after splitting — if header length changed, redo
    actual_header_len = len(f"({len(chunks)}/{len(chunks)})\n")
    if actual_header_len > header_len:
        # Recursively split with corrected size
        return split_html_message(text, max_length)

    total = len(chunks)
    return [f"({i + 1}/{total})\n{chunk}" for i, chunk in enumerate(chunks)]
