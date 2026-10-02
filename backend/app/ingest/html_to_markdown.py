"""Help-centre HTML → light markdown that keeps what chunking needs: `#` headings, `-`/`1.` lists and
blank-line separated blocks. Formatting that only adds noise to embeddings (bold, links, images)
becomes plain text.

Written against the Wix help-centre markup (data-component-type="…" blocks), with generic handling
for ordinary HTML.
"""

import re

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import Comment

BLOCK_TAGS = {"div", "p", "section", "article", "blockquote", "ul", "ol", "li", "table", "pre", "figure", "hr", "h1", "h2", "h3", "h4", "h5", "h6"}
DROPPED_TAGS = {"img", "svg", "script", "style", "iframe", "video", "figure", "hr", "noscript"}
HEADING_LEVEL = {"h1": 2, "h2": 2, "h3": 3, "h4": 4, "h5": 4, "h6": 4}
DROPPED_COMPONENTS = {"image", "video", "iframe", "line"}
GENERIC_TOGGLE = re.compile(r"^(show me how|tell me more|learn more|show me more|click here|read more)\.?$", re.I)


def _collapse(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def _heading(level: int, text: str) -> list[str]:
    return [f"{'#' * level} {text}"] if text else []


def _raw_inline(node) -> str:
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    tag = node.name
    if tag == "br":
        return "\n"
    if tag in DROPPED_TAGS:
        return " "  # inline icons sit between words: "the Connect <img>at the top"
    inner = "".join(_raw_inline(child) for child in node.children)
    return f" {inner} " if tag in BLOCK_TAGS else inner


def _inline(node) -> str:
    return _collapse(_raw_inline(node)) if node is not None else ""


def _labelled(label: str, blocks: list[str]) -> list[str]:
    """Prefix a label ("Note:", "Wix Editor:") onto the first block so the two are never split."""
    if not label:
        return blocks
    if not blocks:
        return [label]
    return [f"{label}\n{blocks[0]}", *blocks[1:]]


def _children(node) -> list:
    return [c for c in node.children if not isinstance(c, Comment)]


def _element_children(node) -> list[Tag]:
    return [c for c in node.children if isinstance(c, Tag)]


def _is_table_of_contents(lst: Tag, article_url: str | None) -> bool:
    items = [c for c in _element_children(lst) if c.name == "li"]
    if not items:
        return False

    def anchor(li: Tag) -> bool:
        link = li.find("a")
        href = link.get("href", "") if link else ""
        return href.startswith("#") or bool(article_url and href.startswith(f"{article_url}#"))

    return all(anchor(li) for li in items)


def _render_list(lst: Tag, depth: int = 0) -> list[str]:
    ordered = lst.name == "ol"
    lines, n = [], 0
    for li in (c for c in _element_children(lst) if c.name == "li"):
        nested = [c for c in _element_children(li) if c.name in ("ul", "ol")]
        own = [c for c in _children(li) if c not in nested]
        text = _collapse("".join(_raw_inline(c) for c in own)).replace("\n", " ")
        if text:
            n += 1
            lines.append(f"{'  ' * depth}{f'{n}.' if ordered else '-'} {text}")
        for sub in nested:
            lines.extend(_render_list(sub, depth + 1))
    return lines


def _render_table(table: Tag | None) -> list[str]:
    if table is None:
        return []
    headers = [_inline(th) for th in table.select("thead th")]
    meaningful = [h for h in headers if h]
    lines = []
    if len(meaningful) == 1:  # a single header label ("General Info") is a caption, not column names
        lines.append(meaningful[0])
    for row in table.select("tbody tr"):
        cells = [_inline(td) for td in row.find_all("td")]
        if not any(cells):
            continue
        if len(cells) == 2:
            lines.append(f"{cells[0]}: {cells[1]}")
        elif len(meaningful) == len(cells):
            lines.append("; ".join(f"{headers[i]}: {c}" for i, c in enumerate(cells)))
        else:
            lines.append(" | ".join(cells))
    return ["\n".join(lines)] if lines else []


def _render_component(kind: str, node: Tag, ctx: dict) -> list[str]:
    if kind in DROPPED_COMPONENTS:
        return []
    if kind in ("heading", "subheading"):
        h = node.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        return _heading(HEADING_LEVEL[h.name] if h else 3, _inline(h or node))
    if kind == "informative":
        title = _inline(node.select_one(".info-title"))
        content = node.select_one(".info-content")
        return _labelled(title, _render_children(content, ctx) if content else [])
    if kind == "collapsible":
        title = _inline(node.select_one(".collapsible-title"))
        content = node.select_one(".collapsible-content")
        blocks = _render_children(content, ctx) if content else []
        if not title or GENERIC_TOGGLE.match(title):
            return blocks
        # Real topics ("Is my currency supported?") become sub-sections; short labels stay inline.
        is_topic = title.endswith("?") or len(title.split()) >= 4
        return [*_heading(4, title), *blocks] if is_topic else _labelled(f"{title}:", blocks)
    if kind == "tabs":
        labels = [_inline(t) for t in node.select(".tab-heading")]
        wrapper = node.select_one(".tab-contents-wrapper")
        panes = _element_children(wrapper) if wrapper else []
        out = []
        for i, pane in enumerate(panes):
            out.extend(_labelled(f"{labels[i]}:" if i < len(labels) and labels[i] else "", _render_children(pane, ctx)))
        return out
    if kind == "table":
        return _render_table(node.find("table"))
    if kind in ("code", "html", "markdown"):
        text = node.get_text().strip()
        return [text] if text else []
    return _render_children(node, ctx)


def _render_children(node, ctx: dict) -> list[str]:
    """Render children, gluing runs of inline content ("Click <b>Save</b> now") into one block."""
    blocks: list[str] = []
    run: list = []

    def flush():
        text = _collapse("".join(_raw_inline(c) for c in run))
        if text:
            blocks.append(text)
        run.clear()

    for child in _children(node):
        is_block = isinstance(child, Tag) and (child.name in BLOCK_TAGS or child.get("data-component-type"))
        if not is_block:
            run.append(child)
            continue
        flush()
        blocks.extend(_render_block(child, ctx))
    flush()
    return blocks


def _render_block(node: Tag, ctx: dict) -> list[str]:
    component = node.get("data-component-type")
    if component:
        return _render_component(component, node, ctx)
    tag = node.name
    if tag in DROPPED_TAGS:
        return []
    if tag in HEADING_LEVEL:
        return _heading(HEADING_LEVEL[tag], _inline(node))
    if tag in ("ul", "ol"):
        if _is_table_of_contents(node, ctx.get("article_url")):
            return []
        lines = _render_list(node)
        return ["\n".join(lines)] if lines else []
    if tag == "table":
        return _render_table(node)
    if tag == "pre":
        text = node.get_text().strip()
        return [text] if text else []
    return _render_children(node, ctx)


def html_to_markdown(html: str, article_url: str | None = None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return "\n\n".join(_render_children(soup, {"article_url": article_url}))
