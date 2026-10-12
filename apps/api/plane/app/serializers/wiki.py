# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re

# Third party imports
from rest_framework import serializers

# Module imports
from .base import BaseSerializer
from plane.db.models import WikiSpace, WikiSpaceMember

IDENTIFIER_PATTERN = re.compile(r"^[A-Z0-9]{2,12}$")


class WikiSpaceSerializer(BaseSerializer):
    # current user's effective role (from plane.utils.wiki_permissions), set by the view
    my_role = serializers.IntegerField(read_only=True, allow_null=True, required=False)
    page_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = WikiSpace
        fields = [
            "id",
            "workspace",
            "name",
            "identifier",
            "description",
            "logo_props",
            "access",
            "is_default",
            "sort_order",
            "my_role",
            "page_count",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "workspace", "is_default", "created_at", "updated_at", "created_by"]

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Space name is required")
        return value

    def validate_identifier(self, value):
        value = (value or "").strip().upper()
        if not IDENTIFIER_PATTERN.match(value):
            raise serializers.ValidationError("Use 2-12 letters or digits, e.g. ENG")
        workspace_id = self.context.get("workspace_id") or getattr(self.instance, "workspace_id", None)
        taken = WikiSpace.objects.filter(workspace_id=workspace_id, identifier=value)
        if self.instance:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("This identifier is already used by another space")
        return value


class WikiSpaceMemberSerializer(BaseSerializer):
    member__display_name = serializers.CharField(source="member.display_name", read_only=True)
    member__avatar_url = serializers.CharField(source="member.avatar_url", read_only=True)

    class Meta:
        model = WikiSpaceMember
        fields = ["id", "space", "member", "role", "member__display_name", "member__avatar_url", "created_at"]
        read_only_fields = ["id", "space", "created_at"]

    def validate_role(self, value):
        if value not in dict(WikiSpaceMember.ROLE_CHOICES):
            raise serializers.ValidationError("Invalid role")
        return value
