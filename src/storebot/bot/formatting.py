"""Convert Claude Markdown responses to Telegram HTML and handle message splitting."""

import html
import re

TELEGRAM_MAX_MESSAGE_LENGTH = 4000

_FENCED_CODE_RE = re.compile(r"```(?:\w*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_ITALIC_UNDER_RE = re.compile(r"(?<!\w)_(.+?)_(?!\w)")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
# Allows one level of balanced parentheses in URLs (e.g. Wikipedia links)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^()\s]*(?:\([^()]*\)[^()\s]*)*)\)")
_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
# Applied after html_escape(), so > has already become &gt; at this point
_BLOCKQUOTE_RE = re.compile(r"^&gt;\s?(.+)$", re.MULTILINE)
_OPEN_TAG_RE = re.compile(r"<(b|i|s|code|pre|blockquote|a)(?:\s[^>]*)?>")
_CLOSE_TAG_RE = re.compile(r"</(b|i|s|code|pre|blockquote|a)>")
_TAG_NAME_RE = re.compile(r"<(\w+)")
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def strip_html_tags(text: str) -> str:
    """Remove all HTML tags from text, leaving only content."""
    return _TAG_STRIP_RE.sub("", text)


def html_escape(text: str) -> str:
    """Escape text for Telegram HTML element content (does not escape quotes)."""
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

    def _link_sub(m: re.Match) -> str:
        url = m.group(2).replace('"', "&quot;")
        if not url.startswith(("http://", "https://")):
            return m.group(1)
        return f'<a href="{url}">{m.group(1)}</a>'

    text = _LINK_RE.sub(_link_sub, text)
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
            if stack[j] == f"<{tag_name}>" or stack[j].startswith(f"<{tag_name} "):
                stack.pop(j)
                break
    return stack


def _close_tags(tags: list[str]) -> str:
    """Generate closing tags in reverse order for a list of open tags."""
    parts = []
    for tag in reversed(tags):
        m = _TAG_NAME_RE.match(tag)
        if m:
            parts.append(f"</{m.group(1)}>")
    return "".join(parts)


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

    # Max closing-tag overhead: </b></i></s></code></pre></blockquote></a> = 43 chars
    tag_reserve = 50

    def _do_split(chunk_size: int) -> list[str]:
        chunks: list[str] = []
        rest = text
        # Leave room for closing tags that may be appended at boundaries
        split_limit = max(1, chunk_size - tag_reserve)
        while rest:
            if len(rest) <= chunk_size:
                chunks.append(rest)
                break

            split_at = rest.rfind("\n\n", 0, split_limit)
            if split_at < split_limit // 2:
                split_at = rest.rfind("\n", 0, split_limit)
            if split_at < split_limit // 2:
                split_at = rest.rfind(" ", 0, split_limit)
            if split_at < split_limit // 2:
                split_at = split_limit

            chunk = rest[:split_at]
            rest = rest[split_at:].lstrip("\n")

            open_tags = _get_open_tags(chunk)
            if open_tags:
                chunk += _close_tags(open_tags)
                rest = "".join(open_tags) + rest

            chunks.append(chunk)
        return chunks

    chunks = _do_split(max_length - header_len)
    actual_header_len = len(f"({len(chunks)}/{len(chunks)})\n")
    if actual_header_len > header_len:
        chunks = _do_split(max_length - actual_header_len)

    total = len(chunks)
    return [f"({i + 1}/{total})\n{chunk}" for i, chunk in enumerate(chunks)]
