# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Data migration: put every existing workspace wiki page into a "General" space.

Kept outside the migration file so tests can run exactly this code. It only sets
Page.space (a bulk UPDATE): content, hierarchy, access, ownership, versions,
logs and updated_at are untouched. Soft-deleted pages are included so restoring
them later keeps a valid space. Safe to run more than once.
"""

DEFAULT_SPACE_NAME = "General"
DEFAULT_SPACE_IDENTIFIER = "GENERAL"
DEFAULT_SPACE_DESCRIPTION = "Pages created before documentation spaces were introduced."


def _unique_identifier(WikiSpace, workspace_id):
    """GENERAL, or GENERAL2, GENERAL3... if a live space already uses it."""
    taken = set(
        WikiSpace._base_manager.filter(workspace_id=workspace_id, deleted_at__isnull=True).values_list(
            "identifier", flat=True
        )
    )
    candidate, n = DEFAULT_SPACE_IDENTIFIER, 1
    while candidate in taken:
        n += 1
        candidate = f"{DEFAULT_SPACE_IDENTIFIER}{n}"
    return candidate


def migrate_wiki_pages_to_default_space(apps, schema_editor=None):
    """Assign every wiki page without a space to its workspace's default space."""
    Page = apps.get_model("db", "Page")
    WikiSpace = apps.get_model("db", "WikiSpace")
    Workspace = apps.get_model("db", "Workspace")

    # _base_manager includes soft-deleted rows, for both real and historical models
    workspace_ids = (
        Page._base_manager.filter(is_global=True, space__isnull=True).values_list("workspace_id", flat=True).distinct()
    )
    for workspace_id in list(workspace_ids):
        space = WikiSpace._base_manager.filter(
            workspace_id=workspace_id, is_default=True, deleted_at__isnull=True
        ).first()
        if space is None:
            owner_id = Workspace._base_manager.filter(pk=workspace_id).values_list("owner_id", flat=True).first()
            # bulk_create skips Model.save(), which would replace created_by with the
            # (absent) request user; the same code then behaves alike for real and historical models
            (space,) = WikiSpace._base_manager.bulk_create(
                [
                    WikiSpace(
                        workspace_id=workspace_id,
                        name=DEFAULT_SPACE_NAME,
                        identifier=_unique_identifier(WikiSpace, workspace_id),
                        description=DEFAULT_SPACE_DESCRIPTION,
                        access=0,  # open: matches the previous wiki visibility (all admins and members)
                        is_default=True,
                        created_by_id=owner_id,
                        updated_by_id=owner_id,
                    )
                ]
            )
        Page._base_manager.filter(workspace_id=workspace_id, is_global=True, space__isnull=True).update(
            space_id=space.id
        )
