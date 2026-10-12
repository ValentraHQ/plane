# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Central authorization for the workspace wiki (documentation spaces and their pages).

Every wiki endpoint, the wiki search and the real-time editor's permission check
must decide access through these functions; do not re-implement the rules in views.

Space role of a user:
  - workspace guests and non-members: none (no wiki access at all)
  - workspace admins: SPACE_ADMIN in every space
  - an explicit WikiSpaceMember row: that role (it overrides the open-space default,
    so an admin can make someone a viewer even in an open space)
  - other workspace members: SPACE_EDITOR in OPEN spaces, none in RESTRICTED spaces

Page rules inside a space:
  - view:   the owner, or anyone with a space role when the page is public
  - edit:   can view and has SPACE_EDITOR or above
  - manage: (lock, archive, delete, move) can view and is a space admin, or the
            owner while still an editor
Inherited privacy and page restrictions then narrow these rules further; page-level
resolution lives in plane.utils.page_access.
"""

# Django imports
from django.db.models import Q

# Module imports
from plane.db.models import Page, WikiSpace, WikiSpaceMember, Workspace, WorkspaceMember

WORKSPACE_ADMIN = 20
WORKSPACE_MEMBER = 15

SPACE_ADMIN = WikiSpaceMember.ROLE_ADMIN
SPACE_EDITOR = WikiSpaceMember.ROLE_EDITOR
SPACE_VIEWER = WikiSpaceMember.ROLE_VIEWER

_UNSET = object()


def workspace_role(user, slug=None, workspace_id=None):
    """Active workspace role of the user, or None."""
    if user is None or user.is_anonymous:
        return None
    filters = {"member": user, "is_active": True}
    if workspace_id:
        filters["workspace_id"] = workspace_id
    else:
        filters["workspace__slug"] = slug
    return WorkspaceMember.objects.filter(**filters).values_list("role", flat=True).first()


def space_role(space, user, ws_role=_UNSET):
    """Effective role of the user in the space, or None if they cannot access it."""
    if ws_role is _UNSET:
        ws_role = workspace_role(user, workspace_id=space.workspace_id)
    if ws_role is None or ws_role < WORKSPACE_MEMBER:
        return None
    if ws_role >= WORKSPACE_ADMIN:
        return SPACE_ADMIN
    explicit = WikiSpaceMember.objects.filter(space_id=space.id, member=user).values_list("role", flat=True).first()
    if explicit is not None:
        return explicit
    if space.access == WikiSpace.ACCESS_OPEN:
        return SPACE_EDITOR
    return None


def space_roles(spaces, user, ws_role=_UNSET):
    """{space_id: role} for many spaces with one membership query."""
    spaces = list(spaces)
    if not spaces:
        return {}
    if ws_role is _UNSET:
        ws_role = workspace_role(user, workspace_id=spaces[0].workspace_id)
    if ws_role is None or ws_role < WORKSPACE_MEMBER:
        return {space.id: None for space in spaces}
    if ws_role >= WORKSPACE_ADMIN:
        return {space.id: SPACE_ADMIN for space in spaces}
    explicit = dict(
        WikiSpaceMember.objects.filter(space_id__in=[s.id for s in spaces], member=user).values_list("space_id", "role")
    )
    roles = {}
    for space in spaces:
        if space.id in explicit:
            roles[space.id] = explicit[space.id]
        elif space.access == WikiSpace.ACCESS_OPEN:
            roles[space.id] = SPACE_EDITOR
        else:
            roles[space.id] = None
    return roles


def viewable_spaces(slug, user):
    """Spaces of the workspace the user can see (any space role)."""
    ws_role = workspace_role(user, slug=slug)
    queryset = WikiSpace.objects.filter(workspace__slug=slug)
    if ws_role is None or ws_role < WORKSPACE_MEMBER:
        return queryset.none()
    if ws_role >= WORKSPACE_ADMIN:
        return queryset
    # explicit memberships win over the open default, so compute the allowed ids explicitly
    member_space_ids = WikiSpaceMember.objects.filter(member=user, space__workspace__slug=slug).values_list(
        "space_id", flat=True
    )
    return queryset.filter(Q(access=WikiSpace.ACCESS_OPEN) | Q(id__in=member_space_ids))


def viewable_wiki_pages(slug, user):
    """Wiki pages the user can see: in a space they can access, public or their own, and not
    hidden by a private or view-restricted ancestor (see plane.utils.page_access)."""
    from plane.utils.page_access import exclude_hidden

    pages = Page.objects.filter(
        workspace__slug=slug,
        is_global=True,
        space__in=viewable_spaces(slug, user),
    ).filter(Q(owned_by=user) | Q(access=Page.PUBLIC_ACCESS))
    workspace_id = Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()
    if workspace_id is None:
        return pages.none()
    return exclude_hidden(pages, user, workspace_id)


def page_permissions(page, user, role=_UNSET):
    """{can_view, can_edit, can_manage, can_edit_content} for a wiki page, restrictions included."""
    from plane.utils.page_access import DENIED, page_permissions as resolve

    if not page.is_global or page.space_id is None:
        return dict(DENIED)
    return resolve(page, user, space_role=role)
