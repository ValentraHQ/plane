# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Book processing task: results, failures, retries, stale runs and re-processing."""

# Python imports
import uuid

# Third party imports
import pytest

# Module imports
from plane.bgtasks import book_task
from plane.db.models import Book, BookChapter, BookResource, FileAsset
from plane.tests.library_helpers import FakeStorage, make_epub, make_pdf, sha256


@pytest.fixture
def storage(monkeypatch):
    store = {}
    fake = FakeStorage(store)
    monkeypatch.setattr(book_task, "S3Storage", lambda *args, **kwargs: fake)
    return fake


def make_book(workspace, owner, storage, data, book_format="epub", file_hash=None):
    book = Book.objects.create(
        workspace=workspace,
        owner=owner,
        format=book_format,
        original_filename=f"book.{book_format}",
        file_size=len(data),
        file_hash=file_hash or sha256(data),
        status=Book.STATUS_PROCESSING,
        processing_token=uuid.uuid4(),
    )
    key = f"{workspace.id}/library/{book.id}/original/file.{book_format}"
    storage.store[key] = {"data": data, "type": "application/octet-stream"}
    book.file = FileAsset.objects.create(
        asset=key, workspace=workspace, entity_type="BOOK_FILE", is_uploaded=True, size=len(data)
    )
    book.save(update_fields=["file"])
    return book


def run(book, token=None):
    return book_task.process_book.run(str(book.id), str(token or book.processing_token))


def processed_keys(storage, book):
    return {k for k in storage.store if k.startswith(f"{book.workspace_id}/library/{book.id}/processed/")}


