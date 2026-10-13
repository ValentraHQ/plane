# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""EPUB processing: structure, metadata, table of contents, sanitizing and the archive safety checks."""

# Python imports
import io
import json
import zipfile

# Third party imports
import pytest

# Module imports
from plane.tests.library_helpers import OPF, default_files, image_bytes, make_epub, make_pdf, make_zip
from plane.utils.library.archive import ArchiveLimits, SafeArchive, normalize_path
from plane.utils.library.epub import EpubBook, isbn_from, make_cover
from plane.utils.library.errors import BookError
from plane.utils.library.pdf import read_pdf
from plane.utils.library.sanitize import sanitize_chapter_html, sanitize_css

LIMITS = ArchiveLimits(max_entries=1000, max_unpacked=64 * 1024 * 1024, max_entry=16 * 1024 * 1024, max_ratio=100)


def open_book(data, limits=LIMITS, max_chapters=100):
    return EpubBook(io.BytesIO(data), limits, max_chapters)


def chapters_of(book):
    result = [(c, json.loads(c.content)) for c in book.chapters()]
    return result


@pytest.mark.unit
class TestValidBooks:
    def test_metadata(self):
        book = open_book(make_epub())
        meta = book.metadata
        assert meta.title == "The Test Book"
        assert meta.authors == ["Ada Author"]  # the editor is not an author
        assert meta.publisher == "Valentra Press"
        assert meta.language == "en"
        assert meta.isbn == "9780306406157"
        assert meta.published_date == "2026-10-29"
        assert meta.description == "A short book."
        assert meta.subjects == ["Testing"]

    def test_toc_from_nav_document(self):
        book = open_book(make_epub())
        assert [(e["title"], e["chapter"], e["fragment"]) for e in book.toc] == [
            ("Chapter One", 0, ""),
            ("Chapter Two", 1, ""),
        ]
        assert book.toc[0]["children"][0] == {"title": "Part Two", "chapter": 0, "fragment": "part2", "children": []}

    def test_toc_from_ncx_for_epub2(self):
        ncx = b"""<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap>
        <navPoint id="n1"><navLabel><text>Opening</text></navLabel><content src="text/ch1.xhtml"/></navPoint>
        <navPoint id="n2"><navLabel><text>Closing</text></navLabel><content src="text/ch2.xhtml#end"/></navPoint>
        </navMap></ncx>"""
        opf = (
            OPF.replace('version="3.0"', 'version="2.0"')
            .replace('properties="nav"', "")
            .replace("<spine>", '<spine toc="ncx">')
            .format(
                extra_manifest='<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', extra_spine=""
            )
        )
        book = open_book(
            make_epub(**{"OEBPS/content.opf": opf.encode(), "OEBPS/nav.xhtml": None, "OEBPS/toc.ncx": ncx})
        )
        assert [(e["title"], e["chapter"], e["fragment"]) for e in book.toc] == [
            ("Opening", 0, ""),
            ("Closing", 1, "end"),
        ]

    def test_chapters_are_sanitized_and_linked(self):
        book = open_book(make_epub())
        (one, doc1), (two, doc2) = chapters_of(book)
        assert one.title == "Chapter One" and two.title == "Chapter Two"
        assert 'href="plane-chapter:1#end"' in doc1["html"]
        assert 'href="https://example.com"' in doc1["html"] and "noopener" in doc1["html"]
        assert 'src="plane-res:OEBPS/images/fig.png"' in doc1["html"]
        assert doc1["stylesheets"] == ["OEBPS/style.css"]
        assert "Second part." in one.text and "<p" not in one.text
        assert one.linear is True

    def test_resources_are_the_used_ones_and_css_is_sanitized(self):
        book = open_book(make_epub())
        list(book.chapters())
        resources = {r.path: r for r in book.resources()}
        assert set(resources) == {"OEBPS/style.css", "OEBPS/images/fig.png"}
        css = resources["OEBPS/style.css"].data.decode()
        assert 'url("plane-res:OEBPS/images/fig.png")' in css
        assert "@import" not in css and "evil.example" not in css

    def test_cover(self):
        book = open_book(make_epub())
        assert book.cover_path() == "OEBPS/images/cover.jpg"
        thumb = make_cover(book.cover_image(), (300, 450))
        assert thumb[:3] == b"\xff\xd8\xff"  # JPEG

    def test_xhtml_doctype_is_not_fetched(self):
        # CH1 has an XHTML DOCTYPE pointing at w3.org; it must parse without any network access
        book = open_book(make_epub())
        assert len(list(book.chapters())) == 2

    def test_font_obfuscation_is_accepted(self):
        encryption = b"""<?xml version="1.0"?><encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
        xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData><enc:EncryptionMethod
        Algorithm="http://www.idpf.org/2008/embedding"/></enc:EncryptedData></encryption>"""
        open_book(make_epub(**{"META-INF/encryption.xml": encryption}))

    def test_isbn_validation(self):
        assert isbn_from("urn:isbn:978-0-306-40615-7") == "9780306406157"
        assert isbn_from("0-306-40615-2") == "0306406152"
        assert isbn_from("9780306406158") == ""  # bad check digit
        assert isbn_from("urn:uuid:1234") == ""


