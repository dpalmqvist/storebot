"""Tests for storebot.bot.formatting — HTML escaping, Markdown→HTML, and message splitting."""

from storebot.bot.formatting import (
    TELEGRAM_MAX_MESSAGE_LENGTH,
    html_escape,
    markdown_to_telegram_html,
    split_html_message,
    strip_html_tags,
)


class TestHtmlEscape:
    def test_escapes_angle_brackets(self):
        assert html_escape("<script>alert('xss')</script>") == (
            "&lt;script&gt;alert('xss')&lt;/script&gt;"
        )

    def test_escapes_ampersand(self):
        assert html_escape("foo & bar") == "foo &amp; bar"

    def test_preserves_swedish_chars(self):
        assert html_escape("åäö ÅÄÖ") == "åäö ÅÄÖ"

    def test_preserves_newlines_and_emojis(self):
        text = "Hej!\n🎉 Bra jobbat"
        assert html_escape(text) == text

    def test_empty_string(self):
        assert html_escape("") == ""


class TestStripHtmlTags:
    def test_strips_simple_tags(self):
        assert strip_html_tags("<b>bold</b> text") == "bold text"

    def test_strips_nested_tags(self):
        assert strip_html_tags("<b><i>bi</i></b>") == "bi"

    def test_strips_attributed_tags(self):
        assert strip_html_tags('<a href="https://x.com">link</a>') == "link"

    def test_preserves_plain_text(self):
        assert strip_html_tags("no tags here") == "no tags here"


