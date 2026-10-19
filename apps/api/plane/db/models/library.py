# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Library: eBooks (EPUB, PDF) uploaded to a workspace.

The uploaded file is kept unchanged as a FileAsset. Processing (plane.bgtasks.book_task) writes
sanitized chapters and resources under a new storage prefix per attempt and switches the book to
it only when the attempt succeeds, so a failed or repeated run never leaves a half-processed book.
Access is resolved by plane.utils.book_access; keep authorization logic there, not here.
"""

# Django imports
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


class Book(BaseModel):
    # Who can see the book. PERSONAL: the owner only. WORKSPACE: every workspace admin and member.
    # Sharing with specific people or groups can be added as a new value backed by its own table,
    # resolved in plane.utils.book_access, without changing this one.
    VISIBILITY_PERSONAL = 0
    VISIBILITY_WORKSPACE = 1
    VISIBILITY_CHOICES = ((VISIBILITY_PERSONAL, "Personal"), (VISIBILITY_WORKSPACE, "Workspace"))

    FORMAT_EPUB = "epub"
    FORMAT_PDF = "pdf"
    FORMAT_CHOICES = ((FORMAT_EPUB, "EPUB"), (FORMAT_PDF, "PDF"))

    STATUS_UPLOADING = 0
    STATUS_PROCESSING = 1
    STATUS_READY = 2
    STATUS_FAILED = 3
    STATUS_CHOICES = (
        (STATUS_UPLOADING, "Uploading"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    )

    # metadata fields a user can edit; edits survive re-processing
    EDITABLE_METADATA = ("title", "authors", "publisher", "language", "isbn", "published_date", "description")

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="books")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="books")
    visibility = models.PositiveSmallIntegerField(choices=VISIBILITY_CHOICES, default=VISIBILITY_PERSONAL)
    format = models.CharField(max_length=8, choices=FORMAT_CHOICES)

    # the original upload, kept unchanged
    file = models.ForeignKey("db.FileAsset", on_delete=models.SET_NULL, null=True, related_name="+")
    original_filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField(default=0)
    # SHA-256 of the file, for duplicate detection; verified against the stored file when processed
    file_hash = models.CharField(max_length=64, db_index=True)

    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES, default=STATUS_UPLOADING)
    failure_reason = models.TextField(blank=True, default="")
    # identifies the current processing attempt; a stale or duplicate task run does nothing
    processing_token = models.UUIDField(null=True, blank=True)
    processing_attempts = models.PositiveIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)
    # version of the processing pipeline that produced the current output
    processor_version = models.PositiveIntegerField(default=0)
    # storage prefix of the current processed output (chapters, resources, cover)
    storage_prefix = models.CharField(max_length=255, blank=True, default="")

    # extracted metadata
    title = models.CharField(max_length=512, blank=True, default="")
    authors = models.JSONField(default=list, blank=True)
    publisher = models.CharField(max_length=255, blank=True, default="")
    language = models.CharField(max_length=35, blank=True, default="")
    isbn = models.CharField(max_length=17, blank=True, default="")
    published_date = models.CharField(max_length=32, blank=True, default="")
    description = models.TextField(blank=True, default="")
    subjects = models.JSONField(default=list, blank=True)
    identifiers = models.JSONField(default=list, blank=True)
    # free-form labels set by people who can edit the book (not by processing)
    tags = models.JSONField(default=list, blank=True)
    # metadata fields the user changed by hand; processing does not overwrite them
    edited_fields = models.JSONField(default=list, blank=True)

    cover_key = models.CharField(max_length=512, blank=True, default="")
    cover_thumbnail_key = models.CharField(max_length=512, blank=True, default="")
    # table of contents: [{"title", "chapter", "fragment", "children": [...]}]
    toc = models.JSONField(default=list, blank=True)
    chapter_count = models.PositiveIntegerField(default=0)
    character_count = models.BigIntegerField(default=0)
    page_count = models.PositiveIntegerField(null=True, blank=True)

    archived_at = models.DateTimeField(null=True, blank=True)
    # full-text search over the book's text: allowed by whoever can edit the book (on by default);
    # the text search configuration follows the book's language and is set when the text is indexed
    search_content = models.BooleanField(default=True)
    search_config = models.CharField(max_length=32, blank=True, default="simple")
    text_indexed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Book"
        verbose_name_plural = "Books"
        db_table = "books"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["workspace", "visibility"], name="book_workspace_visibility_idx"),
            models.Index(fields=["workspace", "owner"], name="book_workspace_owner_idx"),
        ]
        constraints = [
            # the same file once per personal library ...
            models.UniqueConstraint(
                fields=["workspace", "owner", "file_hash"],
                condition=Q(deleted_at__isnull=True, visibility=0),
                name="book_unique_personal_file_when_deleted_at_null",
            ),
            # ... and once in the workspace library
            models.UniqueConstraint(
                fields=["workspace", "file_hash"],
                condition=Q(deleted_at__isnull=True, visibility=1),
                name="book_unique_workspace_file_when_deleted_at_null",
            ),
        ]

    def __str__(self):
        return f"{self.title or self.original_filename} <{self.id}>"


class BookChapter(BaseModel):
    """A spine item of an EPUB: sanitized XHTML in storage, plain text here for search."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="book_chapters")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="chapters")
    index = models.PositiveIntegerField()
    # id of the spine item and its path inside the EPUB (stable across re-processing)
    spine_id = models.CharField(max_length=255)
    href = models.CharField(max_length=1024)
    title = models.CharField(max_length=512, blank=True, default="")
    content_key = models.CharField(max_length=1024)
    text = models.TextField(blank=True, default="")
    # to_tsvector(book.search_config, text), written by index_book_text after processing
    search_vector = SearchVectorField(null=True, blank=True)
    character_count = models.PositiveIntegerField(default=0)
    # spine items marked linear="no" (notes, pop-ups) are kept but skipped by default navigation
    linear = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Book Chapter"
        verbose_name_plural = "Book Chapters"
        db_table = "book_chapters"
        ordering = ("book", "index")
        constraints = [
            models.UniqueConstraint(
                fields=["book", "index"],
                condition=Q(deleted_at__isnull=True),
                name="book_chapter_unique_index_when_deleted_at_null",
            )
        ]
        indexes = [GinIndex(fields=["search_vector"], name="book_chapter_search_idx")]

    def __str__(self):
        return f"{self.book_id} #{self.index}"


