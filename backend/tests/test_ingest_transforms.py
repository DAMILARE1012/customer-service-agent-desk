"""Normalization, HTML conversion and chunking — ported from the original JavaScript test suite."""

from app.ingest.chunker import chunk_markdown
from app.ingest.html_to_markdown import html_to_markdown
from app.ingest.normalize import clean_text, index_form, normalize_query

# ── normalize ────────────────────────────────────────────────────────────────


def test_removes_invisible_characters_and_odd_spaces():
    assert clean_text(f"Hello{chr(0xA0)}world{chr(0x200B)}{chr(0xFEFF)}") == "Hello world"


def test_keeps_identifiers_prices_emails_and_arrows():
    text = "Order #48213 cost $249.99 — code SAVE20, email a.b@example.com, Account → Orders"
    assert clean_text(text) == text


def test_collapses_spaces_and_blank_lines_but_keeps_list_indentation():
    assert clean_text("Steps:\n\n\n\n1. Open   settings\n  - nested   item") == "Steps:\n\n1. Open settings\n  - nested item"


def test_nfkc_folds_ligatures():
    assert clean_text(f"{chr(0xFB01)}le") == "file"


def test_applies_per_source_boilerplate():
    import re

    text = "Real content.\nWe are always working to update and improve our products, and your feedback is greatly appreciated."
    assert clean_text(text, [re.compile(r"We are always working[^\n]*appreciated\.")]) == "Real content."


def test_index_form_folds_quotes_and_dashes_for_search_only():
    display = clean_text(f"it{chr(0x2019)}s {chr(0x201C)}fine{chr(0x201D)} {chr(0x2013)} 3{chr(0x2013)}5 days")
    assert chr(0x2019) in display
    assert index_form(display) == "it's \"fine\" - 3-5 days"
    assert normalize_query(f"  it{chr(0x2019)}s  ") == "it's"


# ── HTML → markdown ──────────────────────────────────────────────────────────

URL = "https://support.example.com/en/article/demo"


def test_keeps_headings_and_lists_drops_images_and_link_markup():
    html = """
      <div data-component-type="heading"><h2>Connecting a domain</h2></div>
      <div data-component-type="text"><ol><li>Click <strong>Settings</strong>.</li><li>Click the icon <img src="x.png">at the top.</li></ol></div>
      <div data-component-type="image"><img src="shot.png" alt="A screenshot"></div>"""
    assert html_to_markdown(html, URL) == "## Connecting a domain\n\n1. Click Settings.\n2. Click the icon at the top."


def test_drops_in_page_tables_of_contents():
    html = f'<ul><li><a href="{URL}#step-1">Step 1</a></li><li><a href="#step-2">Step 2</a></li></ul><div>Body text.</div>'
    assert html_to_markdown(html, URL) == "Body text."


def test_keeps_ordinary_link_lists():
    assert html_to_markdown('<ul><li><a href="https://other.example.com/a">Other article</a></li></ul>', URL) == "- Other article"


def test_labels_tabs_and_callouts():
    html = """
      <div data-component-type="tabs"><div class="tabs-wrapper">
        <div class="headings-wrapper"><div class="tab-heading">Wix Editor</div><div class="tab-heading">Studio Editor</div></div>
        <div class="tab-contents-wrapper"><div class="tab-content"><div>Click Add.</div></div><div class="tab-content"><div>Click Plus.</div></div></div>
      </div></div>
      <div data-component-type="informative"><div class="info-title">Note:</div><div class="info-content"><div>Save first.</div></div></div>"""
    assert html_to_markdown(html) == "Wix Editor:\nClick Add.\n\nStudio Editor:\nClick Plus.\n\nNote:\nSave first."


def test_question_collapsibles_become_subheadings_and_ui_toggles_disappear():
    html = """
      <div data-component-type="collapsible"><h4 class="collapsible-title">Is my currency supported?</h4><div class="collapsible-content"><div>Most are.</div></div></div>
      <div data-component-type="collapsible"><h4 class="collapsible-title">Show me how</h4><div class="collapsible-content"><div>Do this.</div></div></div>"""
    assert html_to_markdown(html) == "#### Is my currency supported?\n\nMost are.\n\nDo this."


def test_two_column_tables_become_key_value_lines():
    html = """<div data-component-type="table"><table>
      <thead><tr><th>General Info</th><th></th></tr></thead>
      <tbody><tr><td>Supported countries</td><td>United States</td></tr><tr><td>Fees</td><td>2.6% + 0.20 USD</td></tr></tbody>
    </table></div>"""
    assert html_to_markdown(html) == "General Info\nSupported countries: United States\nFees: 2.6% + 0.20 USD"


# ── chunking ─────────────────────────────────────────────────────────────────


def count(text: str) -> int:  # one token per word keeps the arithmetic readable
    return len(text.split())


def words(n: int, word: str = "lorem") -> str:
    return " ".join([word] * n)


OPTIONS = {"min_tokens": 10, "target_tokens": 60, "max_tokens": 100}


def test_splits_at_headings_and_records_heading_path():
    md = f"{words(20)}\n\n## Billing\n\n{words(20, 'bill')}\n\n### Refunds\n\n{words(20, 'refund')}"
    assert [c.heading_path for c in chunk_markdown(md, count, **OPTIONS)] == [[], ["Billing"], ["Billing", "Refunds"]]


def test_folds_tiny_section_into_the_next_with_heading_inline():
    chunks = chunk_markdown(f"## Tiny\n\n{words(3, 'tiny')}\n\n## Big\n\n{words(30, 'big')}", count, **OPTIONS)
    assert len(chunks) == 1
    assert chunks[0].heading_path == ["Tiny"]
    assert "tiny tiny tiny\n\n## Big\nbig" in chunks[0].text


def test_intro_line_stays_with_its_list():
    md = "Do the following:\n\n" + "\n".join(f"{i}. {words(12, 'step')}" for i in range(1, 7))
    assert chunk_markdown(md, count, **OPTIONS)[0].text.startswith("Do the following:\n\n1. step")


def test_no_chunk_ends_with_a_dangling_heading():
    import re

    md = f"## A\n\n{words(5)}\n\n## B\n\n{words(95, 'b')}\n\n## C\n\n{words(40, 'c')}"
    for chunk in chunk_markdown(md, count, **OPTIONS):
        assert not re.search(r"(^|\n)#{1,6} [^\n]+$", chunk.text)


def test_oversized_blocks_are_split_to_fit():
    sentences = " ".join(f"{words(9, 'word')}." for _ in range(30))
    chunks = chunk_markdown(sentences, count, **OPTIONS)
    assert len(chunks) > 1
    assert all(c.tokens <= OPTIONS["max_tokens"] for c in chunks)


def test_editing_one_section_only_changes_that_sections_chunks():
    def doc(word):
        return f"## Shipping\n\n{words(30, 'ship')}\n\n## Billing\n\n{words(30, word)}\n\n## Returns\n\n{words(30, 'return')}"

    before = [c.text for c in chunk_markdown(doc("bill"), count, **OPTIONS)]
    after = [c.text for c in chunk_markdown(doc("invoice"), count, **OPTIONS)]
    assert len(before) == len(after)
    assert sum(1 for a, b in zip(before, after, strict=True) if a != b) == 1  # only Billing is re-embedded