class TestMarkdownToTelegramHtml:
    def test_bold(self):
        assert "**fet text**" not in markdown_to_telegram_html("**fet text**")
        assert "<b>fet text</b>" in markdown_to_telegram_html("**fet text**")

    def test_italic_star(self):
        assert "<i>kursiv</i>" in markdown_to_telegram_html("*kursiv*")

    def test_italic_underscore(self):
        assert "<i>kursiv</i>" in markdown_to_telegram_html("_kursiv_")

    def test_inline_code(self):
        result = markdown_to_telegram_html("Kör `storebot` nu")
        assert "<code>storebot</code>" in result

    def test_fenced_code_block(self):
        md = "Före\n```python\ndef foo():\n    pass\n```\nEfter"
        result = markdown_to_telegram_html(md)
        assert "<pre>" in result
        assert "</pre>" in result
        assert "def foo():" in result

    def test_code_block_content_html_escaped(self):
        md = "```\n<div>test</div>\n```"
        result = markdown_to_telegram_html(md)
        assert "&lt;div&gt;" in result
        assert "<div>" not in result

    def test_code_block_not_markdown_processed(self):
        md = "```\n**not bold** _not italic_\n```"
        result = markdown_to_telegram_html(md)
        assert "<b>" not in result
        assert "<i>" not in result
        assert "**not bold**" in result

    def test_inline_code_html_escaped(self):
        result = markdown_to_telegram_html("Kör `a < b`")
        assert "<code>a &lt; b</code>" in result

    def test_link(self):
        result = markdown_to_telegram_html("[Tradera](https://tradera.com)")
        assert '<a href="https://tradera.com">Tradera</a>' in result

    def test_link_url_with_quotes_escaped(self):
        result = markdown_to_telegram_html('[Click](https://x.com/q="a")')
        assert '<a href="https://x.com/q=&quot;a&quot;">Click</a>' in result

    def test_link_url_with_parentheses(self):
        result = markdown_to_telegram_html("[Foo](https://en.wikipedia.org/wiki/Foo_(bar))")
        assert "https://en.wikipedia.org/wiki/Foo_(bar)" in result
        assert "<a " in result

    def test_header(self):
        result = markdown_to_telegram_html("# Rubrik")
        assert "<b>Rubrik</b>" in result

    def test_header_levels(self):
        for level in range(1, 7):
            hashes = "#" * level
            result = markdown_to_telegram_html(f"{hashes} Rubrik {level}")
            assert f"<b>Rubrik {level}</b>" in result

    def test_blockquote(self):
        result = markdown_to_telegram_html("> Citat här")
        assert "<blockquote>Citat här</blockquote>" in result

    def test_blockquote_with_html_special_chars(self):
        result = markdown_to_telegram_html("> Pris: 100 < 200 & moms")
        assert "<blockquote>Pris: 100 &lt; 200 &amp; moms</blockquote>" in result

    def test_strikethrough(self):
        result = markdown_to_telegram_html("~~struken~~")
        assert "<s>struken</s>" in result

    def test_mixed_formatting(self):
        md = "**Titel**: *beskrivning* med `kod`"
        result = markdown_to_telegram_html(md)
        assert "<b>Titel</b>" in result
        assert "<i>beskrivning</i>" in result
        assert "<code>kod</code>" in result

    def test_html_entities_escaped_in_text(self):
        result = markdown_to_telegram_html("Pris: 100 < 200 & moms > 25%")
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&gt;" in result

    def test_plain_text_only_escaping(self):
        text = "Ingen markdown här, bara vanlig text."
        result = markdown_to_telegram_html(text)
        assert result == text

    def test_swedish_text_preserved(self):
        text = "Ångström & Björk — två fina möbler"
        result = markdown_to_telegram_html(text)
        assert "Ångström" in result
        assert "&amp;" in result

    def test_bullet_list_preserved(self):
        md = "Saker:\n- Stol\n- Bord\n- Lampa"
        result = markdown_to_telegram_html(md)
        assert "- Stol" in result
        assert "- Bord" in result
        assert "- Lampa" in result

    def test_star_bullet_list_not_italicised(self):
        md = "Saker:\n* Stol\n* Bord\n* Lampa"
        result = markdown_to_telegram_html(md)
        assert "* Stol" in result
        assert "<i>" not in result

    def test_numbered_list_preserved(self):
        md = "Steg:\n1. Första\n2. Andra\n3. Tredje"
        result = markdown_to_telegram_html(md)
        assert "1. Första" in result
        assert "2. Andra" in result

    def test_empty_input(self):
        assert markdown_to_telegram_html("") == ""

    def test_nested_bold_italic(self):
        result = markdown_to_telegram_html("**bold and *italic* inside**")
        assert "<b>" in result
        assert "<i>italic</i>" in result

    def test_link_non_http_scheme_rendered_as_text(self):
        result = markdown_to_telegram_html("[click](javascript:alert(1))")
        assert "<a " not in result
        assert "click" in result

    def test_multi_paragraph_preserved(self):
        md = "Första stycket.\n\nAndra stycket."
        result = markdown_to_telegram_html(md)
        assert "\n\n" in result


