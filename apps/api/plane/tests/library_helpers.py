# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Builders for test EPUB / PDF files and an in-memory stand-in for the S3 storage."""

# Python imports
import hashlib
import io
import zipfile

# Third party imports
from PIL import Image
from pypdf import PdfWriter

CONTAINER = b"""<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:isbn:9780306406157</dc:identifier>
    <dc:title>The Test Book</dc:title>
    <dc:creator id="a1">Ada Author</dc:creator>
    <dc:creator id="e1">Ed Editor</dc:creator>
    <meta refines="#e1" property="role">edt</meta>
    <dc:publisher>Valentra Press</dc:publisher>
    <dc:language>en</dc:language>
    <dc:date>2026-10-29</dc:date>
    <dc:description>&lt;p&gt;A &lt;b&gt;short&lt;/b&gt; book.&lt;/p&gt;</dc:description>
    <dc:subject>Testing</dc:subject>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="text/ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="img" href="images/fig.png" media-type="image/png"/>
    <item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    {extra_manifest}
  </manifest>
  <spine>
    <itemref idref="c1"/>
    <itemref idref="c2"/>
    {extra_spine}
  </spine>
</package>"""

NAV = b"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>
<nav epub:type="toc"><ol>
  <li><a href="text/ch1.xhtml">Chapter One</a>
    <ol><li><a href="text/ch1.xhtml#part2">Part Two</a></li></ol></li>
  <li><a href="text/ch2.xhtml">Chapter Two</a></li>
</ol></nav></body></html>"""

CH1 = b"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en"><head><title>One</title>
<link rel="stylesheet" href="../style.css"/></head>
<body><h1>Chapter One</h1>
<p>First paragraph with a <a href="ch2.xhtml#end">link to two</a> and <a href="https://example.com">a site</a>.</p>
<p id="part2">Second part. <img src="../images/fig.png" alt="Figure"/></p>
</body></html>"""

CH2 = b"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Two</title></head>
<body><h1>Chapter Two</h1><p id="end">The end.</p></body></html>"""

CSS = b"""body { margin: 1em; }
.fig { background: url(images/fig.png); }
@import url("https://evil.example/x.css");
"""


def image_bytes(fmt="PNG", size=(40, 60), color=(200, 30, 30)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format=fmt)
    return out.getvalue()


def default_files(**overrides):
    files = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": CONTAINER,
        "OEBPS/content.opf": OPF.format(extra_manifest="", extra_spine="").encode(),
        "OEBPS/nav.xhtml": NAV,
        "OEBPS/text/ch1.xhtml": CH1,
        "OEBPS/text/ch2.xhtml": CH2,
        "OEBPS/style.css": CSS,
        "OEBPS/images/fig.png": image_bytes("PNG"),
        "OEBPS/images/cover.jpg": image_bytes("JPEG", (600, 900)),
    }
    files.update(overrides)
    return {name: data for name, data in files.items() if data is not None}


def make_zip(files, compression=zipfile.ZIP_DEFLATED):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(
                zipfile.ZipInfo(name), data, compress_type=zipfile.ZIP_STORED if name == "mimetype" else compression
            )
    return out.getvalue()


def make_epub(**overrides):
    return make_zip(default_files(**overrides))


def make_pdf(title="A PDF Book", author="Pat Writer", pages=3):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": title, "/Author": author, "/Subject": "About PDFs"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class FakeBody:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


class FakeS3Client:
    def __init__(self, store):
        self.store = store

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError

        if Key not in self.store:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": len(self.store[Key]["data"]), "ContentType": self.store[Key]["type"]}

    def download_fileobj(self, Bucket, Key, target):
        target.write(self.store[Key]["data"])

    def get_object(self, Bucket, Key):
        return {"Body": FakeBody(self.store[Key]["data"])}

    def get_paginator(self, name):
        store = self.store

        class Paginator:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for k in store if k.startswith(Prefix))
                for start in range(0, max(len(keys), 1), 1000):
                    yield {"Contents": [{"Key": k} for k in keys[start : start + 1000]]}

        return Paginator()


class FakeStorage:
    """In-memory S3Storage replacement: {key: {"data", "type"}}."""

    aws_storage_bucket_name = "test-bucket"

    def __init__(self, store=None, fail_after=None):
        self.store = {} if store is None else store
        self.s3_client = FakeS3Client(self.store)
        self.fail_after = fail_after
        self.puts = 0

    def upload_file(self, file_obj, object_name, content_type=None, extra_args=None):
        from botocore.exceptions import ClientError

        self.puts += 1
        if self.fail_after is not None and self.puts > self.fail_after:
            raise ClientError({"Error": {"Code": "SlowDown"}}, "PutObject")
        self.store[object_name] = {"data": file_obj.read(), "type": content_type}
        return True

    def delete_files(self, object_names):
        for name in object_names:
            self.store.pop(name, None)
        return True

    def get_object_metadata(self, object_name):
        if object_name not in self.store:
            return None
        return {"ContentLength": len(self.store[object_name]["data"]), "ContentType": self.store[object_name]["type"]}

    def generate_presigned_url(
        self, object_name, expiration=None, http_method="GET", disposition="inline", filename=None
    ):
        return f"https://signed.example/{object_name}?disposition={disposition}&filename={filename}"

    def generate_presigned_post(self, object_name, file_type, file_size, expiration=None):
        return {"url": "https://signed.example/upload", "fields": {"key": object_name, "Content-Type": file_type}}