@pytest.mark.unit
@pytest.mark.django_db
class TestProcessBook:
    def test_epub_is_processed(self, workspace, create_user, storage, django_capture_on_commit_callbacks):
        original = make_epub()
        book = make_book(workspace, create_user, storage, original)
        with django_capture_on_commit_callbacks(execute=True):
            assert run(book) == "ready"
        book.refresh_from_db()
        assert book.status == Book.STATUS_READY and book.failure_reason == ""
        assert book.title == "The Test Book" and book.authors == ["Ada Author"] and book.isbn == "9780306406157"
        assert book.chapter_count == 2 and book.processor_version == book_task.PROCESSOR_VERSION
        assert [c.title for c in BookChapter.objects.filter(book=book).order_by("index")] == [
            "Chapter One",
            "Chapter Two",
        ]
        assert set(BookResource.objects.filter(book=book).values_list("path", flat=True)) == {
            "OEBPS/style.css",
            "OEBPS/images/fig.png",
        }
        assert book.cover_key and book.cover_thumbnail_key
        # all processed output lives under this attempt's prefix; the original is untouched
        assert all(k.startswith(book.storage_prefix) for k in processed_keys(storage, book))
        assert storage.store[book.file.asset.name]["data"] == original

    def test_pdf_is_processed(self, workspace, create_user, storage, django_capture_on_commit_callbacks):
        book = make_book(workspace, create_user, storage, make_pdf(), book_format="pdf")
        with django_capture_on_commit_callbacks(execute=True):
            assert run(book) == "ready"
        book.refresh_from_db()
        assert (book.title, book.authors, book.page_count) == ("A PDF Book", ["Pat Writer"], 3)
        assert book.chapter_count == 0 and not processed_keys(storage, book)

    def test_invalid_book_fails_cleanly(self, workspace, create_user, storage):
        book = make_book(workspace, create_user, storage, make_epub(mimetype=b"text/plain"))
        assert run(book) == "failed"
        book.refresh_from_db()
        assert book.status == Book.STATUS_FAILED and "mimetype" in book.failure_reason
        assert not processed_keys(storage, book) and not BookChapter.objects.filter(book=book).exists()

    def test_unsafe_book_fails_and_leaves_nothing(self, workspace, create_user, storage):
        # the second chapter is rejected after the first was already uploaded
        chapter = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><html><body>&a;</body></html>'
        book = make_book(workspace, create_user, storage, make_epub(**{"OEBPS/text/ch2.xhtml": chapter}))
        assert run(book) == "failed"
        assert not processed_keys(storage, book)

    def test_checksum_mismatch(self, workspace, create_user, storage):
        book = make_book(workspace, create_user, storage, make_epub(), file_hash="0" * 64)
        assert run(book) == "failed"
        book.refresh_from_db()
        assert "checksum" in book.failure_reason

    def test_stale_token_does_nothing(self, workspace, create_user, storage):
        book = make_book(workspace, create_user, storage, make_epub())
        assert run(book, token=uuid.uuid4()) == "stale"
        book.refresh_from_db()
        assert book.status == Book.STATUS_PROCESSING and not processed_keys(storage, book)

    def test_duplicate_delivery_is_harmless(self, workspace, create_user, storage, django_capture_on_commit_callbacks):
        book = make_book(workspace, create_user, storage, make_epub())
        with django_capture_on_commit_callbacks(execute=True):
            assert run(book) == "ready"
            # the same message delivered again: the book is no longer processing
            assert run(book) == "stale"
        assert BookChapter.objects.filter(book=book).count() == 2

    def test_newer_attempt_wins(self, workspace, create_user, storage, monkeypatch, django_capture_on_commit_callbacks):
        book = make_book(workspace, create_user, storage, make_epub())
        old_token, new_token = book.processing_token, uuid.uuid4()
        real = book_task._process_epub

        def slow_process(*args):
            result = real(*args)
            # a re-process request arrives while this attempt is running
            Book.objects.filter(pk=book.id).update(processing_token=new_token)
            return result

        monkeypatch.setattr(book_task, "_process_epub", slow_process)
        with django_capture_on_commit_callbacks(execute=True):
            assert run(book, token=old_token) == "stale"
        assert not processed_keys(storage, book) and not BookChapter.objects.filter(book=book).exists()

    def test_reprocessing_replaces_output_and_keeps_edits(
        self, workspace, create_user, storage, django_capture_on_commit_callbacks
    ):
        book = make_book(workspace, create_user, storage, make_epub())
        with django_capture_on_commit_callbacks(execute=True):
            run(book)
        book.refresh_from_db()
        first_prefix = book.storage_prefix
        Book.objects.filter(pk=book.id).update(
            title="My Title", edited_fields=["title"], status=Book.STATUS_PROCESSING, processing_token=uuid.uuid4()
        )
        book.refresh_from_db()
        with django_capture_on_commit_callbacks(execute=True):
            assert run(book) == "ready"
        book.refresh_from_db()
        assert book.title == "My Title" and book.publisher == "Valentra Press"
        assert book.storage_prefix != first_prefix
        assert not [k for k in storage.store if k.startswith(first_prefix)]
        assert BookChapter.all_objects.filter(book=book).count() == 2
        assert BookResource.all_objects.filter(book=book).count() == 2

    def test_transient_storage_error_retries_and_rolls_back(self, workspace, create_user, storage, monkeypatch):
        book = make_book(workspace, create_user, storage, make_epub())
        storage.fail_after = 1

        class Retry(Exception):
            pass

        monkeypatch.setattr(book_task.process_book, "retry", lambda **kwargs: Retry())
        with pytest.raises(Retry):
            run(book)
        book.refresh_from_db()
        assert book.status == Book.STATUS_PROCESSING and book.processing_attempts == 1
        assert not processed_keys(storage, book)

    def test_deleted_book_during_processing(
        self, workspace, create_user, storage, monkeypatch, django_capture_on_commit_callbacks
    ):
        book = make_book(workspace, create_user, storage, make_epub())
        real = book_task._process_epub

        def delete_meanwhile(*args):
            result = real(*args)
            Book.objects.filter(pk=book.id).update(deleted_at="2026-01-01T00:00:00Z")
            return result

        monkeypatch.setattr(book_task, "_process_epub", delete_meanwhile)
        with django_capture_on_commit_callbacks(execute=True):
            assert run(book) == "stale"
        assert not processed_keys(storage, book)

    def test_purge_removes_every_file(self, workspace, create_user, storage, django_capture_on_commit_callbacks):
        book = make_book(workspace, create_user, storage, make_epub())
        with django_capture_on_commit_callbacks(execute=True):
            run(book)
        book.refresh_from_db()
        book.delete()
        book_task.purge_book_files.run(str(book.id))
        assert not [k for k in storage.store if k.startswith(f"{workspace.id}/library/{book.id}/")]
        assert FileAsset.all_objects.get(pk=book.file_id).is_deleted
