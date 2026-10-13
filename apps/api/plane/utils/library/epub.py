# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
EPUB 2 / EPUB 3 processing: structure validation, metadata, table of contents, sanitized chapters
and resources. Pure: reads a file, returns data; storage and database are the caller's job.
"""

# Python imports
import io
import json
import re
from dataclasses import dataclass, field

# Third party imports
from lxml import html as lxml_html
from PIL import Image

# Module imports
from .archive import ArchiveLimits, SafeArchive, normalize_path
from .errors import BookError
from .sanitize import (
    find_first,
    html_to_text,
    local_name,
    parse_document,
    parse_xml,
    rewrite_chapter,
    sanitize_chapter_html,
    sanitize_css,
)

EPUB_MIMETYPE = b"application/epub+zip"
XHTML_TYPES = {"application/xhtml+xml", "text/html"}
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
CSS_TYPE = "text/css"
# only font obfuscation is accepted in encryption.xml; anything else is DRM
FONT_OBFUSCATION = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}
PIL_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/gif": "GIF", "image/webp": "WEBP"}
MAX_IMAGE_PIXELS = 50_000_000


@dataclass
class Chapter:
    index: int
    spine_id: str
    href: str
    title: str
    linear: bool
    # stored JSON document for the reader: {"html", "stylesheets", "css"}
    content: str
    text: str


@dataclass
class Resource:
    path: str
    media_type: str
    data: bytes


@dataclass
class EpubMetadata:
    title: str = ""
    authors: list = field(default_factory=list)
    publisher: str = ""
    language: str = ""
    isbn: str = ""
    published_date: str = ""
    description: str = ""
    subjects: list = field(default_factory=list)
    identifiers: list = field(default_factory=list)


def _text(element):
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip() if element is not None else ""


def isbn_from(value):
    """Return a valid ISBN-10/13 contained in an identifier, or ''."""
    candidate = re.sub(r"[^0-9Xx]", "", re.sub(r"(?i)^urn:isbn:", "", value or ""))
    if len(candidate) == 13 and candidate.isdigit():
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(candidate[:12]))
        if (10 - total % 10) % 10 == int(candidate[12]):
            return candidate
    if len(candidate) == 10 and candidate[:9].isdigit():
        total = sum((10 - i) * int(d) for i, d in enumerate(candidate[:9]))
        check = (11 - total % 11) % 11
        if candidate[9].upper() == ("X" if check == 10 else str(check)):
            return candidate.upper()
    return ""


def html_description(value):
    """dc:description often contains HTML: keep its text only."""
    if not value:
        return ""
    try:
        return re.sub(r"\s+", " ", lxml_html.fromstring(f"<div>{value}</div>").text_content()).strip()[:10000]
    except Exception:
        return re.sub(r"<[^>]*>", " ", value)[:10000].strip()


class EpubBook:
    def __init__(self, file_obj, limits: ArchiveLimits, max_chapters):
        self.archive = SafeArchive(file_obj, limits)
        self.max_chapters = max_chapters
        self._check_mimetype()
        self._check_encryption()
        self.opf_path = self._find_opf()
        self.opf_dir = self.opf_path.rsplit("/", 1)[0] if "/" in self.opf_path else ""
        self._parse_opf()
        self.toc = self._parse_toc()
        self._image_checks = {}

    # --- structure ---
    def _check_mimetype(self):
        if not self.archive.exists("mimetype"):
            raise BookError("The file is not an EPUB (the 'mimetype' file is missing).")
        if self.archive.read("mimetype", max_bytes=128).strip() != EPUB_MIMETYPE:
            raise BookError("The file is not an EPUB (wrong 'mimetype').")

    def _check_encryption(self):
        if not self.archive.exists("META-INF/encryption.xml"):
            return
        root = parse_xml(self.archive.read("META-INF/encryption.xml", max_bytes=1024 * 1024), "encryption.xml")
        for element in root.iter():
            if local_name(element) == "encryptionmethod" and element.get("Algorithm") not in FONT_OBFUSCATION:
                raise BookError("The book is DRM-protected and cannot be opened.")

    def _find_opf(self):
        if not self.archive.exists("META-INF/container.xml"):
            raise BookError("The EPUB is missing META-INF/container.xml.")
        root = parse_xml(self.archive.read("META-INF/container.xml", max_bytes=1024 * 1024), "container.xml")
        for element in root.iter():
            if local_name(element) == "rootfile":
                path = normalize_path(element.get("full-path"))
                if path and self.archive.exists(path):
                    return path
        raise BookError("The EPUB does not say where its package document is.")

    def _parse_opf(self):
        root = parse_xml(self.archive.read(self.opf_path, max_bytes=16 * 1024 * 1024), "package document")
        self.version = root.get("version", "")
        metadata = find_first(root, "metadata")
        manifest = find_first(root, "manifest")
        spine = find_first(root, "spine")
        if manifest is None or spine is None:
            raise BookError("The EPUB's package document has no manifest or spine.")

        self.manifest = {}
        for item in manifest:
            if local_name(item) != "item":
                continue
            path = normalize_path(item.get("href"), self.opf_dir)
            if not item.get("id") or not path:
                continue
            self.manifest[item.get("id")] = {
                "path": path,
                "media_type": (item.get("media-type") or "").lower(),
                "properties": (item.get("properties") or "").split(),
            }
        self.path_types = {entry["path"]: entry["media_type"] for entry in self.manifest.values()}

        self.spine = []
        for itemref in spine:
            if local_name(itemref) != "itemref":
                continue
            entry = self.manifest.get(itemref.get("idref"))
            if entry and entry["media_type"] in XHTML_TYPES and self.archive.exists(entry["path"]):
                self.spine.append((itemref.get("idref"), entry["path"], itemref.get("linear", "yes") != "no"))
        if not self.spine:
            raise BookError("The EPUB has no readable chapters.")
        if len(self.spine) > self.max_chapters:
            raise BookError(f"The EPUB has too many chapters ({len(self.spine)}; the limit is {self.max_chapters}).")
        self.chapter_index_by_path = {path: index for index, (_, path, _) in enumerate(self.spine)}
        self.ncx_id = spine.get("toc")
        self.metadata = self._parse_metadata(metadata, root)

    def _parse_metadata(self, metadata, root):
        result = EpubMetadata()
        if metadata is None:
            return result
        roles = {}
        for element in metadata:
            if local_name(element) == "meta" and element.get("property") == "role" and element.get("refines"):
                roles[element.get("refines").lstrip("#")] = _text(element)
        cover_id = None
        for element in metadata:
            name, value = local_name(element), _text(element)
            if name == "title" and value and not result.title:
                result.title = value[:512]
            elif name == "creator" and value:
                role = element.get("{http://www.idpf.org/2007/opf}role") or roles.get(element.get("id") or "", "aut")
                if role in ("aut", "") and value not in result.authors:
                    result.authors.append(value[:255])
            elif name == "publisher" and value and not result.publisher:
                result.publisher = value[:255]
            elif name == "language" and value and not result.language:
                result.language = value[:35]
            elif name == "date" and value and not result.published_date:
                result.published_date = value[:32]
            elif name == "description" and value and not result.description:
                result.description = html_description(element.text or value)
            elif name == "subject" and value and len(result.subjects) < 50:
                result.subjects.append(value[:255])
            elif name == "identifier" and value:
                scheme = element.get("{http://www.idpf.org/2007/opf}scheme") or ""
                result.identifiers.append({"scheme": scheme[:50], "value": value[:255]})
                if not result.isbn:
                    result.isbn = isbn_from(value)
            elif name == "meta" and element.get("name") == "cover":
                cover_id = element.get("content")
        self.cover_id = cover_id
        return result

    # --- table of contents ---
    def _toc_target(self, href, base):
        path = normalize_path(href, base)
        if path is None or path not in self.chapter_index_by_path:
            return None, ""
        fragment = href.split("#", 1)[1] if "#" in href else ""
        return self.chapter_index_by_path[path], fragment[:255]

    def _parse_toc(self):
        nav = next((e for e in self.manifest.values() if "nav" in e["properties"]), None)
        if nav and self.archive.exists(nav["path"]):
            entries = self._parse_nav(nav["path"])
            if entries:
                return entries
        ncx = self.manifest.get(self.ncx_id) if self.ncx_id else None
        ncx = ncx or next((e for e in self.manifest.values() if e["media_type"] == "application/x-dtbncx+xml"), None)
        if ncx and self.archive.exists(ncx["path"]):
            return self._parse_ncx(ncx["path"])
        return []

    def _parse_nav(self, path):
        root = parse_document(self.archive.read(path, max_bytes=8 * 1024 * 1024))
        base = path.rsplit("/", 1)[0] if "/" in path else ""
        toc_nav = None
        for element in root.iter():
            if local_name(element) == "nav":
                types = " ".join(v for k, v in element.attrib.items() if k.endswith("type"))
                if "toc" in types.split():
                    toc_nav = element
                    break
        if toc_nav is None:
            return []
        top = next((child for child in toc_nav.iter() if local_name(child) == "ol"), None)
        return self._walk_nav(top, base, 0) if top is not None else []

    def _walk_nav(self, ol, base, depth):
        entries = []
        if depth > 8:
            return entries
        for li in ol:
            if local_name(li) != "li":
                continue
            label = next((c for c in li if local_name(c) in ("a", "span")), None)
            children = next((c for c in li if local_name(c) == "ol"), None)
            chapter, fragment = self._toc_target(label.get("href") or "", base) if label is not None else (None, "")
            entries.append(
                {
                    "title": _text(label)[:512] if label is not None else "",
                    "chapter": chapter,
                    "fragment": fragment,
                    "children": self._walk_nav(children, base, depth + 1) if children is not None else [],
                }
            )
        return entries

    def _parse_ncx(self, path):
        root = parse_xml(self.archive.read(path, max_bytes=8 * 1024 * 1024), "table of contents")
        base = path.rsplit("/", 1)[0] if "/" in path else ""
        nav_map = find_first(root, "navmap")

        def walk(parent, depth):
            entries = []
            if depth > 8:
                return entries
            for point in parent:
                if local_name(point) != "navpoint":
                    continue
                label = find_first(point, "text")
                content = next((c for c in point if local_name(c) == "content"), None)
                chapter, fragment = (
                    self._toc_target(content.get("src") or "", base) if content is not None else (None, "")
                )
                entries.append(
                    {
                        "title": _text(label)[:512],
                        "chapter": chapter,
                        "fragment": fragment,
                        "children": walk(point, depth + 1),
                    }
                )
            return entries

        return walk(nav_map, 0) if nav_map is not None else []

    def _toc_titles(self):
        titles = {}

        def walk(entries):
            for entry in entries:
                if entry["chapter"] is not None and entry["title"]:
                    # the first entry for a chapter, preferring one without a fragment
                    if entry["chapter"] not in titles or not entry["fragment"]:
                        titles.setdefault(entry["chapter"], entry["title"])
                walk(entry["children"])

        walk(self.toc)
        return titles

    # --- resources ---
    def is_image(self, path):
        """An image the book declares, of an allowed type, whose bytes really are that type."""
        # only the verdict is cached: holding every image in memory would not scale to big books
        if path not in self._image_checks:
            media_type = self.path_types.get(path)
            self._image_checks[path] = (
                media_type in IMAGE_TYPES
                and self.archive.exists(path)
                and _image_matches(self.archive.read(path), media_type)
            )
        return self._image_checks[path]

    def cover_path(self):
        entry = next((e for e in self.manifest.values() if "cover-image" in e["properties"]), None)
        if entry is None and self.cover_id:
            entry = self.manifest.get(self.cover_id)
        if entry is None:
            entry = next(
                (e for i, e in self.manifest.items() if "cover" in i.lower() and e["media_type"] in IMAGE_TYPES), None
            )
        if entry and self.is_image(entry["path"]):
            return entry["path"]
        return None

    def cover_image(self):
        path = self.cover_path()
        return self.archive.read(path) if path else None

    # --- chapters ---
    def chapters(self):
        """Yield sanitized chapters in spine order; collects the resources they use as it goes."""
        titles = self._toc_titles()
        self.used_images, self.used_stylesheets = set(), set()
        for index, (spine_id, path, linear) in enumerate(self.spine):
            root = parse_document(self.archive.read(path))

            def resolve_image(image_path):
                ok = self.is_image(image_path)
                if ok:
                    self.used_images.add(image_path)
                return ok

            body, stylesheets, inline_css, doc_title = rewrite_chapter(
                root, path, self.chapter_index_by_path, resolve_image
            )
            clean = sanitize_chapter_html(body)
            stylesheets = [p for p in stylesheets if self.path_types.get(p) == CSS_TYPE and self.archive.exists(p)]
            self.used_stylesheets.update(stylesheets)
            css = sanitize_css(inline_css, path, resolve_image) if inline_css else ""
            text = html_to_text(clean)
            title = titles.get(index) or _first_heading(clean) or doc_title
            content = json.dumps({"html": clean, "stylesheets": stylesheets, "css": css})
            yield Chapter(index, spine_id[:255], path[:1024], (title or "")[:512], linear, content, text)

    def resources(self):
        """Images and sanitized stylesheets referenced by the chapters (call after chapters())."""
        css_images = set()
        for path in sorted(self.used_stylesheets):

            def resolve_image(image_path):
                ok = self.is_image(image_path)
                if ok:
                    css_images.add(image_path)
                return ok

            css = sanitize_css(self.archive.read(path).decode("utf-8", "replace"), path, resolve_image)
            yield Resource(path, CSS_TYPE, css.encode("utf-8"))
        for path in sorted(self.used_images | css_images):
            yield Resource(path, self.path_types[path], self.archive.read(path))

    def close(self):
        self.archive.close()


def _first_heading(clean_html):
    match = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", clean_html, re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", match.group(1))).strip()[:512] if match else ""


def _image_matches(data, media_type):
    """The bytes must be a readable image of the declared type (no polyglots, no pixel bombs)."""
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != PIL_FORMATS[media_type]:
                return False
            image.verify()
        return True
    except Exception:
        return False


def make_cover(data, max_size, quality=85):
    """Re-encode a cover image as JPEG, scaled to fit `max_size` (strips anything but pixels)."""
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        image = image.convert("RGB")
        image.thumbnail(max_size)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()
