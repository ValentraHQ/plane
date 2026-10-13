# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Parsing and sanitizing of book content.

XML is parsed without entity expansion, DTD loading or network access. Chapter XHTML is rewritten
(internal links -> `plane-chapter:<index>#<fragment>`, images -> `plane-res:<path>`; anything
external is dropped) and then cleaned by nh3 against an allow-list: no scripts, event handlers,
forms, frames, embedded objects, SVG or MathML, and no URLs other than http(s)/mailto links and
the two internal schemes. The reader serves the result in a sandboxed iframe without scripts and
with a restrictive Content-Security-Policy, as a second line of defense.
"""

# Python imports
import re
from urllib.parse import quote

# Third party imports
import nh3
from lxml import etree, html as lxml_html

# Module imports
from .archive import normalize_path
from .errors import BookError

RESOURCE_SCHEME = "plane-res"
CHAPTER_SCHEME = "plane-chapter"

XHTML_NS = "http://www.w3.org/1999/xhtml"
_ENTITY_DECLARATION = re.compile(rb"<!ENTITY", re.IGNORECASE)

ALLOWED_TAGS = {
    "a", "abbr", "address", "article", "aside", "b", "bdi", "bdo", "blockquote", "br", "caption", "cite",
    "code", "col", "colgroup", "dd", "del", "details", "dfn", "div", "dl", "dt", "em", "figcaption", "figure",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "img", "ins", "kbd", "li", "main",
    "mark", "nav", "ol", "p", "pre", "q", "rp", "rt", "ruby", "s", "samp", "section", "small", "span",
    "strong", "sub", "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "time", "tr", "u",
    "ul", "var", "wbr",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {
    "*": {"id", "class", "title", "lang", "dir", "style"},
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "headers"},
    "th": {"colspan", "rowspan", "headers", "scope"},
    "col": {"span"},
    "colgroup": {"span"},
    "ol": {"start", "reversed", "type"},
    "li": {"value"},
    "time": {"datetime"},
    "del": {"datetime"},
    "ins": {"datetime"},
}
ALLOWED_STYLE_PROPERTIES = {
    "border", "border-bottom", "border-collapse", "border-left", "border-right", "border-spacing", "border-top",
    "clear", "color", "display", "float", "font-family", "font-size", "font-style", "font-variant", "font-weight",
    "height", "letter-spacing", "line-height", "list-style-type", "margin", "margin-bottom", "margin-left",
    "margin-right", "margin-top", "max-width", "min-width", "padding", "padding-bottom", "padding-left",
    "padding-right", "padding-top", "page-break-after", "page-break-before", "text-align", "text-decoration",
    "text-indent", "text-transform", "vertical-align", "white-space", "width", "word-spacing",
}  # fmt: skip
# elements whose text ends a line when the chapter is read as plain text
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "figure", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table",
    "tr", "ul",
}  # fmt: skip
# dropped together with their content (nh3 would otherwise keep the text of unknown elements)
DROP_WITH_CONTENT = {"script", "style", "noscript", "template", "iframe", "object", "embed", "svg", "math", "form"}


def parse_xml(data, what):
    """Parse an XML document safely. Entity declarations are refused outright."""
    if _ENTITY_DECLARATION.search(data[:65536]):
        raise BookError(f"The EPUB's {what} declares XML entities, which are not allowed.")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, remove_comments=True, recover=False
    )
    try:
        return etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as error:
        raise BookError(f"The EPUB's {what} is not valid XML.") from error


def parse_document(data):
    """Parse chapter XHTML; real-world books are not always well-formed, so fall back to the HTML parser."""
    if _ENTITY_DECLARATION.search(data[:65536]):
        raise BookError("A chapter declares XML entities, which are not allowed.")
    try:
        return parse_xml(data, "chapter")
    except BookError:
        parser = lxml_html.HTMLParser(no_network=True, remove_comments=True, recover=True)
        try:
            root = lxml_html.fromstring(data, parser=parser)
        except (etree.ParserError, ValueError) as error:
            raise BookError("A chapter could not be read.") from error
        return root


def local_name(element):
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def find_first(root, name):
    for element in root.iter():
        if local_name(element) == name:
            return element
    return None


def strip_namespaces(root):
    """XHTML parsed as XML keeps namespaced tags and attributes; the reader needs plain HTML."""
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        element.tag = local_name(element)
        for key in list(element.attrib):
            if key.startswith("{"):
                value = element.attrib.pop(key)
                if key == "{http://www.w3.org/XML/1998/namespace}lang":
                    element.set("lang", value)
    etree.cleanup_namespaces(root)


def resource_url(path):
    return f"{RESOURCE_SCHEME}:{quote(path, safe='/')}"


def _safe_external(url):
    lowered = url.strip().lower()
    return lowered.startswith(("http://", "https://", "mailto:"))


def rewrite_chapter(root, chapter_path, chapter_index_by_path, resolve_image):
    """
    Rewrite links and image sources in place. Returns (body_html, stylesheet_paths, inline_css, title).
    `resolve_image(path)` returns True when the image is an allowed resource of the book.
    """
    base = chapter_path.rsplit("/", 1)[0] if "/" in chapter_path else ""
    strip_namespaces(root)
    head = find_first(root, "head")
    body = find_first(root, "body")
    if body is None:
        body = root
    stylesheets, inline_css = [], []
    title = ""
    if head is not None:
        for element in head.iter():
            name = local_name(element)
            if name == "link" and "stylesheet" in (element.get("rel") or "").lower():
                path = normalize_path(element.get("href"), base)
                if path:
                    stylesheets.append(path)
            elif name == "style" and element.text:
                inline_css.append(element.text)
            elif name == "title" and element.text and not title:
                title = element.text.strip()

    for element in list(body.iter()):
        name = local_name(element)
        if name == "a":
            href = element.get("href") or element.get("{http://www.w3.org/1999/xlink}href")
            element.attrib.pop("{http://www.w3.org/1999/xlink}href", None)
            if not href:
                element.attrib.pop("href", None)
            elif href.startswith("#"):
                index = chapter_index_by_path.get(chapter_path)
                element.set("href", f"{CHAPTER_SCHEME}:{index}{href}" if index is not None else href)
            elif _safe_external(href):
                element.set("href", href.strip())
            else:
                path = normalize_path(href, base)
                index = chapter_index_by_path.get(path) if path else None
                if index is None:
                    element.attrib.pop("href", None)
                else:
                    fragment = href.split("#", 1)[1] if "#" in href else ""
                    element.set("href", f"{CHAPTER_SCHEME}:{index}" + (f"#{fragment}" if fragment else ""))
        elif name == "svg":
            # a cover page often wraps its image in <svg>; keep the image, the svg itself is dropped
            image = next((child for child in element.iter() if local_name(child) == "image"), None)
            href = image.get("href") if image is not None else None
            path = normalize_path(href, base) if href and not _safe_external(href) else None
            if path and resolve_image(path) and element.getparent() is not None:
                img = etree.Element("img", src=resource_url(path), alt="")
                img.tail = element.tail
                element.getparent().replace(element, img)
        elif name in ("img", "image"):
            src = element.get("src") or element.get("{http://www.w3.org/1999/xlink}href") or element.get("href")
            path = normalize_path(src, base) if src and not _safe_external(src) else None
            if path and resolve_image(path):
                alt = element.get("alt") or ""
                element.attrib.clear()
                element.tag = "img"
                element.set("src", resource_url(path))
                element.set("alt", alt)
            else:
                # remote or unknown images are never loaded
                element.attrib.pop("src", None)

    body_html = etree.tostring(body, method="html", encoding="unicode")
    return body_html, stylesheets, "\n".join(inline_css), title


_UNSAFE_STYLE_VALUE = re.compile(r"url\s*\(|expression|javascript:|\\|<|>|@", re.IGNORECASE)


def filter_style(value):
    """Keep only allowed properties with plain values (no url(), expressions, escapes or markup)."""
    kept = []
    for declaration in (value or "").split(";"):
        if ":" not in declaration:
            continue
        name, _, val = declaration.partition(":")
        name, val = name.strip().lower(), val.strip()
        if name in ALLOWED_STYLE_PROPERTIES and val and not _UNSAFE_STYLE_VALUE.search(val):
            kept.append(f"{name}: {val}")
    return "; ".join(kept)


def _strip_dangerous(root):
    for element in list(root.iter()):
        if local_name(element) in DROP_WITH_CONTENT:
            parent = element.getparent()
            if parent is not None:
                # keep the text that followed the removed element
                if element.tail:
                    previous = element.getprevious()
                    if previous is not None:
                        previous.tail = (previous.tail or "") + element.tail
                    else:
                        parent.text = (parent.text or "") + element.tail
                parent.remove(element)


def sanitize_chapter_html(body_html):
    """Final allow-list cleaning. Input is the rewritten body; output is safe HTML for the reader."""
    attributes = ALLOWED_ATTRIBUTES
    try:
        fragment = lxml_html.fragment_fromstring(body_html, create_parent="div")
        _strip_dangerous(fragment)
        for element in fragment.iter():
            if isinstance(element.tag, str) and element.get("style") is not None:
                style = filter_style(element.get("style"))
                if style:
                    element.set("style", style)
                else:
                    del element.attrib["style"]
        body_html = etree.tostring(fragment, method="html", encoding="unicode")
    except (etree.ParserError, ValueError):
        # styles could not be filtered: drop them all rather than pass them through
        attributes = {**ALLOWED_ATTRIBUTES, "*": ALLOWED_ATTRIBUTES["*"] - {"style"}}
    cleaned = nh3.clean(
        body_html,
        tags=ALLOWED_TAGS,
        clean_content_tags=DROP_WITH_CONTENT - {"svg", "math", "form"},
        attributes=attributes,
        url_schemes={"http", "https", "mailto", RESOURCE_SCHEME, CHAPTER_SCHEME},
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )
    # images may only point at the book's own resources
    return re.sub(r'(<img\b[^>]*?\bsrc=")(?!' + RESOURCE_SCHEME + r':)[^"]*(")', r"\1\2", cleaned, flags=re.IGNORECASE)


def html_to_text(clean_html):
    """Plain text of sanitized chapter HTML, one line per block, for search and excerpts."""
    try:
        root = lxml_html.fragment_fromstring(clean_html or "<div></div>", create_parent="div")
    except (etree.ParserError, ValueError):
        return ""
    for element in root.iter():
        if local_name(element) in BLOCK_TAGS:
            element.tail = "\n" + (element.tail or "")
    text = root.text_content()
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_CSS_AT_BLOCK = re.compile(r"@(font-face|import)[^;{]*(\{[^}]*\}|;)", re.IGNORECASE)
_CSS_DANGEROUS = re.compile(r"expression\s*\(|javascript:|behavior\s*:|-moz-binding|@charset", re.IGNORECASE)


def sanitize_css(css, css_path, resolve_image, max_length=512 * 1024):
    """
    Keep a stylesheet's layout rules, drop what could load or run anything: @import and @font-face
    blocks, scriptable properties, and url()s that do not point at one of the book's own images.
    """
    css = _CSS_COMMENT.sub("", css or "")[:max_length]
    css = _CSS_AT_BLOCK.sub("", css)
    base = css_path.rsplit("/", 1)[0] if css_path and "/" in css_path else ""

    def replace_url(match):
        target = match.group(2).strip()
        path = normalize_path(target, base) if target and not _safe_external(target) else None
        if path and resolve_image(path):
            return f'url("{resource_url(path)}")'
        return "none"

    css = _CSS_URL.sub(replace_url, css)
    # drop whole declarations that still contain anything scriptable
    css = re.sub(r"[^;{}]*(" + _CSS_DANGEROUS.pattern + r")[^;{}]*;?", "", css, flags=re.IGNORECASE)
    # nothing can break out of the style element it is served in
    return css.replace("<", "\\3c ").replace(">", "\\3e ")
