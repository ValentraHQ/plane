# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Highlights, notes and bookmarks. Visibility rules live in plane.utils.book_access: annotations are
private to their author unless shared, and shared ones are only visible on workspace books.
"""

# Python imports
from collections import defaultdict

# Django imports
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header

# Third party imports
from rest_framework import serializers, status
from rest_framework.response import Response

# Module imports
from plane.db.models import Book, BookAnnotation, BookChapter
from plane.utils.book_access import annotation_permissions, viewable_books, visible_annotations

from .base import LibraryBaseEndpoint, _forbidden, _is_uuid, _not_found

MAX_QUOTE = 4000
MAX_SPAN = 20000
MAX_NOTE = 10000


class AnnotationSerializer(serializers.ModelSerializer):
    user_detail = serializers.SerializerMethodField()
    chapter_title = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    book_title = serializers.CharField(source="book.title", read_only=True)

    class Meta:
        model = BookAnnotation
        fields = [
            "id", "book", "book_title", "user", "user_detail", "kind", "color", "chapter", "chapter_title",
            "start_offset", "end_offset", "quote", "prefix", "suffix", "note", "visibility", "permissions",
            "created_at", "updated_at",
        ]  # fmt: skip
        read_only_fields = fields

    def get_user_detail(self, annotation):
        return {"id": str(annotation.user_id), "display_name": annotation.user.display_name}

    def get_chapter_title(self, annotation):
        return (self.context.get("chapter_titles") or {}).get((annotation.book_id, annotation.chapter), "")

    def get_permissions(self, annotation):
        return annotation_permissions(annotation, self.context["request"].user, self.context.get("role"))


class AnnotationInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[k for k, _ in BookAnnotation.KIND_CHOICES], default="highlight")
    color = serializers.ChoiceField(choices=list(BookAnnotation.COLORS), required=False)
    chapter = serializers.IntegerField(min_value=0)
    start_offset = serializers.IntegerField(min_value=0)
    end_offset = serializers.IntegerField(min_value=0)
    quote = serializers.CharField(
        max_length=MAX_QUOTE, allow_blank=True, required=False, default="", trim_whitespace=False
    )
    prefix = serializers.CharField(max_length=64, allow_blank=True, required=False, default="", trim_whitespace=False)
    suffix = serializers.CharField(max_length=64, allow_blank=True, required=False, default="", trim_whitespace=False)
    note = serializers.CharField(max_length=MAX_NOTE, allow_blank=True, required=False, default="")
    visibility = serializers.ChoiceField(
        choices=[BookAnnotation.VISIBILITY_PRIVATE, BookAnnotation.VISIBILITY_SHARED], default=0
    )

    def validate(self, data):
        if data["end_offset"] < data["start_offset"]:
            raise serializers.ValidationError({"end_offset": "The end must not be before the start."})
        if data["end_offset"] - data["start_offset"] > MAX_SPAN:
            raise serializers.ValidationError({"end_offset": "That passage is too long to annotate."})
        if data["kind"] != BookAnnotation.KIND_BOOKMARK and data["end_offset"] == data["start_offset"]:
            raise serializers.ValidationError({"end_offset": "Select some text to highlight."})
        if data["kind"] == BookAnnotation.KIND_NOTE and not data.get("note", "").strip():
            raise serializers.ValidationError({"note": "A note needs some text."})
        return data


class AnnotationUpdateSerializer(serializers.Serializer):
    color = serializers.ChoiceField(choices=list(BookAnnotation.COLORS), required=False)
    note = serializers.CharField(max_length=MAX_NOTE, allow_blank=True, required=False)
    visibility = serializers.ChoiceField(
        choices=[BookAnnotation.VISIBILITY_PRIVATE, BookAnnotation.VISIBILITY_SHARED], required=False
    )


def chapter_titles(annotations):
    keys = {(a.book_id, a.chapter) for a in annotations}
    if not keys:
        return {}
    books = {book_id for book_id, _ in keys}
    return {
        (c["book_id"], c["index"]): c["title"]
        for c in BookChapter.objects.filter(book_id__in=books).values("book_id", "index", "title")
        if (c["book_id"], c["index"]) in keys
    }


class BookAnnotationListEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        annotations = visible_annotations(request.user, [book]).select_related("user", "book")
        params = request.query_params
        if params.get("chapter", "").isdigit():
            annotations = annotations.filter(chapter=int(params["chapter"]))
        if params.get("kind") in dict(BookAnnotation.KIND_CHOICES):
            annotations = annotations.filter(kind=params["kind"])
        if params.get("mine") == "true":
            annotations = annotations.filter(user=request.user)
        annotations = list(annotations.order_by("chapter", "start_offset", "created_at")[:2000])
        context = {"request": request, "role": role, "chapter_titles": chapter_titles(annotations)}
        return Response(AnnotationSerializer(annotations, many=True, context=context).data)

    def post(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        if book.status != Book.STATUS_READY or book.format != Book.FORMAT_EPUB:
            return Response({"error": "This book cannot be annotated yet."}, status=status.HTTP_409_CONFLICT)
        serializer = AnnotationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["chapter"] >= book.chapter_count:
            return Response({"error": "That chapter does not exist."}, status=status.HTTP_400_BAD_REQUEST)
        if data["visibility"] == BookAnnotation.VISIBILITY_SHARED and book.visibility != Book.VISIBILITY_WORKSPACE:
            return Response(
                {"error": "Only annotations on workspace books can be shared."}, status=status.HTTP_400_BAD_REQUEST
            )
        if data["kind"] == BookAnnotation.KIND_HIGHLIGHT:
            data.setdefault("color", "yellow")
        else:
            data["color"] = data.get("color", "")
        annotation = BookAnnotation.objects.create(workspace=self.workspace, book=book, user=request.user, **data)
        context = {"request": request, "role": role, "chapter_titles": chapter_titles([annotation])}
        return Response(AnnotationSerializer(annotation, context=context).data, status=status.HTTP_201_CREATED)


class AnnotationDetailEndpoint(LibraryBaseEndpoint):
    def get_annotation(self, request, annotation_id, role):
        books = viewable_books(self.workspace.id, request.user, role=role)
        return visible_annotations(request.user, books).select_related("user", "book").filter(pk=annotation_id).first()

    def patch(self, request, slug, annotation_id):
        role, error = self.access(request)
        if error:
            return error
        annotation = self.get_annotation(request, annotation_id, role)
        if annotation is None:
            return Response({"error": "Annotation not found."}, status=status.HTTP_404_NOT_FOUND)
        if not annotation_permissions(annotation, request.user, role)["can_edit"]:
            return _forbidden("Only the author can change this annotation.")
        serializer = AnnotationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if (
            data.get("visibility") == BookAnnotation.VISIBILITY_SHARED
            and annotation.book.visibility != Book.VISIBILITY_WORKSPACE
        ):
            return Response(
                {"error": "Only annotations on workspace books can be shared."}, status=status.HTTP_400_BAD_REQUEST
            )
        if annotation.kind == BookAnnotation.KIND_NOTE and "note" in data and not data["note"].strip():
            return Response({"note": ["A note needs some text."]}, status=status.HTTP_400_BAD_REQUEST)
        for name, value in data.items():
            setattr(annotation, name, value)
        annotation.save()
        context = {"request": request, "role": role, "chapter_titles": chapter_titles([annotation])}
        return Response(AnnotationSerializer(annotation, context=context).data)

    def delete(self, request, slug, annotation_id):
        role, error = self.access(request)
        if error:
            return error
        annotation = self.get_annotation(request, annotation_id, role)
        if annotation is None:
            return Response({"error": "Annotation not found."}, status=status.HTTP_404_NOT_FOUND)
        if not annotation_permissions(annotation, request.user, role)["can_delete"]:
            return _forbidden("Only the author or a workspace admin can remove this annotation.")
        annotation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyAnnotationsEndpoint(LibraryBaseEndpoint):
    """The user's own annotations across every book they can still see (newest first)."""

    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        books = viewable_books(self.workspace.id, request.user, role=role)
        annotations = BookAnnotation.objects.filter(user=request.user, book__in=books).select_related("user", "book")
        params = request.query_params
        if params.get("book") and _is_uuid(params["book"]):
            annotations = annotations.filter(book_id=params["book"])
        if params.get("kind") in dict(BookAnnotation.KIND_CHOICES):
            annotations = annotations.filter(kind=params["kind"])
        query = params.get("search", "").strip()[:200]
        if query:
            annotations = annotations.filter(Q(quote__icontains=query) | Q(note__icontains=query))
        counts = {row["kind"]: row["total"] for row in annotations.values("kind").annotate(total=Count("id"))}
        try:
            limit = max(1, min(int(params.get("limit", 100)), 200))
            offset = max(0, int(params.get("offset", 0)))
        except ValueError:
            limit, offset = 100, 0
        total = annotations.count()
        page = list(annotations.order_by("-created_at")[offset : offset + limit])
        context = {"request": request, "role": role, "chapter_titles": chapter_titles(page)}
        return Response(
            {
                "count": total,
                "counts": counts,
                "results": AnnotationSerializer(page, many=True, context=context).data,
            }
        )


