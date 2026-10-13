# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Storage used by the library, per workspace.

    python manage.py library_storage_report            # from the database (fast)
    python manage.py library_storage_report --storage  # measure the bucket itself (lists every object)
"""

# Django imports
from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.db.models.functions import Length

# Module imports
from plane.db.models import Book, BookChapter, BookResource, Workspace


def _mb(value):
    return f"{(value or 0) / (1024 * 1024):,.1f} MB"


class Command(BaseCommand):
    help = "Report the storage used by library books, per workspace"

    def add_arguments(self, parser):
        parser.add_argument("--storage", action="store_true", help="measure the bucket instead of estimating")

    def handle(self, *args, **options):
        books = Book.objects.values("workspace_id").annotate(count=Count("id"), originals=Sum("file_size"))
        if not books:
            self.stdout.write("No books in any workspace.")
            return
        slugs = dict(Workspace.objects.values_list("id", "slug"))
        resources = dict(
            BookResource.objects.values("workspace_id").annotate(total=Sum("size")).values_list("workspace_id", "total")
        )
        text = dict(
            BookChapter.objects.values("workspace_id")
            .annotate(total=Sum(Length("text")))
            .values_list("workspace_id", "total")
        )
        measured = self._measure() if options["storage"] else {}
        total = 0
        for row in books:
            workspace = row["workspace_id"]
            line = (
                f"{slugs.get(workspace, workspace)}: {row['count']} books, originals {_mb(row['originals'])}, "
                f"images/styles {_mb(resources.get(workspace))}, chapter text in database {_mb(text.get(workspace))}"
            )
            if options["storage"]:
                line += f", in storage {_mb(measured.get(str(workspace)))}"
                total += measured.get(str(workspace), 0)
            else:
                total += (row["originals"] or 0) + (resources.get(workspace) or 0)
            self.stdout.write(line)
        label = "measured in storage" if options["storage"] else "estimated in storage (without chapter files)"
        self.stdout.write(f"Total {label}: {_mb(total)}")

    def _measure(self):
        from plane.settings.storage import S3Storage

        storage = S3Storage()
        paginator = storage.s3_client.get_paginator("list_objects_v2")
        sizes = {}
        for page in paginator.paginate(Bucket=storage.aws_storage_bucket_name):
            for item in page.get("Contents", []):
                parts = item["Key"].split("/", 2)
                if len(parts) == 3 and parts[1] == "library":
                    sizes[parts[0]] = sizes.get(parts[0], 0) + item["Size"]
        return sizes
