# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Workspace wiki pages: pages that belong to a documentation space instead of a project.

Wiki pages are `Page` rows with `is_global=True`, a `space` and no ProjectPage link.
Every access decision goes through plane.utils.wiki_permissions.
"""

# Python imports
import json
import uuid
from datetime import datetime

# Django imports
from django.contrib.postgres.fields import ArrayField
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import BooleanField, Count, Exists, IntegerField, OuterRef, Subquery, UUIDField, Value
from django.db.models.functions import Coalesce
from django.http import StreamingHttpResponse

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import (
    PageBinaryUpdateSerializer,
    PageDetailSerializer,
    PageSerializer,
    PageVersionDetailSerializer,
    PageVersionSerializer,
    WorkspacePageSerializer,
)
from plane.bgtasks.page_transaction_task import page_transaction
from plane.bgtasks.page_version_task import track_page_version
from plane.db.models import Page, PageRestriction, PageVersion, Workspace
from plane.utils.error_codes import ERROR_CODES
from plane.utils.order_queryset import PAGE_ORDER_BY_ALLOWLIST, sanitize_order_by
from plane.utils.wiki_permissions import (
    SPACE_EDITOR,
    page_permissions,
    space_role,
    viewable_spaces,
    viewable_wiki_pages,
)

from ..base import BaseAPIView, BaseViewSet
from .base import get_page_descendant_ids, unarchive_archive_page_and_descendants, validate_page_parent

WIKI_ROLES = [ROLE.ADMIN, ROLE.MEMBER]


def _forbidden(message):
    return Response({"error": message}, status=status.HTTP_403_FORBIDDEN)


def _not_found(message="Page not found"):
    return Response({"error": message}, status=status.HTTP_404_NOT_FOUND)


def _bad_request(message):
    return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def get_viewable_space(slug, user, space_id):
    """The space if the user can see it, else None (missing and forbidden look the same)."""
    space_uuid = _parse_uuid(space_id)
    if space_uuid is None:
        return None
    return viewable_spaces(slug, user).filter(pk=space_uuid).first()


def create_wiki_page(slug, user, data):
    """
    Create a wiki page as `user` from request-like `data` (space, parent, name, access,
    description_*). Returns (page, None) or (None, error response). Shared by the wiki and
    by features that create pages for the user, such as the library.
    """
    visible = viewable_wiki_pages(slug, user)
    parent_id = data.get("parent")
    space = None
    if parent_id:
        # a sub-page always lives in its parent's space
        parent = visible.filter(pk=_parse_uuid(parent_id)).select_related("space").first()
        if parent is None:
            return None, _bad_request("Parent page not found in this space")
        if not page_permissions(parent, user)["can_edit"]:
            return None, _forbidden("You don't have permission to add pages under this page")
        space = parent.space
        requested_space = data.get("space")
        if requested_space and str(requested_space) != str(space.id):
            return None, _bad_request("A sub-page must be in the same space as its parent")
    else:
        space = get_viewable_space(slug, user, data.get("space"))
        if space is None:
            return None, _bad_request("A valid space is required")
    role = space_role(space, user)
    if role is None or role < SPACE_EDITOR:
        return None, _forbidden("You need editor access to this space to create pages")
    parent_error = validate_page_parent(parent_id, slug, None, wiki_pages=visible.filter(space=space))
    if parent_error:
        return None, _bad_request(parent_error)

    serializer = WorkspacePageSerializer(
        data=data,
        context={
            "workspace_id": Workspace.objects.get(slug=slug).id,
            "space_id": space.id,
            "owned_by_id": user.id,
            "description_json": data.get("description_json", {}),
            "description_binary": data.get("description_binary", None),
            "description_html": data.get("description_html", "<p></p>"),
        },
    )
    if not serializer.is_valid():
        return None, Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    page = serializer.save()
    page_transaction.delay(
        new_description_html=data.get("description_html", "<p></p>"),
        old_description_html=None,
        page_id=page.id,
    )
    return page, None


class WorkspacePageViewSet(BaseViewSet):
    serializer_class = PageSerializer
    model = Page

    def get_queryset(self):
        user = self.request.user
        slug = self.kwargs.get("slug")
        visible = viewable_wiki_pages(slug, user)
        sub_pages_count = (
            visible.filter(parent_id=OuterRef("pk"), archived_at__isnull=True)
            .order_by()
            .values("parent_id")
            .annotate(count=Count("id"))
            .values("count")
        )
        return (
            visible.select_related("workspace", "owned_by", "space")
            .annotate(sub_pages_count=Coalesce(Subquery(sub_pages_count, output_field=IntegerField()), 0))
            # favourites and labels are project features; keep the shape the web app expects
            .annotate(is_favorite=Value(False, output_field=BooleanField()))
            .annotate(
                label_ids=Value([], output_field=ArrayField(UUIDField())),
                project_ids=Value([], output_field=ArrayField(UUIDField())),
            )
            .order_by(
                sanitize_order_by(
                    self.request.GET.get("order_by", "-created_at"),
                    PAGE_ORDER_BY_ALLOWLIST,
                    default="-created_at",
                ),
                "id",
            )
        )

    def _get_page(self, page_id):
        return self.get_queryset().filter(pk=page_id).first()

    def _page_and_permissions(self, request, page_id):
        page = self._get_page(page_id)
        if page is None:
            return None, None
        return page, page_permissions(page, request.user)

    def _check_new_parent(self, request, parent_id):
        """A page can only be placed under a parent the user can edit (restrictions inherit)."""
        if not parent_id:
            return None
        parent = self._get_page(_parse_uuid(parent_id))
        if parent is None or not page_permissions(parent, request.user)["can_edit"]:
            return _forbidden("You don't have permission to add pages under the target page")
        return None

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def list(self, request, slug):
        queryset = self.get_queryset()
        space_id = request.query_params.get("space_id")
        if space_id:
            space = get_viewable_space(slug, request.user, space_id)
            if space is None:
                return _not_found("Space not found")
            queryset = queryset.filter(space=space)
        # Top-level pages by default; ?parent_id=<uuid> lists that page's direct children
        parent_id = request.query_params.get("parent_id")
        if parent_id:
            parent_uuid = _parse_uuid(parent_id)
            if parent_uuid is None:
                return _bad_request("Invalid parent_id")
            queryset = queryset.filter(parent_id=parent_uuid)
        else:
            queryset = queryset.filter(parent__isnull=True)
        return Response(PageSerializer(queryset, many=True).data, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def create(self, request, slug):
        page, error = create_wiki_page(slug, request.user, request.data)
        if error:
            return error
        return Response(PageDetailSerializer(self._get_page(page.id)).data, status=status.HTTP_201_CREATED)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def retrieve(self, request, slug, page_id):
        page, perms = self._page_and_permissions(request, page_id)
        if page is None:
            return _not_found()
        data = PageDetailSerializer(page).data
        data["permissions"] = perms
        return Response(data, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def permissions(self, request, slug, page_id):
        """Effective permissions; used by the real-time server before opening a connection."""
        page, perms = self._page_and_permissions(request, page_id)
        if page is None:
            return _not_found()
        return Response(perms, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def partial_update(self, request, slug, page_id):
        page, perms = self._page_and_permissions(request, page_id)
        if page is None:
            return _not_found()
        if not perms["can_edit"]:
            return _forbidden("You don't have permission to edit this page")
        if page.is_locked:
            return _bad_request("Page is locked")
        if "parent" in request.data and str(request.data.get("parent") or "") != str(page.parent_id or ""):
            # re-parenting is a structural change: same rule as the move endpoint
            if not perms["can_manage"]:
                return _forbidden("Only the page owner or a space admin can move this page")
            # moving to another space goes through the move endpoint
            parent_error = validate_page_parent(
                request.data.get("parent"),
                slug,
                None,
                page_id=page_id,
                wiki_pages=viewable_wiki_pages(slug, request.user).filter(space_id=page.space_id),
            )
            if parent_error:
                return _bad_request(parent_error)
            parent_error = self._check_new_parent(request, request.data.get("parent"))
            if parent_error:
                return parent_error
        if page.access != request.data.get("access", page.access) and page.owned_by_id != request.user.id:
            return _bad_request("Access cannot be updated since this page is owned by someone else")

        serializer = WorkspacePageSerializer(page, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(PageDetailSerializer(self._get_page(page_id)).data, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def move(self, request, slug, page_id):
        """Move a page (and its whole sub-tree) to another parent, space and/or position."""
        page, perms = self._page_and_permissions(request, page_id)
        if page is None:
            return _not_found()
        if not perms["can_manage"]:
            return _forbidden("Only the page owner or a space admin can move this page")
        if page.archived_at:
            return _bad_request("Restore the page before moving it")

        target_space = page.space
        if request.data.get("space") and str(request.data.get("space")) != str(page.space_id):
            target_space = get_viewable_space(slug, request.user, request.data.get("space"))
            if target_space is None:
                return _bad_request("Target space not found")
        target_role = space_role(target_space, request.user)
        if target_role is None or target_role < SPACE_EDITOR:
            return _forbidden("You need editor access to the target space")

        new_parent_id = request.data.get("parent", page.parent_id if target_space.id == page.space_id else None)
        parent_error = validate_page_parent(
            new_parent_id,
            slug,
            None,
            page_id=page_id,
            wiki_pages=viewable_wiki_pages(slug, request.user).filter(space=target_space),
        )
        if parent_error:
            return _bad_request(parent_error)
        parent_error = self._check_new_parent(request, new_parent_id)
        if parent_error:
            return parent_error

        sort_order = request.data.get("sort_order")
        if sort_order is not None:
            try:
                sort_order = float(sort_order)
            except (TypeError, ValueError):
                return _bad_request("Invalid sort_order")

        with transaction.atomic():
            page.parent_id = _parse_uuid(new_parent_id) if new_parent_id else None
            update_fields = ["parent", "updated_at"]
            if sort_order is not None:
                page.sort_order = sort_order
                update_fields.append("sort_order")
            if target_space.id != page.space_id:
                # the whole sub-tree moves with the page
                descendant_ids = get_page_descendant_ids(page.id)
                Page.objects.filter(pk__in=descendant_ids).update(space=target_space)
                page.space = target_space
                update_fields.append("space")
            page.save(update_fields=update_fields)
        return Response(PageDetailSerializer(self._get_page(page_id)).data, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def access(self, request, slug, page_id):
        page, perms = self._page_and_permissions(request, page_id)
        if page is None:
            return _not_found()
        if page.owned_by_id != request.user.id or not perms["can_edit"]:
            return _forbidden("Only the owner can change the access of a page")
        access = request.data.get("access", page.access)
        if access not in (Page.PUBLIC_ACCESS, Page.PRIVATE_ACCESS):
            return _bad_request("Invalid access")
        page.access = access
        page.save(update_fields=["access", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _managed_page(self, request, page_id, action):
        """Return (page, None) if the user may `action` the page, else (None, error response)."""
        page, perms = self._page_and_permissions(request, page_id)
        if page is None:
            return None, _not_found()
        if not perms["can_manage"]:
            return None, _forbidden(f"Only the page owner or a space admin can {action} the page")
        return page, None

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def lock(self, request, slug, page_id):
        page, error = self._managed_page(request, page_id, "lock")
        if error:
            return error
        page.is_locked = True
        page.save(update_fields=["is_locked", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def unlock(self, request, slug, page_id):
        page, error = self._managed_page(request, page_id, "unlock")
        if error:
            return error
        page.is_locked = False
        page.save(update_fields=["is_locked", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def archive(self, request, slug, page_id):
        page, error = self._managed_page(request, page_id, "archive")
        if error:
            return error
        archived_at = datetime.now()
        unarchive_archive_page_and_descendants(page.id, archived_at)
        return Response({"archived_at": str(archived_at)}, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def unarchive(self, request, slug, page_id):
        page, error = self._managed_page(request, page_id, "restore")
        if error:
            return error
        # restoring under a still-archived parent would hide the page, so lift it to the top level
        if page.parent_id and page.parent.archived_at:
            page.parent = None
            page.save(update_fields=["parent", "updated_at"])
        unarchive_archive_page_and_descendants(page.id, None)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def destroy(self, request, slug, page_id):
        page, error = self._managed_page(request, page_id, "delete")
        if error:
            return error
        if page.archived_at is None:
            return _bad_request("The page should be archived before deleting")
        # keep the children: they move to the top level of the same space
        Page.objects.filter(parent_id=page.id, workspace__slug=slug, is_global=True).update(parent=None)
        page.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspacePagesDescriptionViewSet(BaseViewSet):
    """Binary (Yjs) description of a wiki page; used by the real-time editor server."""

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def retrieve(self, request, slug, page_id):
        page = viewable_wiki_pages(slug, request.user).filter(pk=page_id).first()
        if page is None:
            return _not_found()
        binary_data = page.description_binary

        def stream_data():
            yield binary_data or b""

        response = StreamingHttpResponse(stream_data(), content_type="application/octet-stream")
        response["Content-Disposition"] = 'attachment; filename="page_description.bin"'
        return response

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def partial_update(self, request, slug, page_id):
        page = viewable_wiki_pages(slug, request.user).filter(pk=page_id).select_related("space").first()
        if page is None:
            return _not_found()
        if not page_permissions(page, request.user)["can_edit"]:
            return _forbidden("You don't have permission to edit this page")
        if page.is_locked:
            return Response(
                {"error_code": ERROR_CODES["PAGE_LOCKED"], "error_message": "PAGE_LOCKED"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if page.archived_at:
            return Response(
                {"error_code": ERROR_CODES["PAGE_ARCHIVED"], "error_message": "PAGE_ARCHIVED"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_description_html = page.description_html
        existing_instance = json.dumps({"description_html": old_description_html}, cls=DjangoJSONEncoder)
        serializer = PageBinaryUpdateSerializer(page, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        if request.data.get("description_html"):
            page_transaction.delay(
                new_description_html=request.data.get("description_html", "<p></p>"),
                old_description_html=old_description_html,
                page_id=page_id,
            )
        track_page_version.delay(page_id=page_id, existing_instance=existing_instance, user_id=request.user.id)
        return Response({"message": "Updated successfully"})


class WorkspacePageVersionEndpoint(BaseAPIView):
    """Version history of a wiki page; only for users who can see the page."""

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def get(self, request, slug, page_id, pk=None):
        if not viewable_wiki_pages(slug, request.user).filter(pk=page_id).exists():
            return _not_found()
        versions = PageVersion.objects.filter(workspace__slug=slug, page_id=page_id)
        if pk:
            version = versions.filter(pk=pk).first()
            if version is None:
                return _not_found("Version not found")
            return Response(PageVersionDetailSerializer(version).data, status=status.HTTP_200_OK)
        return Response(PageVersionSerializer(versions, many=True).data, status=status.HTTP_200_OK)


class WikiSpacePageTreeEndpoint(BaseAPIView):
    """All visible, non-archived pages of a space in one call, for the sidebar tree."""

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def get(self, request, slug, space_id):
        space = get_viewable_space(slug, request.user, space_id)
        if space is None:
            return _not_found("Space not found")
        pages = (
            viewable_wiki_pages(slug, request.user)
            .filter(space=space, archived_at__isnull=True)
            .annotate(
                view_restricted=Exists(
                    PageRestriction.objects.filter(page_id=OuterRef("pk"), kind=PageRestriction.VIEW)
                ),
                edit_restricted=Exists(
                    PageRestriction.objects.filter(page_id=OuterRef("pk"), kind=PageRestriction.EDIT)
                ),
            )
            .order_by("sort_order", "created_at")
            .values(
                "id",
                "name",
                "parent_id",
                "sort_order",
                "logo_props",
                "access",
                "is_locked",
                "owned_by_id",
                "view_restricted",
                "edit_restricted",
            )
        )
        nodes = [
            {
                "id": p["id"],
                "name": p["name"],
                "parent": p["parent_id"],
                "sort_order": p["sort_order"],
                "logo_props": p["logo_props"],
                "access": p["access"],
                "is_locked": p["is_locked"],
                "owned_by": p["owned_by_id"],
                "space": space.id,
                # the page's own restrictions; inherited ones are shown on the page
                "view_restricted": p["view_restricted"],
                "edit_restricted": p["edit_restricted"],
            }
            for p in pages
        ]
        return Response(nodes, status=status.HTTP_200_OK)
