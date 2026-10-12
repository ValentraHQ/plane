# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json
import uuid
from datetime import datetime
from django.core.serializers.json import DjangoJSONEncoder

# Django imports
from django.db import connection
from django.db.models import (
    Exists,
    OuterRef,
    Q,
    Value,
    UUIDField,
    Count,
    Case,
    When,
    IntegerField,
    Subquery,
)
from django.http import StreamingHttpResponse
from django.contrib.postgres.aggregates import ArrayAgg
from django.contrib.postgres.fields import ArrayField
from django.db.models.functions import Coalesce

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import allow_permission, ROLE
from plane.app.serializers import (
    PageSerializer,
    PageDetailSerializer,
    PageBinaryUpdateSerializer,
)
from plane.db.models import (
    Page,
    PageLog,
    PageRestriction,
    UserFavorite,
    ProjectMember,
    ProjectPage,
    UserRecentVisit,
)
from plane.utils.error_codes import ERROR_CODES
from plane.utils.page_access import page_permissions, viewable_project_pages
from plane.utils.order_queryset import PAGE_ORDER_BY_ALLOWLIST, sanitize_order_by

# Local imports
from ..base import BaseAPIView, BaseViewSet
from plane.bgtasks.page_transaction_task import page_transaction
from plane.bgtasks.page_version_task import track_page_version
from plane.bgtasks.recent_visited_task import recent_visited_task
from plane.bgtasks.copy_s3_object import copy_s3_objects_of_description_and_assets
from plane.app.permissions import ProjectPagePermission


def unarchive_archive_page_and_descendants(page_id, archived_at):
    # Your SQL query
    sql = """
    WITH RECURSIVE descendants AS (
        SELECT id FROM pages WHERE id = %s
        UNION
        SELECT pages.id FROM pages, descendants WHERE pages.parent_id = descendants.id
    )
    UPDATE pages SET archived_at = %s WHERE id IN (SELECT id FROM descendants);
    """

    # Execute the SQL query
    with connection.cursor() as cursor:
        cursor.execute(sql, [page_id, archived_at])


