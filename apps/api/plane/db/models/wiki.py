# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Documentation spaces for the workspace wiki.

Every workspace wiki page (Page.is_global) belongs to exactly one WikiSpace.
Project pages never have a space. Access to a space is resolved by
plane.utils.wiki_permissions; keep authorization logic there, not here.
"""

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


class WikiSpace(BaseModel):
    # OPEN: every workspace admin and member can read and write.
    # RESTRICTED: only explicit space members (and workspace admins).
    ACCESS_OPEN = 0
    ACCESS_RESTRICTED = 1
    ACCESS_CHOICES = ((ACCESS_OPEN, "Open"), (ACCESS_RESTRICTED, "Restricted"))

    DEFAULT_SORT_ORDER = 65535

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="wiki_spaces")
    name = models.CharField(max_length=255)
    # short uppercase key, unique per workspace (e.g. ENG, HR)
    identifier = models.CharField(max_length=12)
    description = models.TextField(blank=True, default="")
    logo_props = models.JSONField(default=dict)
    access = models.PositiveSmallIntegerField(choices=ACCESS_CHOICES, default=ACCESS_OPEN)
    # the space wiki pages were migrated into ("General"); it cannot be deleted
    is_default = models.BooleanField(default=False)
    sort_order = models.FloatField(default=DEFAULT_SORT_ORDER)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Wiki Space"
        verbose_name_plural = "Wiki Spaces"
        db_table = "wiki_spaces"
        ordering = ("sort_order", "name")
        unique_together = ["workspace", "identifier", "deleted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "identifier"],
                condition=Q(deleted_at__isnull=True),
                name="wiki_space_unique_workspace_identifier_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.identifier} <{self.name}>"


class WikiSpaceMember(BaseModel):
    ROLE_ADMIN = 20
    ROLE_EDITOR = 15
    ROLE_VIEWER = 5
    ROLE_CHOICES = ((ROLE_ADMIN, "Admin"), (ROLE_EDITOR, "Editor"), (ROLE_VIEWER, "Viewer"))

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="wiki_space_members")
    space = models.ForeignKey(WikiSpace, on_delete=models.CASCADE, related_name="space_members")
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wiki_space_memberships"
    )
    role = models.PositiveSmallIntegerField(choices=ROLE_CHOICES, default=ROLE_EDITOR)

    class Meta:
        verbose_name = "Wiki Space Member"
        verbose_name_plural = "Wiki Space Members"
        db_table = "wiki_space_members"
        ordering = ("-created_at",)
        unique_together = ["space", "member", "deleted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["space", "member"],
                condition=Q(deleted_at__isnull=True),
                name="wiki_space_member_unique_space_member_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.member_id} in {self.space_id} ({self.role})"
