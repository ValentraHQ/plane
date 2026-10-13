# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
The one place that decides who may do what with a library book.

- Guests and non-members: nothing.
- Personal books: the owner only (workspace admins cannot see them).
- Workspace books: every workspace admin and member can view and download; the owner and
  workspace admins can edit metadata and manage the book (visibility, archive, delete, reprocess).

Lists use `viewable_books` (a single query); single books use `book_permissions`. Both must agree;
a test checks that for every user and book. Sharing with specific people or groups would add one
more condition to each, backed by its own table.
"""

# Django imports
from django.db.models import Q

# Module imports
from plane.db.models import Book, WorkspaceMember

ADMIN = 20
MEMBER = 15

_UNSET = object()


def workspace_role(user, workspace_id):
    if user is None or not user.is_authenticated:
        return None
    return (
        WorkspaceMember.objects.filter(workspace_id=workspace_id, member_id=user.id, is_active=True)
        .values_list("role", flat=True)
        .first()
    )


def library_role(user, workspace_id):
    """The user's workspace role if it gives library access (admins and members), else None."""
    role = workspace_role(user, workspace_id)
    return role if role is not None and role >= MEMBER else None


NO_ACCESS = {"can_view": False, "can_download": False, "can_edit": False, "can_manage": False}


def book_permissions(book, user, role=_UNSET):
    if role is _UNSET:
        role = library_role(user, book.workspace_id)
    if role is None or role < MEMBER or book.deleted_at is not None:
        return dict(NO_ACCESS)
    is_owner = book.owner_id == user.id
    if book.visibility == Book.VISIBILITY_PERSONAL:
        allowed = is_owner
        return {"can_view": allowed, "can_download": allowed, "can_edit": allowed, "can_manage": allowed}
    if book.visibility == Book.VISIBILITY_WORKSPACE:
        manager = is_owner or role >= ADMIN
        return {"can_view": True, "can_download": True, "can_edit": manager, "can_manage": manager}
    return dict(NO_ACCESS)


def viewable_books(workspace_id, user, role=_UNSET):
    """Books of the workspace the user may see (same rules as book_permissions)."""
    if role is _UNSET:
        role = library_role(user, workspace_id)
    queryset = Book.objects.filter(workspace_id=workspace_id)
    if role is None or role < MEMBER:
        return queryset.none()
    return queryset.filter(
        Q(visibility=Book.VISIBILITY_WORKSPACE) | Q(visibility=Book.VISIBILITY_PERSONAL, owner_id=user.id)
    )