@pytest.mark.unit
class TestMalformedBooks:
    @pytest.mark.parametrize(
        "data, message",
        [
            (b"just text", "not a valid EPUB"),
            (make_epub(mimetype=None), "'mimetype' file is missing"),
            (make_epub(mimetype=b"application/zip"), "wrong 'mimetype'"),
            (make_epub(**{"META-INF/container.xml": None}), "container.xml"),
            (make_epub(**{"OEBPS/content.opf": None}), "package document"),
            (make_epub(**{"OEBPS/content.opf": b"<package><broken"}), "not valid XML"),
            (make_epub(**{"OEBPS/content.opf": b"<package xmlns='http://www.idpf.org/2007/opf'/>"}), "no manifest"),
            (make_epub(**{"OEBPS/text/ch1.xhtml": None, "OEBPS/text/ch2.xhtml": None}), "no readable chapters"),
        ],
    )
    def test_invalid_structure_is_rejected(self, data, message):
        with pytest.raises(BookError, match=message):
            open_book(data)

    def test_drm_is_rejected(self):
        encryption = b"""<?xml version="1.0"?><encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
        xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData><enc:EncryptionMethod
        Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/></enc:EncryptedData></encryption>"""
        with pytest.raises(BookError, match="DRM"):
            open_book(make_epub(**{"META-INF/encryption.xml": encryption}))

    def test_too_many_chapters(self):
        with pytest.raises(BookError, match="too many chapters"):
            open_book(make_epub(), max_chapters=1)

    @pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
    def test_damaged_chapter_entry(self, compression):
        data = bytearray(make_zip(default_files(), compression=compression))
        info = zipfile.ZipFile(io.BytesIO(bytes(data))).getinfo("OEBPS/text/ch2.xhtml")
        offset = info.header_offset
        name_len = int.from_bytes(data[offset + 26 : offset + 28], "little")
        extra_len = int.from_bytes(data[offset + 28 : offset + 30], "little")
        start = offset + 30 + name_len + extra_len
        for i in range(start + 5, start + min(info.compress_size, 60)):
            data[i] ^= 0xFF
        book = open_book(bytes(data))
        with pytest.raises(BookError, match="damaged"):
            list(book.chapters())