def _quote_block(text):
    return "\n".join(f"> {line}" if line else ">" for line in text.strip().splitlines())


def annotations_markdown(books_with_annotations, titles):
    """Markdown of annotations grouped by book and chapter, in reading order."""
    lines = []
    for book, annotations in books_with_annotations:
        lines += [f"# {book.title or book.original_filename}", ""]
        if book.authors:
            lines += [f"*{', '.join(book.authors)}*", ""]
        current = None
        for a in sorted(annotations, key=lambda a: (a.chapter, a.start_offset)):
            if a.chapter != current:
                current = a.chapter
                lines += [f"## {titles.get((book.id, a.chapter)) or f'Section {a.chapter + 1}'}", ""]
            if a.kind == BookAnnotation.KIND_BOOKMARK:
                lines += [
                    f"- 🔖 Bookmark{f': {a.note.strip()}' if a.note.strip() else ''}"
                    + (f" — “{a.quote.strip()[:80]}…”" if a.quote.strip() else ""),
                    "",
                ]
                continue
            label = "Highlight" + (f" ({a.color})" if a.kind == BookAnnotation.KIND_HIGHLIGHT and a.color else "")
            label = "Note" if a.kind == BookAnnotation.KIND_NOTE else label
            lines += [f"**{label}** · {timezone.localtime(a.created_at):%Y-%m-%d}", "", _quote_block(a.quote), ""]
            if a.note.strip():
                lines += [a.note.strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


class AnnotationExportEndpoint(LibraryBaseEndpoint):
    """The user's own annotations as Markdown: one book (?book=<id>) or all books."""

    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        books = viewable_books(self.workspace.id, request.user, role=role)
        annotations = BookAnnotation.objects.filter(user=request.user, book__in=books).select_related("book")
        if request.query_params.get("book") and _is_uuid(request.query_params["book"]):
            annotations = annotations.filter(book_id=request.query_params["book"])
        grouped = defaultdict(list)
        for annotation in annotations:
            grouped[annotation.book].append(annotation)
        ordered = sorted(grouped.items(), key=lambda item: (item[0].title or "").lower())
        content = annotations_markdown(ordered, chapter_titles(list(annotations)))
        if not grouped:
            content = "# Notes and highlights\n\nNothing to export yet.\n"
        name = "notes-and-highlights.md"
        if len(grouped) == 1:
            title = next(iter(grouped)).title or "book"
            name = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip()[:80] + " - notes.md"
        response = HttpResponse(content, content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = content_disposition_header(True, name)
        return response
