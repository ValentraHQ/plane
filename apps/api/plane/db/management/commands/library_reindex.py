# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Rebuild the full-text index of library books (it is built automatically after processing).

    python manage.py library_reindex --missing          # ready EPUBs without an index
    python manage.py library_reindex --all              # every ready EPUB
    python manage.py library_reindex --book <id> [...]  # specific books
    add --dry-run to only list them; the work runs here, not on the worker
"""

# Django imports
from django.core.management.base import BaseCommand, CommandError

# Module imports
from plane.db.models import Book
from plane.utils.book_search import index_book_text


class Command(BaseCommand):
    help = "Rebuild the full-text index of library books"

    def add_arguments(self, parser):
        parser.add_argument("--missing", action="store_true", help="ready EPUBs that have no index")
        parser.add_argument("--all", action="store_true", help="every ready EPUB")
        parser.add_argument("--book", nargs="+", default=[], help="book ids")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not (options["missing"] or options["all"] or options["book"]):
            raise CommandError("Choose --missing, --all or --book <id>.")
        books = Book.objects.filter(status=Book.STATUS_READY, format=Book.FORMAT_EPUB)
        if options["book"]:
            books = books.filter(pk__in=options["book"])
        elif options["missing"]:
            books = books.filter(text_indexed_at__isnull=True)
        books = list(books.order_by("created_at"))
        for book in books:
            if options["dry_run"]:
                self.stdout.write(f"{book.id}  {book.title or book.original_filename}")
                continue
            chapters = index_book_text(book.id)
            self.stdout.write(f"{book.id}  {chapters} chapter(s)  {book.title or book.original_filename}")
        verb = "would be indexed" if options["dry_run"] else "indexed"
        self.stdout.write(f"{len(books)} book(s) {verb}.")
