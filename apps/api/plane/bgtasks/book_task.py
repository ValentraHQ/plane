# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Library book processing.

Each processing attempt has a token (Book.processing_token). A task whose token is no longer the
book's current one does nothing, so duplicate deliveries and stale retries are harmless. An attempt
writes only under its own storage prefix and switches the book to it in one transaction (chapters,
resources and metadata together); a failed attempt deletes what it wrote, and the previous output
is removed only after the switch is committed. Invalid books (BookError) fail at once; storage and
network errors are retried with backoff.
"""

# Python imports
import hashlib
import io
import json
import logging
import os
import tempfile
from datetime import timedelta

# Django imports
from django.conf import settings
from django.db import transaction
from django.utils import timezone

# Third party imports
from botocore.exceptions import BotoCoreError, ClientError
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

# Module imports
from plane.db.models import Book, BookChapter, BookResource, FileAsset
from plane.settings.storage import S3Storage
from plane.utils.exception_logger import log_exception
from plane.utils.library.archive import ArchiveLimits
from plane.utils.library.epub import IMAGE_TYPES, EpubBook, make_cover
from plane.utils.library.errors import BookError
from plane.utils.library.pdf import read_pdf

logger = logging.getLogger("plane.worker")

# bump when processing changes in a way that should apply to existing books (see `reprocess`)
PROCESSOR_VERSION = 1
COVER_SIZE = (1200, 1800)
THUMBNAIL_SIZE = (300, 450)
TRANSIENT_ERRORS = (ClientError, BotoCoreError, ConnectionError, TimeoutError)


def book_prefix(book):
    return f"{book.workspace_id}/library/{book.id}/"


def processed_prefix(book, token):
    return f"{book_prefix(book)}processed/{token}/"


def archive_limits():
    return ArchiveLimits(
        max_entries=settings.BOOK_MAX_ARCHIVE_ENTRIES,
        max_unpacked=settings.BOOK_MAX_UNPACKED_SIZE,
        max_entry=settings.BOOK_MAX_ENTRY_SIZE,
        max_ratio=settings.BOOK_MAX_COMPRESSION_RATIO,
    )


def delete_keys(storage, keys):
    keys = list(keys)
    for start in range(0, len(keys), 1000):
        storage.delete_files(keys[start : start + 1000])


def delete_prefix(storage, prefix):
    """Delete every object under a prefix (paginated, 1000 per request)."""
    if not prefix:
        return
    paginator = storage.s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=storage.aws_storage_bucket_name, Prefix=prefix):
        keys = [item["Key"] for item in page.get("Contents", [])]
        if keys:
            delete_keys(storage, keys)


class _Uploader:
    """Uploads processed files and remembers them, so a failed attempt can remove its output."""

    def __init__(self, storage, prefix):
        self.storage, self.prefix, self.keys = storage, prefix, []

    def put(self, name, data, content_type):
        key = f"{self.prefix}{name}"
        if not self.storage.upload_file(io.BytesIO(data), key, content_type=content_type, extra_args={}):
            raise ClientError({"Error": {"Code": "UploadFailed", "Message": key}}, "PutObject")
        self.keys.append(key)
        return key

    def rollback(self):
        if self.keys:
            delete_keys(self.storage, self.keys)
            self.keys = []


def _download_original(storage, book, target):
    key = book.file.asset.name
    head = storage.s3_client.head_object(Bucket=storage.aws_storage_bucket_name, Key=key)
    if head.get("ContentLength", 0) > settings.BOOK_FILE_SIZE_LIMIT:
        raise BookError("The file is larger than the book size limit.")
    storage.s3_client.download_fileobj(storage.aws_storage_bucket_name, key, target)
    target.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: target.read(1024 * 1024), b""):
        digest.update(chunk)
    target.seek(0)
    if digest.hexdigest() != book.file_hash:
        raise BookError("The uploaded file does not match its checksum. Please upload it again.")


def _process_epub(file_obj, book, uploader):
    epub = EpubBook(file_obj, archive_limits(), settings.BOOK_MAX_CHAPTERS)
    try:
        chapters, resources = [], []
        for chapter in epub.chapters():
            key = uploader.put(
                f"chapters/{chapter.index:05d}.json", chapter.content.encode("utf-8"), "application/json"
            )
            chapters.append(
                BookChapter(
                    workspace_id=book.workspace_id,
                    book_id=book.id,
                    index=chapter.index,
                    spine_id=chapter.spine_id,
                    href=chapter.href,
                    title=chapter.title,
                    content_key=key,
                    text=chapter.text,
                    character_count=len(chapter.text),
                    linear=chapter.linear,
                )
            )
        for resource in epub.resources():
            extension = "css" if resource.media_type == "text/css" else IMAGE_TYPES[resource.media_type]
            name = f"res/{hashlib.sha256(resource.path.encode()).hexdigest()[:32]}.{extension}"
            key = uploader.put(name, resource.data, resource.media_type)
            resources.append(
                BookResource(
                    workspace_id=book.workspace_id,
                    book_id=book.id,
                    path=resource.path,
                    storage_key=key,
                    media_type=resource.media_type,
                    size=len(resource.data),
                )
            )
        cover = {}
        cover_data = epub.cover_image()
        if cover_data:
            try:
                cover["cover_key"] = uploader.put("cover.jpg", make_cover(cover_data, COVER_SIZE), "image/jpeg")
                cover["cover_thumbnail_key"] = uploader.put(
                    "cover-thumb.jpg", make_cover(cover_data, THUMBNAIL_SIZE), "image/jpeg"
                )
            except (OSError, ValueError, SyntaxError):
                # a broken cover is not a reason to reject the book
                cover = {}
        metadata = vars(epub.metadata)
        fields = {
            **cover,
            "toc": epub.toc,
            "chapter_count": len(chapters),
            "character_count": sum(c.character_count for c in chapters),
            "page_count": None,
        }
        return metadata, fields, chapters, resources
    finally:
        epub.close()


def _process_pdf(file_obj):
    pdf = read_pdf(file_obj)
    metadata = {"title": pdf.title, "authors": pdf.authors, "description": pdf.description}
    fields = {"page_count": pdf.page_count, "toc": [], "chapter_count": 0, "character_count": 0}
    return metadata, fields, [], []


def _fail(book_id, token, reason, uploader=None):
    if uploader:
        uploader.rollback()
    updated = Book.objects.filter(pk=book_id, processing_token=token).update(
        status=Book.STATUS_FAILED, failure_reason=reason[:2000], updated_at=timezone.now()
    )
    logger.info("book %s processing failed: %s", book_id, reason[:200])
    return "failed" if updated else "stale"


@shared_task(bind=True, acks_late=True, soft_time_limit=900, time_limit=960)
def process_book(self, book_id, token):
    book = Book.objects.filter(pk=book_id).select_related("file").first()
    if book is None or str(book.processing_token) != str(token) or book.status != Book.STATUS_PROCESSING:
        return "stale"
    if book.file is None or not book.file.is_uploaded:
        return _fail(book_id, token, "The book file is missing.")

    storage = S3Storage()
    uploader = _Uploader(storage, processed_prefix(book, token))
    try:
        with tempfile.TemporaryFile() as original:
            _download_original(storage, book, original)
            if book.format == Book.FORMAT_EPUB:
                metadata, fields, chapters, resources = _process_epub(original, book, uploader)
            else:
                metadata, fields, chapters, resources = _process_pdf(original)

        with transaction.atomic():
            current = Book.objects.select_for_update().filter(pk=book_id).first()
            if current is None or str(current.processing_token) != str(token):
                # deleted, or a newer attempt took over while this one ran
                transaction.on_commit(uploader.rollback)
                return "stale"
            old_prefix = current.storage_prefix
            BookChapter.all_objects.filter(book_id=book_id).delete()
            BookResource.all_objects.filter(book_id=book_id).delete()
            BookChapter.objects.bulk_create(chapters, batch_size=200)
            BookResource.objects.bulk_create(resources, batch_size=500)
            for name in Book.EDITABLE_METADATA:
                if name not in (current.edited_fields or []) and name in metadata:
                    setattr(current, name, metadata[name])
            for name in ("subjects", "identifiers"):
                if name in metadata:
                    setattr(current, name, metadata[name])
            if not current.title:
                current.title = os.path.splitext(current.original_filename)[0][:512]
            current.cover_key = fields.pop("cover_key", "")
            current.cover_thumbnail_key = fields.pop("cover_thumbnail_key", "")
            for name, value in fields.items():
                setattr(current, name, value)
            current.status = Book.STATUS_READY
            current.failure_reason = ""
            current.storage_prefix = uploader.prefix
            current.processed_at = timezone.now()
            current.processor_version = PROCESSOR_VERSION
            current.save(disable_auto_set_user=True)
            if old_prefix and old_prefix != uploader.prefix:
                transaction.on_commit(lambda: delete_prefix(storage, old_prefix))
        return "ready"
    except BookError as error:
        return _fail(book_id, token, str(error), uploader)
    except SoftTimeLimitExceeded:
        return _fail(book_id, token, "Processing took too long. The book may be too large or damaged.", uploader)
    except TRANSIENT_ERRORS as error:
        uploader.rollback()
        Book.objects.filter(pk=book_id, processing_token=token).update(processing_attempts=book.processing_attempts + 1)
        if self.request.retries >= settings.BOOK_PROCESSING_MAX_RETRIES:
            log_exception(error)
            return _fail(book_id, token, "The file storage was unavailable. Try processing the book again later.")
        raise self.retry(exc=error, countdown=30 * 2**self.request.retries)
    except Exception as error:
        log_exception(error)
        return _fail(book_id, token, "The book could not be processed because of an unexpected error.", uploader)


# a reservation that was never completed (browser closed, upload failed) is removed after this long
ABANDONED_UPLOAD_AGE = timedelta(days=1)


@shared_task
def delete_abandoned_uploads():
    """Delete books whose upload was reserved but never completed, with anything already stored."""
    stale = Book.objects.filter(status=Book.STATUS_UPLOADING, created_at__lt=timezone.now() - ABANDONED_UPLOAD_AGE)
    removed = 0
    for book in stale:
        book.delete()
        purge_book_files.delay(str(book.id))
        removed += 1
    return removed


@shared_task
def purge_book_files(book_id):
    """Remove every stored file of a deleted book (original, processed output, covers)."""
    book = Book.all_objects.filter(pk=book_id).first()
    if book is None or book.deleted_at is None:
        return
    try:
        delete_prefix(S3Storage(), book_prefix(book))
        if book.file_id:
            FileAsset.objects.filter(pk=book.file_id).update(is_deleted=True, deleted_at=timezone.now())
    except TRANSIENT_ERRORS as error:
        log_exception(error)


def chapter_document(book, chapter, storage=None):
    """The stored reader document of a chapter: {"html", "stylesheets", "css"}."""
    storage = storage or S3Storage()
    body = storage.s3_client.get_object(Bucket=storage.aws_storage_bucket_name, Key=chapter.content_key)["Body"]
    return json.loads(body.read())
