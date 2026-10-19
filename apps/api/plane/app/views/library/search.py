# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Search across the library: books ranked by how well their details and their text match, with
passages from the text that open the reader at the match. Only books the user can see are
searched (plane.utils.book_search starts from viewable_books).
"""

# Django imports
from django.conf import settings
from django.utils import timezone

# Third party imports
from rest_framework.response import Response

# Module imports
from plane.app.serializers.library import BookSerializer
from plane.db.models import Book, BookChapter, BookReadingState
from plane.utils.book_access import viewable_books
from plane.utils.book_search import (
    MIN_QUERY,
    PASSAGES_PER_BOOK,
    clean_query,
    content_matches,
    metadata_matches,
    passage,
    query_terms,
)

from .base import UPLOAD_GRACE, LibraryBaseEndpoint

# details count more than the text: a book *about* the query beats one that mentions it
DETAILS_WEIGHT = 2.0
MAX_LIMIT = 50


class LibrarySearchEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        params = request.query_params
        query = clean_query(params.get("q"))
        include_text = settings.LIBRARY_FULLTEXT_SEARCH and params.get("content") != "false"
        try:
            limit = max(1, min(int(params.get("limit", 20)), MAX_LIMIT))
            offset = max(0, int(params.get("offset", 0)))
        except ValueError:
            limit, offset = 20, 0
        empty = {"query": query, "count": 0, "limit": limit, "offset": offset, "results": []}
        if len(query) < MIN_QUERY:
            return Response({**empty, "content_searched": include_text})

        books = viewable_books(self.workspace.id, request.user, role=role).exclude(
            status=Book.STATUS_UPLOADING, created_at__lt=timezone.now() - UPLOAD_GRACE
        )
        books = books.filter(archived_at__isnull=params.get("archived") != "true")
        if params.get("file_format") in dict(Book.FORMAT_CHOICES):
            books = books.filter(format=params["file_format"])
        if params.get("visibility") in ("0", "1"):
            books = books.filter(visibility=int(params["visibility"]))
        if params.get("tag"):
            books = books.filter(tags__icontains=params["tag"][:50])

        details = metadata_matches(books, query)
        text = content_matches(books, query) if include_text else {}
        scores = {
            book_id: DETAILS_WEIGHT * details.get(book_id, 0.0) + text.get(book_id, (0.0, []))[0]
            for book_id in {*details, *text}
        }
        titles = dict(Book.objects.filter(pk__in=scores).values_list("id", "title"))
        ranked = sorted(scores, key=lambda book_id: (-scores[book_id], (titles.get(book_id) or "").lower()))
        page_ids = ranked[offset : offset + limit]

        page_books = {b.id: b for b in Book.objects.filter(pk__in=page_ids).select_related("owner")}
        states = {s.book_id: s for s in BookReadingState.objects.filter(user=request.user, book_id__in=page_ids)}
        context = self.context(request, role, reading_states=states)

        # passages: the best chapters of each book on this page
        wanted = {
            (book_id, row["index"]): row
            for book_id in page_ids
            for row in text.get(book_id, (0.0, []))[1][:PASSAGES_PER_BOOK]
        }
        chapter_texts = {}
        if wanted:
            for row in BookChapter.objects.filter(book_id__in={b for b, _ in wanted}).values(
                "book_id", "index", "text"
            ):
                if (row["book_id"], row["index"]) in wanted:
                    chapter_texts[(row["book_id"], row["index"])] = row["text"]
        terms = query_terms(query)

        results = []
        for book_id in page_ids:
            book = page_books.get(book_id)
            if book is None:
                continue
            passages = []
            chapters = text.get(book_id, (0.0, []))[1]
            for row in chapters[:PASSAGES_PER_BOOK]:
                found = passage(chapter_texts.get((book_id, row["index"]), ""), query, terms)
                if found:
                    passages.append({"chapter": row["index"], "chapter_title": row["title"], **found})
            results.append(
                {
                    "book": BookSerializer(book, context=context).data,
                    "matched_details": book_id in details,
                    "matched_text": book_id in text,
                    "chapter_matches": len(chapters),
                    "passages": passages,
                }
            )
        return Response({**empty, "count": len(ranked), "results": results, "content_searched": include_text})