def get_page_descendant_ids(page_id):
    """Return the ids of every page nested (at any depth) under page_id."""
    # UNION (not UNION ALL) so the walk terminates even if a cycle already exists
    sql = """
    WITH RECURSIVE descendants AS (
        SELECT id FROM pages WHERE parent_id = %s
        UNION
        SELECT pages.id FROM pages, descendants WHERE pages.parent_id = descendants.id
    )
    SELECT id FROM descendants;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [page_id])
        return {str(row[0]) for row in cursor.fetchall()}


def validate_page_parent(parent_id, slug, project_id, page_id=None, wiki_pages=None):
    """Return an error message if parent_id cannot be the parent of page_id, else None.

    project_id=None validates within the workspace wiki instead of a project; pass
    `wiki_pages` (the wiki pages the user may see, already narrowed to the target space)
    so a parent can only be a visible page of the same space.
    """
    if not parent_id:
        return None
    try:
        parent_id = str(uuid.UUID(str(parent_id)))
    except ValueError:
        return "Invalid parent page"
    if page_id and parent_id == str(page_id):
        return "A page cannot be its own parent"
    if project_id is None:
        pages = wiki_pages if wiki_pages is not None else Page.objects.filter(is_global=True)
        parent = pages.filter(pk=parent_id, workspace__slug=slug).first()
        if parent is None:
            return "Parent page not found in this space"
    else:
        parent = Page.objects.filter(
            pk=parent_id,
            workspace__slug=slug,
            projects__id=project_id,
            project_pages__deleted_at__isnull=True,
        ).first()
    if parent is None:
        return "Parent page not found in this project" if project_id else "Parent page not found in this wiki"
    if parent.archived_at:
        return "A page cannot be nested under an archived page"
    if page_id and parent_id in get_page_descendant_ids(page_id):
        return "A page cannot be moved under one of its own sub-pages"
    return None


def project_page_or_error(request, slug, project_id, page_id, need="can_view"):
    """(page, permissions, None) or (None, None, error response), through the central resolver.

    Pages the user cannot see (including ones hidden by a restricted or private ancestor)
    are reported as missing, so their existence is not revealed.
    """
    page = Page.objects.filter(
        pk=page_id,
        workspace__slug=slug,
        projects__id=project_id,
        project_pages__deleted_at__isnull=True,
    ).first()
    perms = page_permissions(page, request.user, project_id=project_id) if page else None
    if page is None or not perms["can_view"]:
        return None, None, Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
    if not perms[need]:
        return (
            None,
            None,
            Response(
                {"error": "You don't have permission to perform this action on the page"},
                status=status.HTTP_403_FORBIDDEN,
            ),
        )
    return page, perms, None


class PageViewSet(BaseViewSet):
    serializer_class = PageSerializer
    model = Page
    permission_classes = [ProjectPagePermission]
    search_fields = ["name"]

    def get_queryset(self):
        subquery = UserFavorite.objects.filter(
            user=self.request.user,
            entity_type="page",
            entity_identifier=OuterRef("pk"),
            workspace__slug=self.kwargs.get("slug"),
        )
        # Visible, non-archived direct children; lets the UI know a page can be expanded
        visible = viewable_project_pages(self.kwargs.get("slug"), self.request.user, self.kwargs.get("project_id"))
        sub_pages_count = (
            visible.filter(parent_id=OuterRef("pk"), archived_at__isnull=True)
            .order_by()
            .values("parent_id")
            .annotate(count=Count("id"))
            .values("count")
        )
        return self.filter_queryset(
            super()
            .get_queryset()
            .filter(workspace__slug=self.kwargs.get("slug"))
            # who may see what (roles, guests, private pages, inherited restrictions)
            .filter(pk__in=visible.values("pk"))
            .prefetch_related("projects")
            .select_related("workspace")
            .select_related("owned_by")
            .annotate(is_favorite=Exists(subquery))
            .annotate(sub_pages_count=Coalesce(Subquery(sub_pages_count, output_field=IntegerField()), 0))
            .prefetch_related("labels")
            # Sanitize the user-supplied order_by against an allowlist: Django
            # resolves the field at call time, so an unknown field raises
            # FieldError (500 DoS) and a relation path (e.g. owned_by__password)
            # enables ORM relational traversal. Favourites stay
            # pinned first; the sanitized user ordering is the secondary sort
            # (a single .order_by() so it is not overridden), with id as a
            # stable tiebreak for pagination.
            .order_by(
                "-is_favorite",
                sanitize_order_by(
                    self.request.GET.get("order_by", "-created_at"),
                    PAGE_ORDER_BY_ALLOWLIST,
                    default="-created_at",
                ),
                "id",
            )
            .annotate(
                project=Exists(
                    ProjectPage.objects.filter(page_id=OuterRef("id"), project_id=self.kwargs.get("project_id"))
                )
            )
            .annotate(
                label_ids=Coalesce(
                    ArrayAgg(
                        "page_labels__label_id",
                        distinct=True,
                        filter=~Q(page_labels__label_id__isnull=True),
                    ),
                    Value([], output_field=ArrayField(UUIDField())),
                ),
                project_ids=Coalesce(
                    ArrayAgg("projects__id", distinct=True, filter=~Q(projects__id=True)),
                    Value([], output_field=ArrayField(UUIDField())),
                ),
            )
            .filter(project=True)
            .distinct()
        )

    def create(self, request, slug, project_id):
        parent_error = validate_page_parent(request.data.get("parent"), slug, project_id)
        if parent_error:
            return Response({"error": parent_error}, status=status.HTTP_400_BAD_REQUEST)
        if request.data.get("parent"):
            _, _, error = project_page_or_error(request, slug, project_id, request.data.get("parent"), "can_edit")
            if error:
                return error

        serializer = PageSerializer(
            data=request.data,
            context={
                "project_id": project_id,
                "owned_by_id": request.user.id,
                "description_json": request.data.get("description_json", {}),
                "description_binary": request.data.get("description_binary", None),
                "description_html": request.data.get("description_html", "<p></p>"),
            },
        )

        if serializer.is_valid():
            serializer.save()
            # capture the page transaction
            page_transaction.delay(
                new_description_html=request.data.get("description_html", "<p></p>"),
                old_description_html=None,
                page_id=serializer.data["id"],
            )
            page = self.get_queryset().get(pk=serializer.data["id"])
            serializer = PageDetailSerializer(page)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request, slug, project_id, page_id):
        try:
            page, _, error = project_page_or_error(request, slug, project_id, page_id, "can_edit")
            if error:
                return error

            if page.is_locked:
                return Response({"error": "Page is locked"}, status=status.HTTP_400_BAD_REQUEST)

            parent_error = validate_page_parent(request.data.get("parent"), slug, project_id, page_id=page_id)
            if parent_error:
                return Response({"error": parent_error}, status=status.HTTP_400_BAD_REQUEST)
            new_parent = request.data.get("parent")
            if new_parent and str(new_parent) != str(page.parent_id or ""):
                _, _, error = project_page_or_error(request, slug, project_id, new_parent, "can_edit")
                if error:
                    return error

            # Only update access if the page owner is the requesting  user
            if page.access != request.data.get("access", page.access) and page.owned_by_id != request.user.id:
                return Response(
                    {"error": "Access cannot be updated since this page is owned by someone else"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer = PageDetailSerializer(page, data=request.data, partial=True)
            page_description = page.description_html
            if serializer.is_valid():
                serializer.save()
                # capture the page transaction
                if request.data.get("description_html"):
                    page_transaction.delay(
                        new_description_html=request.data.get("description_html", "<p></p>"),
                        old_description_html=page_description,
                        page_id=page_id,
                    )

                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Page.DoesNotExist:
            return Response(
                {"error": "Access cannot be updated since this page is owned by someone else"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def retrieve(self, request, slug, project_id, page_id=None):
        page = self.get_queryset().filter(pk=page_id).first()
        if page is None:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        # guests, private pages and restrictions are already applied by get_queryset()
        track_visit = request.query_params.get("track_visit", "true").lower() == "true"
        issue_ids = PageLog.objects.filter(page_id=page_id, entity_name="issue").values_list(
            "entity_identifier", flat=True
        )
        data = PageDetailSerializer(page).data
        data["issue_ids"] = issue_ids
        data["permissions"] = page_permissions(page, request.user, project_id=project_id)
        if track_visit:
            recent_visited_task.delay(
                slug=slug,
                entity_name="page",
                entity_identifier=page_id,
                user_id=request.user.id,
                project_id=project_id,
            )
        return Response(data, status=status.HTTP_200_OK)

    def permissions(self, request, slug, project_id, page_id):
        """Effective permissions (plane.utils.page_access); used by the real-time server
        before opening a connection."""
        page, perms, error = project_page_or_error(request, slug, project_id, page_id)
        if error:
            return error
        return Response(perms, status=status.HTTP_200_OK)

    def lock(self, request, slug, project_id, page_id):
        page, _, error = project_page_or_error(request, slug, project_id, page_id, "can_edit")
        if error:
            return error

        page.is_locked = True
        page.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def unlock(self, request, slug, project_id, page_id):
        page, _, error = project_page_or_error(request, slug, project_id, page_id, "can_edit")
        if error:
            return error

        page.is_locked = False
        page.save()

        return Response(status=status.HTTP_204_NO_CONTENT)

    def access(self, request, slug, project_id, page_id):
        access = request.data.get("access", 0)
        page, _, error = project_page_or_error(request, slug, project_id, page_id, "can_edit")
        if error:
            return error

        # Only update access if the page owner is the requesting user
        if page.access != request.data.get("access", page.access) and page.owned_by_id != request.user.id:
            return Response(
                {"error": "Access cannot be updated since this page is owned by someone else"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        page.access = access
        page.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def list(self, request, slug, project_id):
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
        # guests, private pages and restrictions are already applied by get_queryset()
        pages = PageSerializer(queryset, many=True).data
        return Response(pages, status=status.HTTP_200_OK)

    def archive(self, request, slug, project_id, page_id):
        page, _, error = project_page_or_error(request, slug, project_id, page_id, "can_edit")
        if error:
            return error

        # only the owner or admin can archive the page
        if (
            ProjectMember.objects.filter(
                project_id=project_id, member=request.user, is_active=True, role__lte=15
            ).exists()
            and request.user.id != page.owned_by_id
        ):
            return Response(
                {"error": "Only the owner or admin can archive the page"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        UserFavorite.objects.filter(
            entity_type="page",
            entity_identifier=page_id,
            project_id=project_id,
            workspace__slug=slug,
        ).delete()

        unarchive_archive_page_and_descendants(page_id, datetime.now())

        return Response({"archived_at": str(datetime.now())}, status=status.HTTP_200_OK)

    def unarchive(self, request, slug, project_id, page_id):
        page, _, error = project_page_or_error(request, slug, project_id, page_id, "can_edit")
        if error:
            return error

        # only the owner or admin can un archive the page
        if (
            ProjectMember.objects.filter(
                project_id=project_id, member=request.user, is_active=True, role__lte=15
            ).exists()
            and request.user.id != page.owned_by_id
        ):
            return Response(
                {"error": "Only the owner or admin can un archive the page"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # if parent archived then page will be un archived breaking hierarchy
        if page.parent_id and page.parent.archived_at:
            page.parent = None
            page.save(update_fields=["parent"])

        unarchive_archive_page_and_descendants(page_id, None)

        return Response(status=status.HTTP_204_NO_CONTENT)

    def destroy(self, request, slug, project_id, page_id):
        page, _, error = project_page_or_error(request, slug, project_id, page_id, "can_edit")
        if error:
            return error

        if page.archived_at is None:
            return Response(
                {"error": "The page should be archived before deleting"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if page.owned_by_id != request.user.id and (
            not ProjectMember.objects.filter(
                workspace__slug=slug,
                member=request.user,
                role=20,
                project_id=project_id,
                is_active=True,
            ).exists()
        ):
            return Response(
                {"error": "Only admin or owner can delete the page"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # remove parent from all the children
        _ = Page.objects.filter(
            parent_id=page_id,
            projects__id=project_id,
            workspace__slug=slug,
            project_pages__deleted_at__isnull=True,
        ).update(parent=None)

        page.delete()
        # Delete the user favorite page
        UserFavorite.objects.filter(
            project=project_id,
            workspace__slug=slug,
            entity_identifier=page_id,
            entity_type="page",
        ).delete()
        # Delete the page from recent visit
        UserRecentVisit.objects.filter(
            project_id=project_id,
            workspace__slug=slug,
            entity_identifier=page_id,
            entity_name="page",
        ).delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def summary(self, request, slug, project_id):
        queryset = viewable_project_pages(slug, request.user, project_id).filter(parent__isnull=True)

        stats = queryset.aggregate(
            public_pages=Count(
                Case(
                    When(access=Page.PUBLIC_ACCESS, archived_at__isnull=True, then=1),
                    output_field=IntegerField(),
                )
            ),
            private_pages=Count(
                Case(
                    When(access=Page.PRIVATE_ACCESS, archived_at__isnull=True, then=1),
                    output_field=IntegerField(),
                )
            ),
            archived_pages=Count(Case(When(archived_at__isnull=False, then=1), output_field=IntegerField())),
        )

        return Response(stats, status=status.HTTP_200_OK)


class PageFavoriteViewSet(BaseViewSet):
    model = UserFavorite

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def create(self, request, slug, project_id, page_id):
        # a favourite shows the page title in the sidebar, so only for pages the user can see
        _, _, error = project_page_or_error(request, slug, project_id, page_id)
        if error:
            return error
        _ = UserFavorite.objects.create(
            project_id=project_id,
            entity_identifier=page_id,
            entity_type="page",
            user=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def destroy(self, request, slug, project_id, page_id):
        page_favorite = UserFavorite.objects.get(
            project=project_id,
            user=request.user,
            workspace__slug=slug,
            entity_identifier=page_id,
            entity_type="page",
        )
        page_favorite.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PagesDescriptionViewSet(BaseViewSet):
    permission_classes = [ProjectPagePermission]

    def retrieve(self, request, slug, project_id, page_id):
        page, _, error = project_page_or_error(request, slug, project_id, page_id)
        if error:
            return error
        binary_data = page.description_binary

        def stream_data():
            if binary_data:
                yield binary_data
            else:
                yield b""

        response = StreamingHttpResponse(stream_data(), content_type="application/octet-stream")
        response["Content-Disposition"] = 'attachment; filename="page_description.bin"'
        return response

    def partial_update(self, request, slug, project_id, page_id):
        page, _, error = project_page_or_error(request, slug, project_id, page_id, "can_edit")
        if error:
            return error

        if page.is_locked:
            return Response(
                {
                    "error_code": ERROR_CODES["PAGE_LOCKED"],
                    "error_message": "PAGE_LOCKED",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if page.archived_at:
            return Response(
                {
                    "error_code": ERROR_CODES["PAGE_ARCHIVED"],
                    "error_message": "PAGE_ARCHIVED",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Store the old description_html before saving (needed for both tasks)
        old_description_html = page.description_html

        # Serialize the existing instance
        existing_instance = json.dumps({"description_html": old_description_html}, cls=DjangoJSONEncoder)

        # Use serializer for validation and update
        serializer = PageBinaryUpdateSerializer(page, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()

            # Capture the page transaction
            if request.data.get("description_html"):
                page_transaction.delay(
                    new_description_html=request.data.get("description_html", "<p></p>"),
                    old_description_html=old_description_html,
                    page_id=page_id,
                )

            # Run background tasks
            track_page_version.delay(
                page_id=page_id,
                existing_instance=existing_instance,
                user_id=request.user.id,
            )
            return Response({"message": "Updated successfully"})
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PageDuplicateEndpoint(BaseAPIView):
    permission_classes = [ProjectPagePermission]

    def post(self, request, slug, project_id, page_id):
        page, _, error = project_page_or_error(request, slug, project_id, page_id)
        if error:
            return error
        if page.parent_id:
            # the copy sits next to the original, so it needs edit rights on the parent
            _, _, error = project_page_or_error(request, slug, project_id, page.parent_id, "can_edit")
            if error:
                return error
        source_page_id = page.id

        # get all the project ids where page is present
        project_ids = ProjectPage.objects.filter(page_id=page_id).values_list("project_id", flat=True)

        page.pk = None
        page.name = f"{page.name} (Copy)"
        page.description_binary = None
        page.owned_by = request.user
        page.created_by = request.user
        page.updated_by = request.user
        page.save()

        # the copy keeps the original's own restrictions, so copying never widens access
        PageRestriction.objects.bulk_create(
            [
                PageRestriction(
                    workspace_id=page.workspace_id,
                    page_id=page.id,
                    kind=restriction.kind,
                    member_id=restriction.member_id,
                    created_by_id=request.user.id,
                    updated_by_id=request.user.id,
                )
                for restriction in PageRestriction.objects.filter(page_id=source_page_id)
            ]
        )

        for project_id in project_ids:
            ProjectPage.objects.create(
                workspace_id=page.workspace_id,
                project_id=project_id,
                page_id=page.id,
                created_by_id=page.created_by_id,
                updated_by_id=page.updated_by_id,
            )

        page_transaction.delay(
            new_description_html=page.description_html,
            old_description_html=None,
            page_id=page.id,
        )

        # Copy the s3 objects uploaded in the page
        copy_s3_objects_of_description_and_assets.delay(
            entity_name="PAGE",
            entity_identifier=page.id,
            project_id=project_id,
            slug=slug,
            user_id=request.user.id,
        )

        page = (
            Page.objects.filter(pk=page.id)
            .annotate(
                project_ids=Coalesce(
                    ArrayAgg("projects__id", distinct=True, filter=~Q(projects__id=True)),
                    Value([], output_field=ArrayField(UUIDField())),
                )
            )
            .first()
        )
        serializer = PageDetailSerializer(page)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
