# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import os
import re

# Django imports
from django.conf import settings

# Third party imports
from rest_framework import serializers

# Module imports
from plane.db.models import Book, BookChapter
from plane.utils.book_access import book_permissions

from .base import BaseSerializer

BOOK_TYPES = {".epub": ("epub", "application/epub+zip"), ".pdf": ("pdf", "application/pdf")}


class BookUploadSerializer(serializers.Serializer):
    """Reserve an upload: the browser then sends the file straight to storage."""

    name = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1)
    sha256 = serializers.RegexField(r"^[0-9a-fA-F]{64}$")
    visibility = serializers.ChoiceField(
        choices=[Book.VISIBILITY_PERSONAL, Book.VISIBILITY_WORKSPACE], default=Book.VISIBILITY_PERSONAL
    )

    def validate_name(self, value):
        name = os.path.basename(value.replace("\\", "/")).strip()
        if os.path.splitext(name)[1].lower() not in BOOK_TYPES:
            raise serializers.ValidationError("Only EPUB and PDF files can be added to the library.")
        return re.sub(r"[\x00-\x1f]", "", name)[:255]

    def validate_size(self, value):
        if value > settings.BOOK_FILE_SIZE_LIMIT:
            limit = settings.BOOK_FILE_SIZE_LIMIT // (1024 * 1024)
            raise serializers.ValidationError(f"The file is larger than the {limit} MB limit for books.")
        return value

    def validate_sha256(self, value):
        return value.lower()


class BookSerializer(BaseSerializer):
    permissions = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()
    cover_thumbnail_url = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Book
        fields = [
            "id",
            "workspace",
            "owner",
            "visibility",
            "format",
            "original_filename",
            "file_size",
            "file_hash",
            "status",
            "status_label",
            "failure_reason",
            "processed_at",
            "title",
            "authors",
            "publisher",
            "language",
            "isbn",
            "published_date",
            "description",
            "subjects",
            "identifiers",
            "edited_fields",
            "chapter_count",
            "character_count",
            "page_count",
            "archived_at",
            "permissions",
            "cover_url",
            "cover_thumbnail_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _signed(self, key):
        storage = self.context.get("storage")
        if not key or storage is None:
            return None
        return storage.generate_presigned_url(
            object_name=key, expiration=settings.BOOK_SIGNED_URL_EXPIRATION, disposition="inline"
        )

    def get_permissions(self, book):
        return book_permissions(book, self.context["request"].user, role=self.context.get("role"))

    def get_cover_url(self, book):
        return self._signed(book.cover_key)

    def get_cover_thumbnail_url(self, book):
        return self._signed(book.cover_thumbnail_key)


class BookDetailSerializer(BookSerializer):
    class Meta(BookSerializer.Meta):
        fields = BookSerializer.Meta.fields + ["toc"]
        read_only_fields = fields


class BookUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=512, required=False, allow_blank=False)
    authors = serializers.ListField(
        # blank entries are dropped by the view
        child=serializers.CharField(max_length=255, allow_blank=True),
        max_length=50,
        required=False,
        allow_empty=True,
    )
    publisher = serializers.CharField(max_length=255, required=False, allow_blank=True)
    language = serializers.CharField(max_length=35, required=False, allow_blank=True)
    isbn = serializers.CharField(max_length=17, required=False, allow_blank=True)
    published_date = serializers.CharField(max_length=32, required=False, allow_blank=True)
    description = serializers.CharField(max_length=10000, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(choices=[Book.VISIBILITY_PERSONAL, Book.VISIBILITY_WORKSPACE], required=False)
    archived = serializers.BooleanField(required=False)


class BookChapterSerializer(BaseSerializer):
    class Meta:
        model = BookChapter
        fields = ["id", "index", "title", "href", "linear", "character_count"]
        read_only_fields = fields
