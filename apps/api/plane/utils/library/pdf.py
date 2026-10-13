# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""PDF validation and metadata. PDFs are stored and downloadable; in-browser reading comes later."""

# Python imports
import re
from dataclasses import dataclass, field

# Third party imports
from pypdf import PdfReader
from pypdf.errors import PdfReadError

# Module imports
from .errors import BookError


@dataclass
class PdfMetadata:
    title: str = ""
    authors: list = field(default_factory=list)
    description: str = ""
    page_count: int | None = None
    encrypted: bool = False


def _clean(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def read_pdf(file_obj):
    head = file_obj.read(1024)
    file_obj.seek(0)
    if b"%PDF-" not in head:
        raise BookError("The file is not a PDF.")
    try:
        reader = PdfReader(file_obj, strict=False)
        result = PdfMetadata(encrypted=reader.is_encrypted)
        if reader.is_encrypted:
            # metadata of an encrypted PDF is only readable with an empty user password
            try:
                reader.decrypt("")
            except Exception:
                return result
        info = reader.metadata or {}
        result.title = _clean(info.get("/Title"), 512)
        author = _clean(info.get("/Author"), 512)
        result.authors = [a.strip()[:255] for a in re.split(r";", author) if a.strip()] if author else []
        result.description = _clean(info.get("/Subject"), 10000)
        result.page_count = len(reader.pages)
        return result
    except BookError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise BookError("The PDF is damaged and could not be read.") from error
