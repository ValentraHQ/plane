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
from plane.db.models import Book, BookChapter, BookCollection, BookReadingState
from plane.utils.book_access import book_permissions, collection_permissions

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
    owner_detail = serializers.SerializerMethodField()
    my_reading = serializers.SerializerMethodField()

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
            "tags",
            "owner_detail",
            "my_reading",
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

    def get_my_reading(self, book):
        """The requesting user's own progress; views pass their states in the context (one query)."""
        state = (self.context.get("reading_states") or {}).get(book.id)
        if state is None:
            return {"progress": 0, "status": BookReadingState.STATUS_UNREAD, "last_opened_at": None}
        return {"progress": state.progress, "status": state.status, "last_opened_at": state.last_opened_at}

    def get_owner_detail(self, book):
        owner = book.owner
        return {"id": str(owner.id), "display_name": owner.display_name, "avatar_url": owner.avatar_url}

    def get_permissions(self, book):
        return book_permissions(book, self.context["request"].user, role=self.context.get("role"))

    def get_cover_url(self, book):
        return self._signed(book.cover_key)

    def get_cover_thumbnail_url(self, book):
        return self._signed(book.cover_thumbnail_key)


class BookDetailSerializer(BookSerializer):
    collection_ids = serializers.SerializerMethodField()

    class Meta(BookSerializer.Meta):
        fields = BookSerializer.Meta.fields + ["toc", "collection_ids"]
        read_only_fields = fields

    def get_collection_ids(self, book):
        """Collections of this book that the requesting user can see."""
        visible = self.context.get("visible_collection_ids")
        if visible is None:
            return []
        return [str(cid) for cid in book.collection_items.values_list("collection_id", flat=True) if cid in visible]


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
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50, allow_blank=True), max_length=50, required=False, allow_empty=True
    )

    def validate_tags(self, value):
        """Trimmed, without blanks, de-duplicated case-insensitively (first spelling wins)."""
        seen, tags = set(), []
        for tag in value:
            tag = " ".join(tag.split())
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                tags.append(tag)
        return tags


class BookChapterSerializer(BaseSerializer):
    class Meta:
        model = BookChapter
        fields = ["id", "index", "title", "href", "linear", "character_count"]
        read_only_fields = fields


class BookCollectionSerializer(BaseSerializer):
    permissions = serializers.SerializerMethodField()
    book_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = BookCollection
        fields = ["id", "workspace", "owner", "name", "description", "visibility", "sort_order", "book_count",
                  "permissions", "created_at", "updated_at"]  # fmt: skip
        read_only_fields = ["id", "workspace", "owner", "book_count", "permissions", "created_at", "updated_at"]

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("A collection needs a name.")
        return value

    def get_permissions(self, collection):
        return collection_permissions(collection, self.context["request"].user, role=self.context.get("role"))


class BookPositionSerializer(serializers.Serializer):
    chapter = serializers.IntegerField(min_value=0)
    offset = serializers.IntegerField(min_value=0, max_value=50_000_000)
    quote = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")


class BookReadingStateSerializer(serializers.Serializer):
    """PUT payload: any of position / progress / status; `opened` marks the book as just opened."""

    position = BookPositionSerializer(required=False)
    progress = serializers.FloatField(min_value=0, max_value=100, required=False)
    status = serializers.ChoiceField(
        choices=[BookReadingState.STATUS_UNREAD, BookReadingState.STATUS_READING, BookReadingState.STATUS_COMPLETED],
        required=False,
    )
    opened = serializers.BooleanField(required=False, default=False)


READER_DEFAULTS = {
    "font_family": "publisher",
    "font_size": 18,
    "line_height": 1.6,
    "margin": "normal",
    "theme": "light",
    "layout": "paginated",
}


class ReaderPreferencesSerializer(serializers.Serializer):
    font_family = serializers.ChoiceField(choices=["publisher", "serif", "sans", "mono", "dyslexic"], required=False)
    font_size = serializers.IntegerField(min_value=12, max_value=32, required=False)
    line_height = serializers.FloatField(min_value=1.0, max_value=2.4, required=False)
    margin = serializers.ChoiceField(choices=["narrow", "normal", "wide"], required=False)
    theme = serializers.ChoiceField(choices=["light", "dark", "sepia", "system"], required=False)
    layout = serializers.ChoiceField(choices=["paginated", "scroll"], required=False)
