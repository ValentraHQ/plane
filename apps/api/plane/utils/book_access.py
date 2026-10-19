# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
The one place that decides who may do what with a library book.

- Guests and non-members: nothing.
- Personal books: the owner only (workspace admins cannot see them).
- Workspace books: every workspace admin and member can view and download; the owner and
  workspace admins can edit metadata and manage the book (visibility, archive, delete, reprocess).

Collections (shelves) follow the same rules: personal ones are the owner's, workspace ones are
visible to admins and members and managed by their owner and workspace admins.

Annotations (highlights, notes, bookmarks) are their author's. A shared annotation is visible to
everyone who can see the book, and only while the book is a workspace book. Only the author edits
an annotation; workspace admins may also remove shared ones.

Lists use `viewable_books` (a single query); single books use `book_permissions`. Both must agree;
a test checks that for every user and book. Sharing with specific people or groups would add one
more condition to each, backed by its own table.
"""

# Django imports
from django.db.models import Q

# Module imports
from plane.db.models import Book, BookAnnotation, BookCollection, WorkspaceMember

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


def collection_permissions(collection, user, role=_UNSET):
    if role is _UNSET:
        role = library_role(user, collection.workspace_id)
    if role is None or role < MEMBER or collection.deleted_at is not None:
        return {"can_view": False, "can_edit": False}
    is_owner = collection.owner_id == user.id
    if collection.visibility == Book.VISIBILITY_PERSONAL:
        return {"can_view": is_owner, "can_edit": is_owner}
    return {"can_view": True, "can_edit": is_owner or role >= ADMIN}


def viewable_collections(workspace_id, user, role=_UNSET):
    if role is _UNSET:
        role = library_role(user, workspace_id)
    queryset = BookCollection.objects.filter(workspace_id=workspace_id)
    if role is None or role < MEMBER:
        return queryset.none()
    return queryset.filter(
        Q(visibility=Book.VISIBILITY_WORKSPACE) | Q(visibility=Book.VISIBILITY_PERSONAL, owner_id=user.id)
    )


def visible_annotations(user, books):
    """Annotations the user can see on the given books (which the caller already checked they can see)."""
    return BookAnnotation.objects.filter(book__in=books).filter(
        Q(user_id=user.id) | Q(visibility=BookAnnotation.VISIBILITY_SHARED, book__visibility=Book.VISIBILITY_WORKSPACE)
    )


def annotation_permissions(annotation, user, role):
    is_author = annotation.user_id == user.id
    shared = (
        annotation.visibility == BookAnnotation.VISIBILITY_SHARED
        and annotation.book.visibility == Book.VISIBILITY_WORKSPACE
    )
    return {"can_edit": is_author, "can_delete": is_author or (shared and role is not None and role >= ADMIN)}