@pytest.mark.unit
class TestArchiveSafety:
    @pytest.mark.parametrize(
        "name", ["../evil.xhtml", "OEBPS/../../evil.xhtml", "/etc/passwd", "C:/evil", "OEBPS\\evil.xhtml"]
    )
    def test_path_traversal_and_absolute_paths(self, name):
        files = default_files()
        files[name] = b"x"
        with pytest.raises(BookError, match="unsafe file path"):
            SafeArchive(io.BytesIO(make_zip(files)), LIMITS)

    def test_symlink(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            info = zipfile.ZipInfo("OEBPS/link")
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "/etc/passwd")
        with pytest.raises(BookError, match="symbolic link"):
            SafeArchive(io.BytesIO(out.getvalue()), LIMITS)

    def test_duplicate_entries(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("a.xhtml", "1")
            archive.writestr("a.xhtml", "2")
        with pytest.raises(BookError, match="same file twice"):
            SafeArchive(io.BytesIO(out.getvalue()), LIMITS)

    def test_zip_encryption_flag(self):
        data = bytearray(make_zip({"a.txt": b"hello"}))
        # set the "encrypted" general-purpose flag in the local and central headers
        for signature in (b"PK\x03\x04", b"PK\x01\x02"):
            offset = data.find(signature)
            flag_at = offset + (6 if signature == b"PK\x03\x04" else 8)
            data[flag_at] |= 0x1
        with pytest.raises(BookError, match="encrypted"):
            SafeArchive(io.BytesIO(bytes(data)), LIMITS)

    def test_decompression_bomb_ratio(self):
        files = default_files(**{"OEBPS/bomb.bin": b"\x00" * (10 * 1024 * 1024)})
        with pytest.raises(BookError, match="decompression bomb"):
            SafeArchive(io.BytesIO(make_zip(files)), LIMITS)

    def test_total_unpacked_size(self):
        small = ArchiveLimits(max_entries=1000, max_unpacked=200 * 1024, max_entry=16 * 1024 * 1024, max_ratio=100000)
        files = default_files(**{f"OEBPS/f{i}.bin": bytes(range(256)) * 400 for i in range(5)})
        with pytest.raises(BookError, match="more data than allowed"):
            SafeArchive(io.BytesIO(make_zip(files)), small)

    def test_entry_size(self):
        small = ArchiveLimits(max_entries=1000, max_unpacked=64 * 1024 * 1024, max_entry=1024, max_ratio=100000)
        with pytest.raises(BookError, match="too large"):
            SafeArchive(io.BytesIO(make_epub()), small)

    def test_too_many_entries(self):
        few = ArchiveLimits(max_entries=5, max_unpacked=64 * 1024 * 1024, max_entry=16 * 1024 * 1024, max_ratio=100)
        with pytest.raises(BookError, match="too many files"):
            SafeArchive(io.BytesIO(make_epub()), few)

    def test_lying_header_cannot_unpack_more(self):
        archive = SafeArchive(io.BytesIO(make_epub()), LIMITS)
        # pretend the header under-reports the size; reading must stop and refuse
        archive.entries["OEBPS/text/ch1.xhtml"].file_size = 10
        with pytest.raises(BookError):
            archive.read("OEBPS/text/ch1.xhtml")

    @pytest.mark.parametrize(
        "path, base, expected",
        [
            ("ch1.xhtml", "OEBPS/text", "OEBPS/text/ch1.xhtml"),
            ("../images/a%20b.png#x", "OEBPS/text", "OEBPS/images/a b.png"),
            ("../../../etc/passwd", "OEBPS/text", None),
            ("https://evil.example/x.png", "OEBPS", None),
            ("javascript:alert(1)", "OEBPS", None),
            ("/abs.png", "OEBPS", None),
        ],
    )
    def test_normalize_path(self, path, base, expected):
        assert normalize_path(path, base) == expected


@pytest.mark.unit
class TestXmlSafety:
    def test_xxe_in_package_document(self):
        opf = b"""<?xml version="1.0"?><!DOCTYPE package [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
        <package xmlns="http://www.idpf.org/2007/opf"><metadata><title>&xxe;</title></metadata></package>"""
        with pytest.raises(BookError, match="declares XML entities"):
            open_book(make_epub(**{"OEBPS/content.opf": opf}))

    def test_billion_laughs_in_container(self):
        container = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>
        <container>&lol2;</container>"""
        with pytest.raises(BookError, match="declares XML entities"):
            open_book(make_epub(**{"META-INF/container.xml": container}))

    def test_entities_in_a_chapter(self):
        chapter = b"""<?xml version="1.0"?><!DOCTYPE html [<!ENTITY x SYSTEM "http://evil.example/">]>
        <html xmlns="http://www.w3.org/1999/xhtml"><body><p>&x;</p></body></html>"""
        book = open_book(make_epub(**{"OEBPS/text/ch2.xhtml": chapter}))
        with pytest.raises(BookError, match="declares XML entities"):
            list(book.chapters())


@pytest.mark.unit
class TestContentSanitizing:
    MALICIOUS = b"""<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head>
    <script>alert(1)</script><style>body{background:url(https://evil.example/t.png)} p{color:red}</style></head>
    <body onload="alert(1)">
    <p onclick="alert(2)" style="color: blue; background-image: url(https://evil.example/x)">Text</p>
    <a href="javascript:alert(3)">js link</a>
    <a href="data:text/html,&lt;script&gt;alert(4)&lt;/script&gt;">data link</a>
    <img src="https://evil.example/track.gif" onerror="alert(5)"/>
    <img src="../images/fake.png"/>
    <iframe src="https://evil.example"></iframe><object data="x.swf"></object><embed src="x"/>
    <form action="https://evil.example"><input name="password"/></form>
    <svg xmlns="http://www.w3.org/2000/svg"><script>alert(6)</script></svg>
    <math><mi>x</mi></math>
    <p>After everything</p>
    </body></html>"""

    def _sanitized(self, chapter=MALICIOUS, **files):
        fake = b"<html><script>alert(1)</script></html>"  # declared as PNG, really HTML (polyglot)
        opf = OPF.format(
            extra_manifest='<item id="fake" href="images/fake.png" media-type="image/png"/>', extra_spine=""
        ).encode()
        book = open_book(
            make_epub(
                **{"OEBPS/text/ch2.xhtml": chapter, "OEBPS/images/fake.png": fake, "OEBPS/content.opf": opf, **files}
            )
        )
        chapters = chapters_of(book)
        return chapters[1][1], book

    def test_scripts_handlers_and_dangerous_elements_are_removed(self):
        doc, _ = self._sanitized()
        html = doc["html"].lower()
        for needle in ("<script", "onload", "onclick", "onerror", "javascript:", "data:text", "<iframe", "<object",
                       "<embed", "<form", "<input", "<svg", "<math", "alert("):  # fmt: skip
            assert needle not in html, needle
        assert "After everything" in doc["html"]

    def test_remote_and_fake_images_are_not_loaded(self):
        doc, book = self._sanitized()
        assert "evil.example" not in doc["html"]
        assert "plane-res:OEBPS/images/fake.png" not in doc["html"]
        list(book.resources())
        assert "OEBPS/images/fake.png" not in book.used_images

    def test_inline_styles_are_filtered(self):
        doc, _ = self._sanitized()
        assert "color:blue" in doc["html"].replace(" ", "")
        assert "background-image" not in doc["html"]

    def test_head_style_is_kept_without_remote_urls(self):
        doc, _ = self._sanitized()
        assert "color:red" in doc["css"].replace(" ", "")
        assert "evil.example" not in doc["css"]

    def test_svg_cover_page_becomes_an_image(self):
        chapter = b"""<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"
        xmlns:xlink="http://www.w3.org/1999/xlink"><body><svg xmlns="http://www.w3.org/2000/svg">
        <image xlink:href="../images/cover.jpg" href="../images/cover.jpg"/></svg></body></html>"""
        book = open_book(make_epub(**{"OEBPS/text/ch2.xhtml": chapter}))
        doc = chapters_of(book)[1][1]
        assert '<img src="plane-res:OEBPS/images/cover.jpg"' in doc["html"]
        assert "<svg" not in doc["html"]

    def test_svg_cover_page_with_xlink_href_only(self):
        # Project Gutenberg's cover pages use xlink:href and no plain href
        chapter = b"""<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>
        <div class="cover"><svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
        viewBox="0 0 800 1104"><image width="800" height="1104" xlink:href="../images/cover.jpg"/></svg></div>
        </body></html>"""
        book = open_book(make_epub(**{"OEBPS/text/ch2.xhtml": chapter}))
        doc = chapters_of(book)[1][1]
        assert '<img src="plane-res:OEBPS/images/cover.jpg"' in doc["html"]

    def test_css_sanitizer(self):
        css = sanitize_css(
            """@import "https://evil.example/a.css";
            @font-face { font-family: X; src: url(https://evil.example/f.woff); }
            p { color: red; width: expression(alert(1)); }
            div { background: url(javascript:alert(1)); }
            .x { -moz-binding: url(evil.xml#x); }
            </style><script>alert(1)</script>""",
            "OEBPS/style.css",
            lambda path: False,
        )
        lowered = css.lower()
        for needle in ("@import", "@font-face", "evil.example", "expression", "javascript", "-moz-binding", "</style"):
            assert needle not in lowered, needle
        assert "color: red" in css

    def test_final_cleaner_drops_unknown_image_sources(self):
        html = sanitize_chapter_html('<p><img src="images/relative.png"><img src="plane-res:OEBPS/a.png"></p>')
        assert 'src="images/relative.png"' not in html
        assert 'src="plane-res:OEBPS/a.png"' in html


@pytest.mark.unit
class TestPdf:
    def test_metadata(self):
        pdf = read_pdf(io.BytesIO(make_pdf()))
        assert pdf.title == "A PDF Book"
        assert pdf.authors == ["Pat Writer"]
        assert pdf.description == "About PDFs"
        assert pdf.page_count == 3

    def test_not_a_pdf(self):
        with pytest.raises(BookError, match="not a PDF"):
            read_pdf(io.BytesIO(make_epub()))

    def test_damaged_pdf(self):
        with pytest.raises(BookError):
            read_pdf(io.BytesIO(b"%PDF-1.7\n" + b"\x00garbage" * 100))


def test_images_must_match_their_type():
    from plane.utils.library.epub import _image_matches

    assert _image_matches(image_bytes("PNG"), "image/png")
    assert not _image_matches(image_bytes("JPEG"), "image/png")
    assert not _image_matches(b"<html>not an image</html>", "image/png")
