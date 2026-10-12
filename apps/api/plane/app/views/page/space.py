# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Documentation spaces of the workspace wiki, and their members.

Who may do what (see plane.utils.wiki_permissions for roles):
  - list / view a space: anyone with a role in it
  - create a space: workspace admins and members; the creator becomes space admin
  - update a space, manage its members: space admins (workspace admins are always space admins)
  - delete a space: space admins, only when it holds no pages; the default space cannot be deleted
"""

# Django imports
from django.db import IntegrityError, transaction
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import WikiSpaceMemberSerializer, WikiSpaceSerializer
from plane.db.models import Page, WikiSpaceMember, Workspace, WorkspaceMember
from plane.utils.wiki_permissions import SPACE_ADMIN, space_role, space_roles, viewable_spaces

from ..base import BaseViewSet
from .workspace import get_viewable_space

WIKI_ROLES = [ROLE.ADMIN, ROLE.MEMBER]


def _error(message, code):
    return Response({"error": message}, status=code)


class WikiSpaceViewSet(BaseViewSet):
    serializer_class = WikiSpaceSerializer

    def _spaces(self, slug, user):
        visible_pages = (
            Page.objects.filter(space_id=OuterRef("pk"), is_global=True, archived_at__isnull=True)
            .filter(Q(owned_by=user) | Q(access=Page.PUBLIC_ACCESS))
            .order_by()
            .values("space_id")
            .annotate(count=Count("id"))
            .values("count")
        )
        return viewable_spaces(slug, user).annotate(
            page_count=Coalesce(Subquery(visible_pages, output_field=IntegerField()), 0)
        )

    def _serialize(self, spaces, user, many=False):
        items = list(spaces) if many else [spaces]
        roles = space_roles(items, user)
        for space in items:
            space.my_role = roles.get(space.id)
        return WikiSpaceSerializer(items if many else items[0], many=many).data

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def list(self, request, slug):
        return Response(self._serialize(self._spaces(slug, request.user), request.user, many=True))

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def create(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        serializer = WikiSpaceSerializer(data=request.data, context={"workspace_id": workspace.id})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                space = serializer.save(workspace=workspace)
                WikiSpaceMember.objects.create(
                    workspace=workspace, space=space, member=request.user, role=WikiSpaceMember.ROLE_ADMIN
                )
        except IntegrityError:
            return _error("This identifier is already used by another space", status.HTTP_400_BAD_REQUEST)
        space = self._spaces(slug, request.user).get(pk=space.pk)
        return Response(self._serialize(space, request.user), status=status.HTTP_201_CREATED)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def retrieve(self, request, slug, space_id):
        space = self._spaces(slug, request.user).filter(pk=space_id).first()
        if space is None:
            return _error("Space not found", status.HTTP_404_NOT_FOUND)
        return Response(self._serialize(space, request.user))

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def partial_update(self, request, slug, space_id):
        space = self._spaces(slug, request.user).filter(pk=space_id).first()
        if space is None:
            return _error("Space not found", status.HTTP_404_NOT_FOUND)
        if space_role(space, request.user) != SPACE_ADMIN:
            return _error("Only space admins can change the space", status.HTTP_403_FORBIDDEN)
        serializer = WikiSpaceSerializer(space, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            serializer.save()
        except IntegrityError:
            return _error("This identifier is already used by another space", status.HTTP_400_BAD_REQUEST)
        space = self._spaces(slug, request.user).get(pk=space.pk)
        return Response(self._serialize(space, request.user))

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def destroy(self, request, slug, space_id):
        space = self._spaces(slug, request.user).filter(pk=space_id).first()
        if space is None:
            return _error("Space not found", status.HTTP_404_NOT_FOUND)
        if space_role(space, request.user) != SPACE_ADMIN:
            return _error("Only space admins can delete the space", status.HTTP_403_FORBIDDEN)
        if space.is_default:
            return _error("The default space cannot be deleted", status.HTTP_400_BAD_REQUEST)
        # count every page, including archived and other people's private pages
        if Page.objects.filter(space=space).exists():
            return _error("Move or delete all pages in this space first", status.HTTP_400_BAD_REQUEST)
        WikiSpaceMember.objects.filter(space=space).delete()
        space.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WikiSpaceMemberViewSet(BaseViewSet):
    serializer_class = WikiSpaceMemberSerializer

    def _admin_space(self, request, slug, space_id):
        """(space, None) if the user is a space admin, else (None, error response)."""
        space = get_viewable_space(slug, request.user, space_id)
        if space is None:
            return None, _error("Space not found", status.HTTP_404_NOT_FOUND)
        if space_role(space, request.user) != SPACE_ADMIN:
            return None, _error("Only space admins can manage members", status.HTTP_403_FORBIDDEN)
        return space, None

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def list(self, request, slug, space_id):
        space = get_viewable_space(slug, request.user, space_id)
        if space is None:
            return _error("Space not found", status.HTTP_404_NOT_FOUND)
        members = WikiSpaceMember.objects.filter(space=space).select_related("member")
        return Response(WikiSpaceMemberSerializer(members, many=True).data)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def create(self, request, slug, space_id):
        space, error = self._admin_space(request, slug, space_id)
        if error:
            return error
        member_id = request.data.get("member")
        # only active workspace admins/members can join; guests never get wiki access
        is_member = WorkspaceMember.objects.filter(
            workspace_id=space.workspace_id, member_id=member_id, is_active=True, role__gte=ROLE.MEMBER.value
        ).exists()
        if not is_member:
            return _error("Only workspace admins and members can be added to a space", status.HTTP_400_BAD_REQUEST)
        if WikiSpaceMember.objects.filter(space=space, member_id=member_id).exists():
            return _error("This user is already a member of the space", status.HTTP_400_BAD_REQUEST)
        serializer = WikiSpaceMemberSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save(space=space, workspace_id=space.workspace_id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def partial_update(self, request, slug, space_id, member_id):
        space, error = self._admin_space(request, slug, space_id)
        if error:
            return error
        membership = WikiSpaceMember.objects.filter(space=space, pk=member_id).first()
        if membership is None:
            return _error("Member not found", status.HTTP_404_NOT_FOUND)
        serializer = WikiSpaceMemberSerializer(membership, data={"role": request.data.get("role")}, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def destroy(self, request, slug, space_id, member_id):
        space, error = self._admin_space(request, slug, space_id)
        if error:
            return error
        membership = WikiSpaceMember.objects.filter(space=space, pk=member_id).first()
        if membership is None:
            return _error("Member not found", status.HTTP_404_NOT_FOUND)
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
