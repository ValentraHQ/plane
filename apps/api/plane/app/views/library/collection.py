# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Library tags and collections (shelves). Access rules live in plane.utils.book_access."""

# Python imports
from collections import Counter

# Django imports
from django.db import transaction
from django.db.models import Count, Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.serializers.library import BookCollectionSerializer
from plane.db.models import Book, BookCollection, BookCollectionItem
from plane.utils.book_access import collection_permissions, viewable_books, viewable_collections

from .base import LibraryBaseEndpoint, _forbidden, _is_uuid

MAX_BOOKS_PER_REQUEST = 200


def _with_counts(collections, user):
    """Count only books the user can see (shared shelves only hold workspace books, but be strict)."""
    visible = Q(items__deleted_at__isnull=True, items__book__deleted_at__isnull=True) & (
        Q(items__book__visibility=Book.VISIBILITY_WORKSPACE) | Q(items__book__owner_id=user.id)
    )
    return collections.annotate(book_count=Count("items", filter=visible, distinct=True))


class BookTagListEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        counts, spelling = Counter(), {}
        # only books the user can see contribute tags, so tags never reveal private books
        books = viewable_books(self.workspace.id, request.user, role=role).order_by("created_at")
        # the spelling of the earliest book wins
        for tags in books.values_list("tags", flat=True):
            for tag in tags or []:
                key = tag.lower()
                spelling.setdefault(key, tag)
                counts[key] += 1
        result = [{"name": spelling[key], "count": count} for key, count in counts.items()]
        return Response(sorted(result, key=lambda item: item["name"].lower()))


class BookCollectionListEndpoint(LibraryBaseEndpoint):
    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        collections = _with_counts(viewable_collections(self.workspace.id, request.user, role=role), request.user)
        return Response(
            BookCollectionSerializer(collections, many=True, context={"request": request, "role": role}).data
        )

    def post(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        serializer = BookCollectionSerializer(data=request.data, context={"request": request, "role": role})
        serializer.is_valid(raise_exception=True)
        collection = serializer.save(workspace=self.workspace, owner=request.user)
        return Response(
            BookCollectionSerializer(collection, context={"request": request, "role": role}).data,
            status=status.HTTP_201_CREATED,
        )


class BookCollectionDetailEndpoint(LibraryBaseEndpoint):
    def get_collection(self, request, collection_id, role):
        return viewable_collections(self.workspace.id, request.user, role=role).filter(pk=collection_id).first()

    def patch(self, request, slug, collection_id):
        role, error = self.access(request)
        if error:
            return error
        collection = self.get_collection(request, collection_id, role)
        if collection is None:
            return Response({"error": "Collection not found."}, status=status.HTTP_404_NOT_FOUND)
        if not collection_permissions(collection, request.user, role=role)["can_edit"]:
            return _forbidden("Only the owner or a workspace admin can change this collection.")
        serializer = BookCollectionSerializer(
            collection, data=request.data, partial=True, context={"request": request, "role": role}
        )
        serializer.is_valid(raise_exception=True)
        visibility = serializer.validated_data.get("visibility")
        if visibility is not None and visibility != collection.visibility:
            if collection.owner_id != request.user.id:
                return _forbidden("Only the owner can change who can see this collection.")
            personal_items = collection.items.filter(book__visibility=Book.VISIBILITY_PERSONAL).count()
            if visibility == Book.VISIBILITY_WORKSPACE and personal_items:
                return Response(
                    {
                        "error": f"This collection holds {personal_items} personal book(s). Share them with the "
                        "workspace or remove them before sharing the collection."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        serializer.save()
        collection = _with_counts(BookCollection.objects.filter(pk=collection.id), request.user).first()
        return Response(BookCollectionSerializer(collection, context={"request": request, "role": role}).data)

    def delete(self, request, slug, collection_id):
        role, error = self.access(request)
        if error:
            return error
        collection = self.get_collection(request, collection_id, role)
        if collection is None:
            return Response({"error": "Collection not found."}, status=status.HTTP_404_NOT_FOUND)
        if not collection_permissions(collection, request.user, role=role)["can_edit"]:
            return _forbidden("Only the owner or a workspace admin can delete this collection.")
        # the books themselves stay in the library
        with transaction.atomic():
            collection.items.all().delete(soft=False)
            collection.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BookCollectionBooksEndpoint(LibraryBaseEndpoint):
    """Add books to a collection (POST {"book_ids": [...]}) or remove one (DELETE …/books/<book_id>/)."""

    def _editable(self, request, collection_id):
        role, error = self.access(request)
        if error:
            return None, None, error
        collection = viewable_collections(self.workspace.id, request.user, role=role).filter(pk=collection_id).first()
        if collection is None:
            return None, None, Response({"error": "Collection not found."}, status=status.HTTP_404_NOT_FOUND)
        if not collection_permissions(collection, request.user, role=role)["can_edit"]:
            return None, None, _forbidden("Only the owner or a workspace admin can change this collection.")
        return collection, role, None

    def post(self, request, slug, collection_id):
        collection, role, error = self._editable(request, collection_id)
        if error:
            return error
        book_ids = request.data.get("book_ids")
        if (
            not isinstance(book_ids, list)
            or not book_ids
            or len(book_ids) > MAX_BOOKS_PER_REQUEST
            or not all(_is_uuid(book_id) for book_id in book_ids)
        ):
            return Response({"error": "Send a list of book ids."}, status=status.HTTP_400_BAD_REQUEST)
        books = viewable_books(self.workspace.id, request.user, role=role).filter(pk__in=book_ids)
        if books.count() != len(set(map(str, book_ids))):
            return Response({"error": "Some of these books were not found."}, status=status.HTTP_404_NOT_FOUND)
        if (
            collection.visibility == Book.VISIBILITY_WORKSPACE
            and books.filter(visibility=Book.VISIBILITY_PERSONAL).exists()
        ):
            return Response(
                {"error": "Personal books cannot be added to a shared collection. Share the book first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        existing = set(collection.items.values_list("book_id", flat=True))
        BookCollectionItem.objects.bulk_create(
            [
                BookCollectionItem(workspace=self.workspace, collection=collection, book=book)
                for book in books
                if book.id not in existing
            ]
        )
        return Response({"added": len([b for b in books if b.id not in existing])}, status=status.HTTP_200_OK)

    def delete(self, request, slug, collection_id, book_id):
        collection, role, error = self._editable(request, collection_id)
        if error:
            return error
        collection.items.filter(book_id=book_id).delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)
