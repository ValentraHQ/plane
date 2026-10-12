# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Page restrictions (who may view / edit a page and its sub-pages) for wiki and project pages."""

# Python imports
import uuid

# Django imports
from django.db import transaction

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, ProjectPagePermission, allow_permission
from plane.db.models import Page, PageRestriction
from plane.utils.page_access import ancestry, restriction_candidates
from plane.utils.wiki_permissions import page_permissions, viewable_wiki_pages

from ..base import BaseAPIView
from .base import project_page_or_error

KINDS = (PageRestriction.VIEW, PageRestriction.EDIT)


def restrictions_payload(page, perms):
    """The page's own restrictions, the ones it inherits, and whether the user may change them."""
    own = {kind: [] for kind in KINDS}
    for kind, member_id in PageRestriction.objects.filter(page_id=page.id).values_list("kind", "member_id"):
        own[kind].append(str(member_id))

    # every ancestor is visible to someone who can see this page, so naming them leaks nothing
    ancestor_ids = [node_id for node_id, _, _ in ancestry(page.id)[1:]]
    kinds_by_page = {}
    for node_id, kind in PageRestriction.objects.filter(page_id__in=ancestor_ids).values_list("page_id", "kind"):
        kinds_by_page.setdefault(node_id, set()).add(kind)
    names = dict(Page.objects.filter(pk__in=list(kinds_by_page)).values_list("id", "name"))
    inherited = [
        {
            "page": str(node_id),
            "name": names.get(node_id, ""),
            "view": PageRestriction.VIEW in kinds_by_page[node_id],
            "edit": PageRestriction.EDIT in kinds_by_page[node_id],
        }
        for node_id in ancestor_ids
        if node_id in kinds_by_page
    ]
    return {**own, "inherited": inherited, "can_manage": perms["can_manage"]}


def replace_restrictions(request, page):
    """Replace the page's VIEW and/or EDIT member lists. Returns an error response or None."""
    requested = {}
    for kind in KINDS:
        if kind not in request.data:
            continue
        values = request.data.get(kind)
        if not isinstance(values, list):
            return Response({"error": f"'{kind}' must be a list of member ids"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            requested[kind] = {uuid.UUID(str(value)) for value in values}
        except ValueError:
            return Response({"error": f"'{kind}' contains an invalid member id"}, status=status.HTTP_400_BAD_REQUEST)
    if not requested:
        return Response({"error": "Nothing to update"}, status=status.HTTP_400_BAD_REQUEST)

    wanted = set().union(*requested.values())
    allowed = set(restriction_candidates(page).filter(pk__in=wanted).values_list("id", flat=True))
    if wanted - allowed:
        return Response(
            {"error": "Restrictions can only list people who already have access to this page's space or project"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        for kind, members in requested.items():
            current = {row.member_id: row for row in PageRestriction.objects.filter(page_id=page.id, kind=kind)}
            # soft delete keeps who removed what, and when
            for member_id, row in current.items():
                if member_id not in members:
                    row.delete()
            PageRestriction.objects.bulk_create(
                [
                    PageRestriction(
                        workspace_id=page.workspace_id,
                        page_id=page.id,
                        kind=kind,
                        member_id=member_id,
                        created_by_id=request.user.id,
                        updated_by_id=request.user.id,
                    )
                    for member_id in members - set(current)
                ]
            )
    return None


class WorkspacePageRestrictionEndpoint(BaseAPIView):
    """GET / PUT restrictions of a workspace wiki page."""

    def _page(self, request, slug, page_id):
        page = viewable_wiki_pages(slug, request.user).filter(pk=page_id).select_related("space").first()
        if page is None:
            return None, None
        return page, page_permissions(page, request.user)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug, page_id):
        page, perms = self._page(request, slug, page_id)
        if page is None:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(restrictions_payload(page, perms), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def put(self, request, slug, page_id):
        page, perms = self._page(request, slug, page_id)
        if page is None:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        if not perms["can_manage"]:
            return Response(
                {"error": "Only the page owner or a space admin can change restrictions"},
                status=status.HTTP_403_FORBIDDEN,
            )
        error = replace_restrictions(request, page)
        if error:
            return error
        return Response(restrictions_payload(page, page_permissions(page, request.user)), status=status.HTTP_200_OK)


class ProjectPageRestrictionEndpoint(BaseAPIView):
    """GET / PUT restrictions of a project page."""

    permission_classes = [ProjectPagePermission]

    def get(self, request, slug, project_id, page_id):
        page, perms, error = project_page_or_error(request, slug, project_id, page_id)
        if error:
            return error
        return Response(restrictions_payload(page, perms), status=status.HTTP_200_OK)

    def put(self, request, slug, project_id, page_id):
        page, perms, error = project_page_or_error(request, slug, project_id, page_id)
        if error:
            return error
        if not perms["can_manage"]:
            return Response(
                {"error": "Only the page owner or a project admin can change restrictions"},
                status=status.HTTP_403_FORBIDDEN,
            )
        error = replace_restrictions(request, page)
        if error:
            return error
        _, perms, _ = project_page_or_error(request, slug, project_id, page_id)
        return Response(restrictions_payload(page, perms), status=status.HTTP_200_OK)
