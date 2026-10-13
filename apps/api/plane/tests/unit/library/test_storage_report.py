# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from io import StringIO

# Third party imports
import pytest
from django.core.management import call_command

# Module imports
from plane.db.models import Book, BookChapter, BookResource


@pytest.mark.unit
@pytest.mark.django_db
def test_library_storage_report(workspace, create_user):
    book = Book.objects.create(
        workspace=workspace,
        owner=create_user,
        format="epub",
        original_filename="a.epub",
        file_hash="a" * 64,
        file_size=3 * 1024 * 1024,
    )
    BookResource.objects.create(
        workspace=workspace, book=book, path="a.png", storage_key="k", media_type="image/png", size=1024 * 1024
    )
    BookChapter.objects.create(
        workspace=workspace, book=book, index=0, spine_id="c", href="c", content_key="k", text="x" * 1000
    )
    out = StringIO()
    call_command("library_storage_report", stdout=out)
    report = out.getvalue()
    assert f"{workspace.slug}: 1 books, originals 3.0 MB, images/styles 1.0 MB" in report
    assert "Total estimated in storage (without chapter files): 4.0 MB" in report


@pytest.mark.unit
@pytest.mark.django_db
def test_library_storage_report_without_books():
    out = StringIO()
    call_command("library_storage_report", stdout=out)
    assert "No books" in out.getvalue()


@pytest.mark.unit
@pytest.mark.django_db
def test_library_reprocess_outdated(workspace, create_user, monkeypatch, django_capture_on_commit_callbacks):
    from plane.bgtasks import book_task

    queued = []
    monkeypatch.setattr(book_task.process_book, "delay", lambda *args: queued.append(args))
    old = Book.objects.create(
        workspace=workspace,
        owner=create_user,
        format="epub",
        original_filename="a.epub",
        file_hash="a" * 64,
        status=Book.STATUS_READY,
        processor_version=1,
    )
    Book.objects.create(
        workspace=workspace,
        owner=create_user,
        format="epub",
        original_filename="b.epub",
        file_hash="b" * 64,
        status=Book.STATUS_READY,
        processor_version=book_task.PROCESSOR_VERSION,
    )
    out = StringIO()
    call_command("library_reprocess", "--outdated", "--dry-run", stdout=out)
    assert "1 book(s) would be queued" in out.getvalue() and queued == []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("library_reprocess", "--outdated", stdout=StringIO())
    old.refresh_from_db()
    assert old.status == Book.STATUS_PROCESSING and queued == [(str(old.id), str(old.processing_token))]
