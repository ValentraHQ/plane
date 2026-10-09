# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Workspace wiki: pages that belong to the workspace rather than a project.

Wiki pages are `Page` rows with `is_global=True` and no ProjectPage link. Only
active workspace Admins and Members can use the wiki; guests cannot. A page is
visible to its owner, and to every member when it is public.
"""

# Python imports
import json
import uuid
from datetime import datetime

# Django imports
from django.contrib.postgres.fields import ArrayField
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import BooleanField, Count, IntegerField, OuterRef, Q, Subquery, UUIDField, Value
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
from plane.db.models import Page, PageVersion, Workspace, WorkspaceMember
from plane.utils.error_codes import ERROR_CODES
from plane.utils.order_queryset import PAGE_ORDER_BY_ALLOWLIST, sanitize_order_by

from ..base import BaseAPIView, BaseViewSet
from .base import unarchive_archive_page_and_descendants, validate_page_parent

WIKI_ROLES = [ROLE.ADMIN, ROLE.MEMBER]


def is_workspace_admin(slug, user):
    return WorkspaceMember.objects.filter(
        workspace__slug=slug, member=user, role=ROLE.ADMIN.value, is_active=True
    ).exists()


def visible_wiki_pages(slug, user):
    """Wiki pages the user may see: their own, plus every public one."""
    return Page.objects.filter(workspace__slug=slug, is_global=True).filter(
        Q(owned_by=user) | Q(access=Page.PUBLIC_ACCESS)
    )


def _forbidden(message):
    return Response({"error": message}, status=status.HTTP_403_FORBIDDEN)


def _not_found():
    return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)


class WorkspacePageViewSet(BaseViewSet):
    serializer_class = PageSerializer
    model = Page

    def get_queryset(self):
        user = self.request.user
        sub_pages_count = (
            Page.objects.filter(parent_id=OuterRef("pk"), is_global=True, archived_at__isnull=True)
            .filter(Q(owned_by=user) | Q(access=Page.PUBLIC_ACCESS))
            .order_by()
            .values("parent_id")
            .annotate(count=Count("id"))
            .values("count")
        )
        return (
            visible_wiki_pages(self.kwargs.get("slug"), user)
            .select_related("workspace", "owned_by")
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

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def list(self, request, slug):
        queryset = self.get_queryset()
        # Top-level pages by default; ?parent_id=<uuid> lists that page's direct children
        parent_id = request.query_params.get("parent_id")
        if parent_id:
            try:
                queryset = queryset.filter(parent_id=uuid.UUID(parent_id))
            except ValueError:
                return Response({"error": "Invalid parent_id"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            queryset = queryset.filter(parent__isnull=True)
        return Response(PageSerializer(queryset, many=True).data, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def create(self, request, slug):
        parent_error = validate_page_parent(request.data.get("parent"), slug, None)
        if parent_error:
            return Response({"error": parent_error}, status=status.HTTP_400_BAD_REQUEST)

        workspace = Workspace.objects.get(slug=slug)
        serializer = WorkspacePageSerializer(
            data=request.data,
            context={
                "workspace_id": workspace.id,
                "owned_by_id": request.user.id,
                "description_json": request.data.get("description_json", {}),
                "description_binary": request.data.get("description_binary", None),
                "description_html": request.data.get("description_html", "<p></p>"),
            },
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        page = serializer.save()
        page_transaction.delay(
            new_description_html=request.data.get("description_html", "<p></p>"),
            old_description_html=None,
            page_id=page.id,
        )
        return Response(PageDetailSerializer(self._get_page(page.id)).data, status=status.HTTP_201_CREATED)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def retrieve(self, request, slug, page_id):
        page = self._get_page(page_id)
        if page is None:
            return _not_found()
        return Response(PageDetailSerializer(page).data, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def partial_update(self, request, slug, page_id):
        page = self._get_page(page_id)
        if page is None:
            return _not_found()
        if page.is_locked:
            return Response({"error": "Page is locked"}, status=status.HTTP_400_BAD_REQUEST)
        if "parent" in request.data:
            parent_error = validate_page_parent(request.data.get("parent"), slug, None, page_id=page_id)
            if parent_error:
                return Response({"error": parent_error}, status=status.HTTP_400_BAD_REQUEST)
        if page.access != request.data.get("access", page.access) and page.owned_by_id != request.user.id:
            return Response(
                {"error": "Access cannot be updated since this page is owned by someone else"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = WorkspacePageSerializer(page, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(PageDetailSerializer(self._get_page(page_id)).data, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def access(self, request, slug, page_id):
        page = self._get_page(page_id)
        if page is None:
            return _not_found()
        if page.owned_by_id != request.user.id:
            return _forbidden("Only the owner can change the access of a page")
        access = request.data.get("access", page.access)
        if access not in (Page.PUBLIC_ACCESS, Page.PRIVATE_ACCESS):
            return Response({"error": "Invalid access"}, status=status.HTTP_400_BAD_REQUEST)
        page.access = access
        page.save(update_fields=["access", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _owner_or_admin_page(self, request, slug, page_id, action):
        """Return (page, None) if the user may `action` the page, else (None, error response)."""
        page = self._get_page(page_id)
        if page is None:
            return None, _not_found()
        if page.owned_by_id != request.user.id and not is_workspace_admin(slug, request.user):
            return None, _forbidden(f"Only the owner or a workspace admin can {action} the page")
        return page, None

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def lock(self, request, slug, page_id):
        page, error = self._owner_or_admin_page(request, slug, page_id, "lock")
        if error:
            return error
        page.is_locked = True
        page.save(update_fields=["is_locked", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def unlock(self, request, slug, page_id):
        page, error = self._owner_or_admin_page(request, slug, page_id, "unlock")
        if error:
            return error
        page.is_locked = False
        page.save(update_fields=["is_locked", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def archive(self, request, slug, page_id):
        page, error = self._owner_or_admin_page(request, slug, page_id, "archive")
        if error:
            return error
        archived_at = datetime.now()
        unarchive_archive_page_and_descendants(page.id, archived_at)
        return Response({"archived_at": str(archived_at)}, status=status.HTTP_200_OK)

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def unarchive(self, request, slug, page_id):
        page, error = self._owner_or_admin_page(request, slug, page_id, "restore")
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
        page, error = self._owner_or_admin_page(request, slug, page_id, "delete")
        if error:
            return error
        if page.archived_at is None:
            return Response(
                {"error": "The page should be archived before deleting"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # keep the children: they move to the top level
        Page.objects.filter(parent_id=page.id, workspace__slug=slug, is_global=True).update(parent=None)
        page.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspacePagesDescriptionViewSet(BaseViewSet):
    """Binary (Yjs) description of a wiki page; used by the real-time editor server."""

    @allow_permission(WIKI_ROLES, level="WORKSPACE")
    def retrieve(self, request, slug, page_id):
        page = visible_wiki_pages(slug, request.user).filter(pk=page_id).first()
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
        page = visible_wiki_pages(slug, request.user).filter(pk=page_id).first()
        if page is None:
            return _not_found()
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
        if not visible_wiki_pages(slug, request.user).filter(pk=page_id).exists():
            return _not_found()
        versions = PageVersion.objects.filter(workspace__slug=slug, page_id=page_id)
        if pk:
            version = versions.filter(pk=pk).first()
            if version is None:
                return Response({"error": "Version not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response(PageVersionDetailSerializer(version).data, status=status.HTTP_200_OK)
        return Response(PageVersionSerializer(versions, many=True).data, status=status.HTTP_200_OK)