class TestSplitHtmlMessage:
    def test_short_message_as_is(self):
        result = split_html_message("Hej!")
        assert result == ["Hej!"]

    def test_exact_limit_not_split(self):
        text = "x" * TELEGRAM_MAX_MESSAGE_LENGTH
        result = split_html_message(text)
        assert result == [text]

    def test_over_limit_splits(self):
        text = "x" * (TELEGRAM_MAX_MESSAGE_LENGTH + 1)
        result = split_html_message(text)
        assert len(result) >= 2
        assert result[0].startswith("(1/")

    def test_headers_format(self):
        text = "x" * (TELEGRAM_MAX_MESSAGE_LENGTH * 2)
        result = split_html_message(text)
        total = len(result)
        for i, part in enumerate(result):
            assert part.startswith(f"({i + 1}/{total})\n")

    def test_splits_at_paragraph_boundary(self):
        half = TELEGRAM_MAX_MESSAGE_LENGTH // 2
        text = "a" * half + "\n\n" + "b" * half
        result = split_html_message(text)
        assert len(result) == 2
        assert result[0].endswith("a" * half)

    def test_splits_at_line_boundary(self):
        half = TELEGRAM_MAX_MESSAGE_LENGTH // 2
        text = "a" * half + "\n" + "b" * half
        result = split_html_message(text)
        assert len(result) == 2
        assert result[0].endswith("a" * half)

    def test_splits_at_word_boundary(self):
        word = "word "
        text = word * (TELEGRAM_MAX_MESSAGE_LENGTH // len(word) + 100)
        result = split_html_message(text)
        assert len(result) >= 2
        content = result[0].split("\n", 1)[1]
        assert content.endswith("word")

    def test_dense_text_hard_cut(self):
        text = "x" * (TELEGRAM_MAX_MESSAGE_LENGTH * 3)
        result = split_html_message(text)
        assert len(result) >= 3
        for part in result:
            assert len(part) <= TELEGRAM_MAX_MESSAGE_LENGTH

    def test_no_content_lost(self):
        text = "Hello world! " * 500
        result = split_html_message(text)
        content = " ".join(part.split("\n", 1)[1] for part in result)
        assert content.split() == text.split()

    def test_empty_string(self):
        assert split_html_message("") == [""]

    def test_closes_open_bold_tag(self):
        # Build text where a <b>...</b> spans the split boundary
        half = TELEGRAM_MAX_MESSAGE_LENGTH // 2
        text = "<b>" + "x" * half + " " + "y" * half + "</b>"
        result = split_html_message(text)
        assert len(result) >= 2
        # First chunk should have closing </b>
        first_content = result[0].split("\n", 1)[1]
        assert first_content.endswith("</b>")
        # Second chunk should reopen <b>
        second_content = result[1].split("\n", 1)[1]
        assert second_content.startswith("<b>")

    def test_closes_nested_tags(self):
        half = TELEGRAM_MAX_MESSAGE_LENGTH // 2
        text = "<b><i>" + "x" * half + " " + "y" * half + "</i></b>"
        result = split_html_message(text)
        assert len(result) >= 2
        first_content = result[0].split("\n", 1)[1]
        # Should close inner tag first, then outer
        assert "</i></b>" in first_content
        second_content = result[1].split("\n", 1)[1]
        # Should reopen outer first, then inner
        assert second_content.startswith("<b><i>")

    def test_header_length_correction_at_digit_boundary(self):
        # Text that produces ~10 chunks — header goes from "(9/9)\n" to "(10/10)\n"
        text = "x" * 35950
        result = split_html_message(text)
        assert len(result) >= 10
        for part in result:
            assert len(part) <= TELEGRAM_MAX_MESSAGE_LENGTH

    def test_closing_tags_do_not_exceed_max_length(self):
        half = TELEGRAM_MAX_MESSAGE_LENGTH // 2
        text = "<b><i>" + "x" * half + " " + "y" * half + "</i></b>"
        result = split_html_message(text)
        for part in result:
            assert len(part) <= TELEGRAM_MAX_MESSAGE_LENGTH

    def test_preserves_a_href_on_reopen(self):
        half = TELEGRAM_MAX_MESSAGE_LENGTH // 2
        text = '<a href="https://example.com">' + "x" * half + " " + "y" * half + "</a>"
        result = split_html_message(text)
        assert len(result) >= 2
        second_content = result[1].split("\n", 1)[1]
        assert '<a href="https://example.com">' in second_content


class TestGetOpenTags:
    def test_close_tag_pops_from_stack(self):
        from storebot.bot.formatting import _get_open_tags

        # All tags closed — empty stack
        result = _get_open_tags("<b>hello</b>")
        assert result == []

    def test_nested_close_tags(self):
        from storebot.bot.formatting import _get_open_tags

        # Inner closed, outer still open
        result = _get_open_tags("<b><i>hello</i>")
        assert result == ["<b>"]

    def test_close_tag_with_attr(self):
        from storebot.bot.formatting import _get_open_tags

        result = _get_open_tags('<a href="http://x.com">link</a>')
        assert result == []
