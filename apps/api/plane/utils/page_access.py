# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Central page authorization for workspace wiki pages and project pages.

Every page endpoint, search, version history and the real-time server (through the
`permissions` endpoints) must decide access here; do not re-implement the rules in views.

Two layers:

1. Base rules, from the user's role:
   - wiki pages: the space role (plane.utils.wiki_permissions.space_role)
   - project pages: the project role; guests only see their own pages unless the
     project enables `guest_view_all_features`
   - private pages are visible to their owner only

2. Inherited restrictions (Confluence style), which only ever narrow access:
   - a private ancestor hides the whole sub-tree from everyone except that ancestor's owner
   - VIEW restrictions on a page or any ancestor: only the listed members, that page's
     owner and admins pass
   - EDIT restrictions on a page or any ancestor: same, for editing and managing
   "Admins" are space admins (including workspace admins) for wiki pages and project
   admins for project pages. A sub-page can never be more open than its ancestors.
"""

# Django imports
from django.db import connection
from django.db.models import Exists, OuterRef, Q
from django.db.models.expressions import RawSQL

# Module imports
from plane.db.models import (
    Page,
    PageRestriction,
    ProjectMember,
    ProjectPage,
    User,
    WikiSpace,
    WikiSpaceMember,
    Workspace,
    WorkspaceMember,
)
from plane.utils import wiki_permissions as wiki

PROJECT_ADMIN = 20
PROJECT_MEMBER = 15
PROJECT_GUEST = 5

DENIED = {"can_view": False, "can_edit": False, "can_manage": False, "can_edit_content": False}

# Pages hidden from a user: private pages of others and VIEW-restricted pages the user does
# not pass, plus every page below them. Parameters, in order: workspace_id, user_id,
# user_id, workspace-admin flag, admin space ids, admin project ids.
_HIDDEN_PAGES_SQL = """
WITH RECURSIVE hidden(id) AS (
    SELECT p.id FROM pages p
    WHERE p.workspace_id = %s
      AND p.deleted_at IS NULL
      AND p.owned_by_id <> %s
      AND (
        p.access = 1
        OR (
          EXISTS (
            SELECT 1 FROM page_restrictions r
            WHERE r.page_id = p.id AND r.kind = 'view' AND r.deleted_at IS NULL
          )
          AND NOT EXISTS (
            SELECT 1 FROM page_restrictions r
            WHERE r.page_id = p.id AND r.kind = 'view' AND r.deleted_at IS NULL AND r.member_id = %s
          )
          AND NOT (p.space_id IS NOT NULL AND (%s OR p.space_id = ANY(%s::uuid[])))
          AND NOT (
            p.space_id IS NULL
            AND EXISTS (
              SELECT 1 FROM project_pages pp
              WHERE pp.page_id = p.id AND pp.deleted_at IS NULL AND pp.project_id = ANY(%s::uuid[])
            )
          )
        )
      )
    UNION
    SELECT c.id FROM pages c JOIN hidden h ON c.parent_id = h.id
)
SELECT id FROM hidden
"""

# The page and its ancestors, nearest first. UNION stops on (corrupt) cycles.
_ANCESTRY_SQL = """
WITH RECURSIVE chain(id, parent_id, owned_by_id, access, depth) AS (
    SELECT id, parent_id, owned_by_id, access, 0 FROM pages WHERE id = %s
    UNION
    SELECT p.id, p.parent_id, p.owned_by_id, p.access, c.depth + 1
    FROM pages p JOIN chain c ON p.id = c.parent_id
    WHERE c.depth < 200
)
SELECT id, owned_by_id, access FROM chain ORDER BY depth
"""


def _admin_scopes(user, workspace_id):
    """(is workspace admin, admin space ids, admin project ids) for the restriction bypass."""
    ws_role = wiki.workspace_role(user, workspace_id=workspace_id)
    is_ws_admin = ws_role is not None and ws_role >= wiki.WORKSPACE_ADMIN
    space_ids = []
    if not is_ws_admin and ws_role is not None and ws_role >= wiki.WORKSPACE_MEMBER:
        space_ids = [
            str(space_id)
            for space_id in WikiSpaceMember.objects.filter(
                workspace_id=workspace_id, member=user, role=wiki.SPACE_ADMIN
            ).values_list("space_id", flat=True)
        ]
    project_ids = [
        str(project_id)
        for project_id in ProjectMember.objects.filter(
            workspace_id=workspace_id, member=user, is_active=True, role=PROJECT_ADMIN
        ).values_list("project_id", flat=True)
    ]
    return is_ws_admin, space_ids, project_ids


def exclude_hidden(queryset, user, workspace_id):
    """Drop pages hidden from the user by a private or VIEW-restricted page at or above them."""
    is_ws_admin, space_ids, project_ids = _admin_scopes(user, workspace_id)
    hidden = RawSQL(
        _HIDDEN_PAGES_SQL,
        [workspace_id, user.id, user.id, is_ws_admin, space_ids, project_ids],
    )
    return queryset.exclude(id__in=hidden)


def viewable_project_pages(slug, user, project_id=None):
    """Project pages the user can see, optionally only those of one project."""
    workspace_id = Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()
    if workspace_id is None:
        return Page.objects.none()
    memberships = ProjectMember.objects.filter(
        workspace__slug=slug, member=user, is_active=True, project__archived_at__isnull=True
    )
    all_projects = memberships.values("project_id")
    # guests only see others' pages where the project allows it
    full_view_projects = memberships.filter(
        Q(role__gte=PROJECT_MEMBER) | Q(project__guest_view_all_features=True)
    ).values("project_id")

    def linked(projects):
        links = ProjectPage.objects.filter(page_id=OuterRef("pk"), project_id__in=projects)
        if project_id:
            links = links.filter(project_id=project_id)
        return Exists(links)

    queryset = Page.objects.filter(workspace__slug=slug, space__isnull=True).filter(
        (Q(access=Page.PUBLIC_ACCESS) & linked(full_view_projects)) | (Q(owned_by=user) & linked(all_projects))
    )
    return exclude_hidden(queryset, user, workspace_id)


def _base_wiki(page, user, space_role):
    if space_role is None:
        return None
    is_owner = page.owned_by_id == user.id
    view = is_owner or page.access == Page.PUBLIC_ACCESS
    return {
        "view": view,
        "edit": view and space_role >= wiki.SPACE_EDITOR,
        "manage": view and (space_role >= wiki.SPACE_ADMIN or (is_owner and space_role >= wiki.SPACE_EDITOR)),
        "admin": space_role >= wiki.SPACE_ADMIN,
    }


def _project_role(page, user, project_id):
    """(role, guest_view_all_features) in the given project, or the highest across the page's projects."""
    links = ProjectPage.objects.filter(page_id=page.id)
    if project_id:
        links = links.filter(project_id=project_id)
    project_ids = links.values("project_id")
    best = None
    for role, guest_view_all in ProjectMember.objects.filter(
        project_id__in=project_ids, member=user, is_active=True, project__archived_at__isnull=True
    ).values_list("role", "project__guest_view_all_features"):
        if best is None or (role, guest_view_all) > best:
            best = (role, guest_view_all)
    return best


