# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Library (eBook) endpoints. Every decision goes through plane.utils.book_access; a book the user may
not see is reported as 404 so its existence is not revealed. All endpoints are 404 while the
library is disabled (LIBRARY_ENABLED).
"""

# Python imports
import os
import re
import uuid
from datetime import timedelta
from urllib.parse import unquote

# Django imports
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.http import JsonResponse
from django.utils import timezone

# Third party imports
from botocore.exceptions import BotoCoreError, ClientError
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.serializers.library import (
    BOOK_TYPES,
    BookChapterSerializer,
    BookDetailSerializer,
    BookSerializer,
    BookUpdateSerializer,
    BookUploadSerializer,
)
from plane.bgtasks.book_task import chapter_document, process_book, purge_book_files
from plane.db.models import (
    Book,
    BookChapter,
    BookCollectionItem,
    BookReadingState,
    BookResource,
    FileAsset,
    Workspace,
)
from plane.settings.storage import S3Storage
from plane.utils.book_access import book_permissions, library_role, viewable_books, viewable_collections

from ..base import BaseAPIView

# how long an unfinished upload is listed (the upload itself usually takes seconds)
UPLOAD_GRACE = timedelta(hours=1)
ORDER_BY = {"-created_at", "created_at", "title", "-title", "-updated_at", "updated_at"}
RESOURCE_PLACEHOLDER = re.compile(r"plane-res:([A-Za-z0-9._~/%!$&'*+,;=@-]+)")


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def _not_found():
    return Response({"error": "Book not found."}, status=status.HTTP_404_NOT_FOUND)


def _forbidden(message):
    return Response({"error": message}, status=status.HTTP_403_FORBIDDEN)


class LibraryBaseEndpoint(BaseAPIView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.workspace = Workspace.objects.filter(slug=kwargs.get("slug")).first()

    def dispatch(self, request, *args, **kwargs):
        if not settings.LIBRARY_ENABLED:
            # behave as if the feature did not exist
            return JsonResponse({"error": "Not found."}, status=404)
        return super().dispatch(request, *args, **kwargs)

    def access(self, request):
        """(role, error response). Guests and non-members get 403, like the wiki."""
        if self.workspace is None:
            return None, Response({"error": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        role = library_role(request.user, self.workspace.id)
        if role is None:
            return None, _forbidden("You do not have access to the library of this workspace.")
        return role, None

    def get_book(self, request, book_id, role):
        book = viewable_books(self.workspace.id, request.user, role=role).filter(pk=book_id).first()
        return book, book_permissions(book, request.user, role=role) if book else None

    def context(self, request, role, **extra):
        return {"request": request, "role": role, "storage": S3Storage(request=request), **extra}

    def detail_context(self, request, role, book=None):
        visible = set(viewable_collections(self.workspace.id, request.user, role=role).values_list("id", flat=True))
        states = {}
        if book is not None:
            states = {s.book_id: s for s in BookReadingState.objects.filter(user=request.user, book=book)}
        return self.context(request, role, visible_collection_ids=visible, reading_states=states)


class BookListEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        books = viewable_books(self.workspace.id, request.user, role=role).select_related("owner")
        # unfinished uploads are not books yet; recent ones stay visible while they complete
        books = books.exclude(status=Book.STATUS_UPLOADING, created_at__lt=timezone.now() - UPLOAD_GRACE)
        params = request.query_params
        if params.get("visibility") in ("0", "1"):
            books = books.filter(visibility=int(params["visibility"]))
        if params.get("status", "").isdigit():
            books = books.filter(status=int(params["status"]))
        if params.get("format") in ("epub", "pdf"):
            books = books.filter(format=params["format"])
        books = books.filter(archived_at__isnull=params.get("archived") != "true")
        reading = {"reading": BookReadingState.STATUS_READING, "completed": BookReadingState.STATUS_COMPLETED}
        if params.get("reading") in ("reading", "completed", "unread"):
            mine = BookReadingState.objects.filter(book=OuterRef("pk"), user=request.user)
            if params["reading"] == "unread":
                books = books.exclude(Exists(mine.exclude(status=BookReadingState.STATUS_UNREAD)))
            else:
                books = books.filter(Exists(mine.filter(status=reading[params["reading"]])))
        if params.get("tag"):
            books = books.filter(tags__contains=[params["tag"][:50]])
        if params.get("collection"):
            collection = (
                viewable_collections(self.workspace.id, request.user, role=role).filter(pk=params["collection"]).first()
                if _is_uuid(params["collection"])
                else None
            )
            if collection is None:
                return Response({"error": "Collection not found."}, status=status.HTTP_404_NOT_FOUND)
            books = books.filter(collection_items__collection=collection, collection_items__deleted_at__isnull=True)
        query = params.get("search", "").strip()[:200]
        if query:
            books = books.filter(
                Q(title__icontains=query)
                | Q(authors__icontains=query)
                | Q(isbn__icontains=query.replace("-", ""))
                | Q(publisher__icontains=query)
                | Q(tags__icontains=query)
            )
        order_by = params.get("order_by", "-created_at")
        books = books.order_by(order_by if order_by in ORDER_BY else "-created_at", "id")
        try:
            limit = max(1, min(int(params.get("limit", 50)), 100))
            offset = max(0, int(params.get("offset", 0)))
        except ValueError:
            limit, offset = 50, 0
        total = books.count()
        page = list(books[offset : offset + limit])
        states = {
            state.book_id: state
            for state in BookReadingState.objects.filter(user=request.user, book_id__in=[b.id for b in page])
        }
        return Response(
            {
                "count": total,
                "limit": limit,
                "offset": offset,
                "results": BookSerializer(
                    page, many=True, context=self.context(request, role, reading_states=states)
                ).data,
            }
        )

    def post(self, request, slug):
        """Reserve an upload. Duplicates (same file in the same library) are refused with 409."""
        role, error = self.access(request)
        if error:
            return error
        serializer = BookUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        name, visibility, file_hash = data["name"], data["visibility"], data["sha256"]
        book_format, content_type = BOOK_TYPES[os.path.splitext(name)[1].lower()]

        duplicate = Book.objects.filter(workspace=self.workspace, file_hash=file_hash, visibility=visibility)
        if visibility == Book.VISIBILITY_PERSONAL:
            duplicate = duplicate.filter(owner=request.user)
        duplicate = duplicate.first()
        if duplicate and duplicate.status == Book.STATUS_UPLOADING and duplicate.owner_id == request.user.id:
            # the user's own unfinished upload of this file (e.g. the browser was closed): start over
            abandoned_id = str(duplicate.id)
            with transaction.atomic():
                duplicate.delete()
                transaction.on_commit(lambda: purge_book_files.delay(abandoned_id))
            duplicate = None
        if duplicate:
            return Response(
                {"error": "This book is already in the library.", "book_id": str(duplicate.id)},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            with transaction.atomic():
                book = Book.objects.create(
                    workspace=self.workspace,
                    owner=request.user,
                    visibility=visibility,
                    format=book_format,
                    original_filename=name,
                    file_size=data["size"],
                    file_hash=file_hash,
                    title=os.path.splitext(name)[0][:512],
                )
                key = f"{self.workspace.id}/library/{book.id}/original/{uuid.uuid4().hex}.{book_format}"
                asset = FileAsset.objects.create(
                    attributes={"name": name, "type": content_type, "size": data["size"]},
                    asset=key,
                    size=data["size"],
                    workspace=self.workspace,
                    created_by=request.user,
                    entity_type=FileAsset.EntityTypeContext.BOOK_FILE,
                    entity_identifier=str(book.id),
                )
                book.file = asset
                book.save(update_fields=["file"])
        except IntegrityError:
            # a concurrent upload of the same file won the race
            return Response({"error": "This book is already in the library."}, status=status.HTTP_409_CONFLICT)

        storage = S3Storage(request=request)
        # the storage policy enforces the exact size and type: nothing bigger can be uploaded
        upload = storage.generate_presigned_post(object_name=key, file_type=content_type, file_size=data["size"])
        if upload is None:
            book.delete(soft=False)
            asset.delete()
            return Response({"error": "The file storage is unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            {"book": BookSerializer(book, context=self.context(request, role)).data, "upload_data": upload},
            status=status.HTTP_201_CREATED,
        )


class BookDetailEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        return Response(BookDetailSerializer(book, context=self.detail_context(request, role, book)).data)

    def patch(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        serializer = BookUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if set(data) - {"archived"} and not permissions["can_edit"]:
            return _forbidden("Only the owner or a workspace admin can change this book.")
        if "archived" in data and not permissions["can_manage"]:
            return _forbidden("Only the owner or a workspace admin can archive this book.")
        if "visibility" in data and data["visibility"] != book.visibility and book.owner_id != request.user.id:
            return _forbidden("Only the owner can change who can see this book.")

        fields = ["updated_at", "updated_by"]
        for name in Book.EDITABLE_METADATA:
            if name in data:
                value = [a.strip() for a in data[name] if a.strip()] if name == "authors" else data[name].strip()
                setattr(book, name, value)
                if name not in book.edited_fields:
                    book.edited_fields = [*book.edited_fields, name]
                fields.append(name)
        if fields[2:]:
            fields.append("edited_fields")
        if "tags" in data:
            book.tags = data["tags"]
            fields.append("tags")
        if "visibility" in data:
            book.visibility = data["visibility"]
            fields.append("visibility")
        if "archived" in data:
            book.archived_at = timezone.now() if data["archived"] else None
            fields.append("archived_at")
        try:
            with transaction.atomic():
                book.save(update_fields=fields)
                if book.visibility == Book.VISIBILITY_PERSONAL:
                    # a personal book cannot stay on shared shelves
                    BookCollectionItem.objects.filter(
                        book=book, collection__visibility=Book.VISIBILITY_WORKSPACE
                    ).delete(soft=False)
        except IntegrityError:
            return Response({"error": "The same book is already in that library."}, status=status.HTTP_409_CONFLICT)
        return Response(BookDetailSerializer(book, context=self.detail_context(request, role, book)).data)

    def delete(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        if not permissions["can_manage"]:
            return _forbidden("Only the owner or a workspace admin can remove this book.")
        with transaction.atomic():
            # a running processing attempt becomes stale and cleans up after itself
            book.processing_token = None
            book.delete()
            transaction.on_commit(lambda: purge_book_files.delay(str(book.id)))
        return Response(status=status.HTTP_204_NO_CONTENT)


class BookUploadCompleteEndpoint(LibraryBaseEndpoint):
    """The browser finished uploading: check the stored object, then start processing."""

    def post(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None or book.owner_id != request.user.id:
            return _not_found()
        if book.status != Book.STATUS_UPLOADING:
            return Response(BookSerializer(book, context=self.context(request, role)).data)
        storage = S3Storage()
        metadata = storage.get_object_metadata(object_name=book.file.asset.name)
        if not metadata:
            return Response({"error": "The file has not been uploaded yet."}, status=status.HTTP_400_BAD_REQUEST)
        if metadata.get("ContentLength") != book.file_size:
            return Response(
                {"error": "The uploaded file does not match the announced size."}, status=status.HTTP_400_BAD_REQUEST
            )
        token = uuid.uuid4()
        with transaction.atomic():
            updated = Book.objects.filter(pk=book.id, status=Book.STATUS_UPLOADING).update(
                status=Book.STATUS_PROCESSING, processing_token=token, processing_attempts=0
            )
            FileAsset.objects.filter(pk=book.file_id).update(is_uploaded=True, storage_metadata=metadata)
            if updated:
                transaction.on_commit(lambda: process_book.delay(str(book.id), str(token)))
        book.refresh_from_db()
        return Response(BookSerializer(book, context=self.context(request, role)).data)


class BookReprocessEndpoint(LibraryBaseEndpoint):
    def post(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        if not permissions["can_manage"]:
            return _forbidden("Only the owner or a workspace admin can process this book again.")
        if book.status == Book.STATUS_UPLOADING:
            return Response({"error": "The book has not been uploaded yet."}, status=status.HTTP_400_BAD_REQUEST)
        token = uuid.uuid4()
        with transaction.atomic():
            Book.objects.filter(pk=book.id).update(
                status=Book.STATUS_PROCESSING, processing_token=token, processing_attempts=0, failure_reason=""
            )
            transaction.on_commit(lambda: process_book.delay(str(book.id), str(token)))
        book.refresh_from_db()
        return Response(BookSerializer(book, context=self.context(request, role)).data)


class BookDownloadEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None or not permissions["can_download"]:
            return _not_found()
        if book.file is None or not book.file.is_uploaded:
            return Response({"error": "The file is not available."}, status=status.HTTP_400_BAD_REQUEST)
        url = S3Storage(request=request).generate_presigned_url(
            object_name=book.file.asset.name,
            expiration=settings.BOOK_SIGNED_URL_EXPIRATION,
            disposition="attachment",
            filename=book.original_filename,
        )
        return Response({"url": url, "expires_in": settings.BOOK_SIGNED_URL_EXPIRATION})


class BookChapterListEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        chapters = BookChapter.objects.filter(book=book).order_by("index")
        return Response(BookChapterSerializer(chapters, many=True).data)


class BookChapterEndpoint(LibraryBaseEndpoint):
    """
    One chapter for the reader: sanitized HTML and CSS, with the book's images as short-lived signed
    links (resource placeholders are only resolved here, after the permission check).
    """

    def get(self, request, slug, book_id, index):
        role, error = self.access(request)
        if error:
            return error
        book, permissions = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        if book.status != Book.STATUS_READY or book.format != Book.FORMAT_EPUB:
            return Response({"error": "The book is not ready to read."}, status=status.HTTP_409_CONFLICT)
        chapter = BookChapter.objects.filter(book=book, index=index).first()
        if chapter is None:
            return _not_found()
        internal = S3Storage()
        try:
            document = chapter_document(book, chapter, storage=internal)
            stylesheet_keys = dict(
                BookResource.objects.filter(book=book, path__in=document.get("stylesheets", [])).values_list(
                    "path", "storage_key"
                )
            )
            css_parts = []
            for path in document.get("stylesheets", []):
                key = stylesheet_keys.get(path)
                if key:
                    body = internal.s3_client.get_object(Bucket=internal.aws_storage_bucket_name, Key=key)["Body"]
                    css_parts.append(body.read().decode("utf-8", "replace"))
            css_parts.append(document.get("css", ""))
        except (ClientError, BotoCoreError, ValueError):
            return Response({"error": "The chapter could not be loaded."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        html, css = document.get("html", ""), "\n".join(css_parts)
        paths = {unquote(m) for m in RESOURCE_PLACEHOLDER.findall(html + css)}
        keys = dict(BookResource.objects.filter(book=book, path__in=paths).values_list("path", "storage_key"))
        signer = S3Storage(request=request)
        urls = {
            path: signer.generate_presigned_url(
                object_name=key, expiration=settings.BOOK_SIGNED_URL_EXPIRATION, disposition="inline"
            )
            for path, key in keys.items()
        }

        def resolve(match):
            return urls.get(unquote(match.group(1))) or "about:blank"

        return Response(
            {
                "index": chapter.index,
                "title": chapter.title,
                "html": RESOURCE_PLACEHOLDER.sub(resolve, html),
                "css": RESOURCE_PLACEHOLDER.sub(resolve, css),
                "previous": BookChapter.objects.filter(book=book, index__lt=index)
                .order_by("-index")
                .values_list("index", flat=True)
                .first(),
                "next": BookChapter.objects.filter(book=book, index__gt=index)
                .order_by("index")
                .values_list("index", flat=True)
                .first(),
                "expires_in": settings.BOOK_SIGNED_URL_EXPIRATION,
            }
        )
