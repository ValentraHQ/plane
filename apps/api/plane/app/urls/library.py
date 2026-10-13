# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views.library.base import (
    BookChapterEndpoint,
    BookChapterListEndpoint,
    BookDetailEndpoint,
    BookDownloadEndpoint,
    BookListEndpoint,
    BookReprocessEndpoint,
    BookUploadCompleteEndpoint,
)

urlpatterns = [
    path("workspaces/<str:slug>/library/books/", BookListEndpoint.as_view(), name="library-books"),
    path("workspaces/<str:slug>/library/books/<uuid:book_id>/", BookDetailEndpoint.as_view(), name="library-book"),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/upload-complete/",
        BookUploadCompleteEndpoint.as_view(),
        name="library-book-upload-complete",
    ),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/reprocess/",
        BookReprocessEndpoint.as_view(),
        name="library-book-reprocess",
    ),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/download/",
        BookDownloadEndpoint.as_view(),
        name="library-book-download",
    ),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/chapters/",
        BookChapterListEndpoint.as_view(),
        name="library-book-chapters",
    ),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/chapters/<int:index>/",
        BookChapterEndpoint.as_view(),
        name="library-book-chapter",
    ),
]