class BookResource(BaseModel):
    """An image or stylesheet from inside an EPUB, stored after validation / sanitizing."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="book_resources")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="resources")
    # normalized path inside the EPUB
    path = models.CharField(max_length=1024)
    storage_key = models.CharField(max_length=1024)
    media_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Book Resource"
        verbose_name_plural = "Book Resources"
        db_table = "book_resources"
        constraints = [
            models.UniqueConstraint(
                fields=["book", "path"],
                condition=Q(deleted_at__isnull=True),
                name="book_resource_unique_path_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.book_id}:{self.path}"


class BookCollection(BaseModel):
    """
    A shelf of books. PERSONAL: the owner only. WORKSPACE: visible to every workspace admin and member,
    managed by its owner and workspace admins, and holds workspace books only.
    """

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="book_collections")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="book_collections")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    visibility = models.PositiveSmallIntegerField(choices=Book.VISIBILITY_CHOICES, default=Book.VISIBILITY_PERSONAL)
    sort_order = models.FloatField(default=65535)

    class Meta:
        verbose_name = "Book Collection"
        verbose_name_plural = "Book Collections"
        db_table = "book_collections"
        ordering = ("sort_order", "name")

    def __str__(self):
        return f"{self.name} <{self.id}>"


class BookCollectionItem(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="book_collection_items")
    collection = models.ForeignKey(BookCollection, on_delete=models.CASCADE, related_name="items")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="collection_items")
    sort_order = models.FloatField(default=65535)

    class Meta:
        verbose_name = "Book Collection Item"
        verbose_name_plural = "Book Collection Items"
        db_table = "book_collection_items"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "book"],
                condition=Q(deleted_at__isnull=True),
                name="book_collection_item_unique_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.collection_id}:{self.book_id}"


class BookReadingState(BaseModel):
    """
    One person's reading of one book: where they are, how far, and whether they finished it.
    Private to that person. `position` is the reader's anchor:
    {"chapter": <index>, "offset": <character offset in the chapter's text>, "quote": <text at that point>}.
    """

    STATUS_UNREAD = 0
    STATUS_READING = 1
    STATUS_COMPLETED = 2
    STATUS_CHOICES = ((STATUS_UNREAD, "Unread"), (STATUS_READING, "Reading"), (STATUS_COMPLETED, "Completed"))

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="book_reading_states")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reading_states")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="book_reading_states")
    position = models.JSONField(default=dict, blank=True)
    # 0..100, from the reader
    progress = models.FloatField(default=0)
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES, default=STATUS_UNREAD)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Book Reading State"
        verbose_name_plural = "Book Reading States"
        db_table = "book_reading_states"
        ordering = ("-last_opened_at",)
        indexes = [models.Index(fields=["user", "workspace", "last_opened_at"], name="book_reading_recent_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "user"],
                condition=Q(deleted_at__isnull=True),
                name="book_reading_state_unique_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.user_id}:{self.book_id} {self.progress:.0f}%"


class ReaderPreferences(BaseModel):
    """A person's reader settings (font, size, spacing, theme, layout), the same on every device."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reader_preferences")
    preferences = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Reader Preferences"
        verbose_name_plural = "Reader Preferences"
        db_table = "reader_preferences"

    def __str__(self):
        return f"reader preferences of {self.user_id}"


class BookAnnotation(BaseModel):
    """
    A highlight, note or bookmark in a book. Private to its author unless shared; sharing is only
    possible on workspace books, where every reader of the book can see it.

    The anchor follows the reader's positions: chapter index, start / end character offsets into the
    chapter's text, and the quoted text with a little context on each side, so the passage can be found
    again if offsets drift (e.g. after the book is processed again).
    """

    KIND_HIGHLIGHT = "highlight"
    KIND_NOTE = "note"
    KIND_BOOKMARK = "bookmark"
    KIND_CHOICES = ((KIND_HIGHLIGHT, "Highlight"), (KIND_NOTE, "Note"), (KIND_BOOKMARK, "Bookmark"))
    COLORS = ("yellow", "green", "blue", "pink", "purple")
    VISIBILITY_PRIVATE = 0
    VISIBILITY_SHARED = 1
    VISIBILITY_CHOICES = ((VISIBILITY_PRIVATE, "Private"), (VISIBILITY_SHARED, "Shared"))

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="book_annotations")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="annotations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="book_annotations")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_HIGHLIGHT)
    color = models.CharField(max_length=16, blank=True, default="yellow")
    chapter = models.PositiveIntegerField()
    start_offset = models.PositiveIntegerField()
    end_offset = models.PositiveIntegerField()
    quote = models.TextField(blank=True, default="")
    prefix = models.CharField(max_length=64, blank=True, default="")
    suffix = models.CharField(max_length=64, blank=True, default="")
    note = models.TextField(blank=True, default="")
    visibility = models.PositiveSmallIntegerField(choices=VISIBILITY_CHOICES, default=VISIBILITY_PRIVATE)

    class Meta:
        verbose_name = "Book Annotation"
        verbose_name_plural = "Book Annotations"
        db_table = "book_annotations"
        ordering = ("chapter", "start_offset", "created_at")
        indexes = [
            models.Index(fields=["book", "user"], name="book_annotation_book_user_idx"),
            models.Index(fields=["book", "visibility"], name="book_annotation_shared_idx"),
            models.Index(fields=["user", "workspace", "created_at"], name="book_annot_user_recent_idx"),
        ]

    def __str__(self):
        return f"{self.kind} {self.book_id} #{self.chapter}:{self.start_offset}"


