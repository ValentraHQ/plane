# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Process library books again, e.g. after the processing pipeline improved.

    python manage.py library_reprocess --outdated         # books made by an older processor version
    python manage.py library_reprocess --failed           # books whose processing failed
    python manage.py library_reprocess --book <id> [...]  # specific books
    add --dry-run to only list them
"""

# Python imports
import uuid

# Django imports
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Module imports
from plane.bgtasks.book_task import PROCESSOR_VERSION, process_book
from plane.db.models import Book


class Command(BaseCommand):
    help = "Queue library books for processing again"

    def add_arguments(self, parser):
        parser.add_argument(
            "--outdated", action="store_true", help=f"ready books older than processor v{PROCESSOR_VERSION}"
        )
        parser.add_argument("--failed", action="store_true", help="books whose processing failed")
        parser.add_argument("--book", nargs="+", default=[], help="book ids")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not (options["outdated"] or options["failed"] or options["book"]):
            raise CommandError("Choose --outdated, --failed or --book <id>.")
        books = Book.objects.none()
        if options["outdated"]:
            books |= Book.objects.filter(status=Book.STATUS_READY, processor_version__lt=PROCESSOR_VERSION)
        if options["failed"]:
            books |= Book.objects.filter(status=Book.STATUS_FAILED)
        if options["book"]:
            books |= Book.objects.filter(pk__in=options["book"]).exclude(status=Book.STATUS_UPLOADING)
        books = list(books.distinct())
        for book in books:
            self.stdout.write(f"{book.id}  v{book.processor_version}  {book.title or book.original_filename}")
            if options["dry_run"]:
                continue
            token = uuid.uuid4()
            with transaction.atomic():
                Book.objects.filter(pk=book.id).update(
                    status=Book.STATUS_PROCESSING, processing_token=token, processing_attempts=0, failure_reason=""
                )
                transaction.on_commit(lambda b=book.id, t=token: process_book.delay(str(b), str(t)))
        verb = "would be queued" if options["dry_run"] else "queued"
        self.stdout.write(f"{len(books)} book(s) {verb}.")
