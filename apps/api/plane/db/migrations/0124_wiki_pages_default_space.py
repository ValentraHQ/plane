# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations

from plane.db.wiki_space_migration import migrate_wiki_pages_to_default_space


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0123_wiki_spaces"),
    ]

    operations = [
        # Reverse is a no-op: rolling back 0123 removes Page.space and the space tables.
        migrations.RunPython(migrate_wiki_pages_to_default_space, migrations.RunPython.noop),
    ]