class BookLink(BaseModel):
    """
    A link between a book and a page (wiki or project), a project or a work item. A link is shown
    only to people who can see both ends, so it never reveals a book or a target to anyone else.

    `origin` tells pages created from the book (with the passage they started from) apart from
    links added by hand.
    """

    TARGET_PAGE = "page"
    TARGET_PROJECT = "project"
    TARGET_ISSUE = "issue"
    TARGET_CHOICES = ((TARGET_PAGE, "Page"), (TARGET_PROJECT, "Project"), (TARGET_ISSUE, "Work item"))
    ORIGIN_LINKED = "linked"
    ORIGIN_CREATED = "created"
    ORIGIN_CHOICES = ((ORIGIN_LINKED, "Linked"), (ORIGIN_CREATED, "Created from the book"))

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="book_links")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="links")
    target_type = models.CharField(max_length=16, choices=TARGET_CHOICES)
    page = models.ForeignKey("db.Page", null=True, blank=True, on_delete=models.CASCADE, related_name="book_links")
    project = models.ForeignKey(
        "db.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="book_links"
    )
    issue = models.ForeignKey("db.Issue", null=True, blank=True, on_delete=models.CASCADE, related_name="book_links")
    origin = models.CharField(max_length=16, choices=ORIGIN_CHOICES, default=ORIGIN_LINKED)
    # where in the book a created page came from
    chapter = models.PositiveIntegerField(null=True, blank=True)
    start_offset = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Book Link"
        verbose_name_plural = "Book Links"
        db_table = "book_links"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["book", "page"],
                condition=Q(deleted_at__isnull=True, page__isnull=False),
                name="book_link_unique_page",
            ),
            models.UniqueConstraint(
                fields=["book", "project"],
                condition=Q(deleted_at__isnull=True, project__isnull=False),
                name="book_link_unique_project",
            ),
            models.UniqueConstraint(
                fields=["book", "issue"],
                condition=Q(deleted_at__isnull=True, issue__isnull=False),
                name="book_link_unique_issue",
            ),
            models.CheckConstraint(
                condition=(
                    Q(target_type="page", page__isnull=False, project__isnull=True, issue__isnull=True)
                    | Q(target_type="project", page__isnull=True, project__isnull=False, issue__isnull=True)
                    | Q(target_type="issue", page__isnull=True, project__isnull=True, issue__isnull=False)
                ),
                name="book_link_one_target",
            ),
        ]
        indexes = [
            models.Index(fields=["page"], name="book_link_page_idx"),
            models.Index(fields=["issue"], name="book_link_issue_idx"),
            models.Index(fields=["project"], name="book_link_project_idx"),
        ]

    def __str__(self):
        return f"{self.book_id} -> {self.target_type}"