def _base_project(page, user, project_id):
    membership = _project_role(page, user, project_id)
    if membership is None:
        return None
    role, guest_view_all = membership
    is_owner = page.owned_by_id == user.id
    is_public = page.access == Page.PUBLIC_ACCESS
    view = is_owner or (is_public and (role >= PROJECT_MEMBER or guest_view_all))
    return {
        "view": view,
        "edit": view and (is_owner or (is_public and role >= PROJECT_MEMBER)),
        "manage": view and (is_owner or role >= PROJECT_ADMIN),
        "admin": role >= PROJECT_ADMIN,
    }


def ancestry(page_id):
    """[(id, owned_by_id, access)] for the page and its ancestors, nearest first."""
    with connection.cursor() as cursor:
        cursor.execute(_ANCESTRY_SQL, [page_id])
        return cursor.fetchall()


def restriction_blocks(page_id, user, is_admin):
    """{"view": bool, "edit": bool}: whether inherited privacy or restrictions block the user."""
    chain = ancestry(page_id)
    owners = {node_id: owner_id for node_id, owner_id, _ in chain}
    # a private ancestor hides its sub-tree from everyone but that ancestor's owner
    view_blocked = any(access == Page.PRIVATE_ACCESS and owner_id != user.id for _, owner_id, access in chain[1:])
    edit_blocked = False
    if not is_admin:
        restricted = {}
        for node_id, kind, member_id in PageRestriction.objects.filter(page_id__in=list(owners)).values_list(
            "page_id", "kind", "member_id"
        ):
            restricted.setdefault((node_id, kind), set()).add(member_id)
        for (node_id, kind), members in restricted.items():
            if user.id in members or owners[node_id] == user.id:
                continue
            if kind == PageRestriction.VIEW:
                view_blocked = True
            else:
                edit_blocked = True
    return {"view": view_blocked, "edit": edit_blocked}


def page_permissions(page, user, project_id=None, space_role=wiki._UNSET):
    """
    {can_view, can_edit, can_manage, can_edit_content} for a wiki or project page.

    project_id scopes a project page to the project in the URL; space_role can be
    passed when the caller already resolved it.
    """
    if user is None or user.is_anonymous:
        return dict(DENIED)
    if page.space_id is not None:
        if space_role is wiki._UNSET:
            space_role = wiki.space_role(page.space, user)
        base = _base_wiki(page, user, space_role)
    else:
        base = _base_project(page, user, project_id)
    if base is None or not base["view"]:
        return dict(DENIED)
    blocks = restriction_blocks(page.id, user, base["admin"])
    if blocks["view"]:
        return dict(DENIED)
    can_edit = base["edit"] and not blocks["edit"]
    can_manage = base["manage"] and not blocks["edit"]
    return {
        "can_view": True,
        "can_edit": can_edit,
        "can_manage": can_manage,
        # what a live editor may do right now (locked and archived pages are read-only)
        "can_edit_content": can_edit and not page.is_locked and not page.archived_at,
    }


def restriction_candidates(page):
    """Users who may be listed in the page's restrictions: everyone with a base role on it."""
    if page.space_id is not None:
        members = WorkspaceMember.objects.filter(
            workspace_id=page.workspace_id, is_active=True, role__gte=wiki.WORKSPACE_MEMBER
        )
        if page.space.access != WikiSpace.ACCESS_OPEN:
            members = members.filter(
                Q(role__gte=wiki.WORKSPACE_ADMIN)
                | Q(member_id__in=WikiSpaceMember.objects.filter(space_id=page.space_id).values("member_id"))
            )
        return User.objects.filter(id__in=members.values("member_id"))
    project_ids = ProjectPage.objects.filter(page_id=page.id).values("project_id")
    return User.objects.filter(
        id__in=ProjectMember.objects.filter(project_id__in=project_ids, is_active=True).values("member_id")
    )
