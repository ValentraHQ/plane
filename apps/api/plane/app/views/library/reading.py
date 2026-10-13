# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Reading: a person's position and progress in a book, their reader settings, "continue reading",
and search inside a book. Reading data is private: every query is filtered to the requesting user.
"""

# Python imports
import re

# Django imports
from django.db import IntegrityError, transaction
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.serializers.library import (
    READER_DEFAULTS,
    BookReadingStateSerializer,
    BookSerializer,
    ReaderPreferencesSerializer,
)
from plane.db.models import Book, BookChapter, BookReadingState, ReaderPreferences
from plane.utils.book_access import viewable_books

from .base import LibraryBaseEndpoint, _not_found

MAX_RESULTS = 100
MAX_PER_CHAPTER = 25
SNIPPET = 60


def reading_states_for(user, books):
    """{book_id: state} for the given books and the requesting user, in one query."""
    ids = [book.id for book in books]
    return {state.book_id: state for state in BookReadingState.objects.filter(user=user, book_id__in=ids)}


def serialize_state(state):
    if state is None:
        return {"position": {}, "progress": 0, "status": BookReadingState.STATUS_UNREAD, "last_opened_at": None}
    return {
        "position": state.position,
        "progress": state.progress,
        "status": state.status,
        "last_opened_at": state.last_opened_at,
        "completed_at": state.completed_at,
    }


class BookReadingStateEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        return Response(serialize_state(BookReadingState.objects.filter(book=book, user=request.user).first()))

    def put(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        serializer = BookReadingStateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "position" in data and data["position"]["chapter"] >= max(book.chapter_count, 1):
            return Response({"error": "That chapter does not exist."}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        try:
            with transaction.atomic():
                state, _ = BookReadingState.objects.select_for_update().get_or_create(
                    book=book, user=request.user, defaults={"workspace_id": book.workspace_id}
                )
        except IntegrityError:
            # two devices created it at the same moment
            state = BookReadingState.objects.get(book=book, user=request.user)
        if "position" in data:
            state.position = dict(data["position"])
            if state.status == BookReadingState.STATUS_UNREAD and "status" not in data:
                state.status = BookReadingState.STATUS_READING
        if "progress" in data:
            state.progress = round(data["progress"], 2)
        if "status" in data:
            state.status = data["status"]
            if data["status"] == BookReadingState.STATUS_UNREAD:
                state.position, state.progress = {}, 0
        state.completed_at = (state.completed_at or now) if state.status == BookReadingState.STATUS_COMPLETED else None
        if data.get("opened") or "position" in data:
            state.last_opened_at = now
        state.save()
        return Response(serialize_state(state))


class ContinueReadingEndpoint(LibraryBaseEndpoint):
    """Books the user is reading, most recently opened first (only books they can still see)."""

    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        visible = viewable_books(self.workspace.id, request.user, role=role).filter(
            archived_at__isnull=True, status=Book.STATUS_READY
        )
        states = (
            BookReadingState.objects.filter(
                user=request.user,
                status=BookReadingState.STATUS_READING,
                book__in=visible,
                last_opened_at__isnull=False,
            )
            .select_related("book", "book__owner")
            .order_by("-last_opened_at")[:12]
        )
        states = list(states)
        context = self.context(request, role, reading_states={state.book_id: state for state in states})
        return Response(BookSerializer([state.book for state in states], many=True, context=context).data)


class ReaderPreferencesEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        stored = ReaderPreferences.objects.filter(user=request.user).values_list("preferences", flat=True).first()
        return Response({**READER_DEFAULTS, **(stored or {})})

    def put(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        serializer = ReaderPreferencesSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        preferences, _ = ReaderPreferences.objects.get_or_create(user=request.user)
        preferences.preferences = {**READER_DEFAULTS, **(preferences.preferences or {}), **serializer.validated_data}
        preferences.save()
        return Response(preferences.preferences)


class BookSearchEndpoint(LibraryBaseEndpoint):
    """
    Find text inside one book. Each result names the chapter and which occurrence of the text it is
    in that chapter, so the reader can find the same occurrence in the rendered chapter.
    """

    def get(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        query = " ".join(request.query_params.get("q", "").split())[:200]
        if len(query) < 2:
            return Response({"query": query, "results": [], "truncated": False})
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        results, truncated = [], False
        chapters = (
            BookChapter.objects.filter(book=book, text__icontains=query)
            .order_by("index")
            .values("index", "title", "text")
        )
        for chapter in chapters:
            # whitespace inside the chapter text is collapsed the same way as the query
            text = " ".join(chapter["text"].split())
            for occurrence, match in enumerate(pattern.finditer(text)):
                if occurrence >= MAX_PER_CHAPTER or len(results) >= MAX_RESULTS:
                    truncated = True
                    break
                start, end = match.span()
                results.append(
                    {
                        "chapter": chapter["index"],
                        "chapter_title": chapter["title"],
                        "occurrence": occurrence,
                        "before": text[max(0, start - SNIPPET) : start],
                        "match": text[start:end],
                        "after": text[end : end + SNIPPET],
                    }
                )
            if len(results) >= MAX_RESULTS:
                truncated = True
                break
        return Response({"query": query, "results": results, "truncated": truncated})
