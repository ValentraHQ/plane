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
from plane.app.views.library.annotations import (
    AnnotationDetailEndpoint,
    AnnotationExportEndpoint,
    BookAnnotationListEndpoint,
    MyAnnotationsEndpoint,
)
from plane.app.views.library.links import (
    BookLinkDetailEndpoint,
    BookLinkListEndpoint,
    BookWikiPageEndpoint,
    LinkedBooksEndpoint,
    LinkTargetSearchEndpoint,
)
from plane.app.views.library.reading import (
    BookReadingStateEndpoint,
    BookSearchEndpoint,
    ContinueReadingEndpoint,
    ReaderPreferencesEndpoint,
)
from plane.app.views.library.collection import (
    BookCollectionBooksEndpoint,
    BookCollectionDetailEndpoint,
    BookCollectionListEndpoint,
    BookTagListEndpoint,
)

urlpatterns = [
    path("workspaces/<str:slug>/library/annotations/", MyAnnotationsEndpoint.as_view(), name="library-annotations"),
    path(
        "workspaces/<str:slug>/library/annotations/export/",
        AnnotationExportEndpoint.as_view(),
        name="library-annotations-export",
    ),
    path(
        "workspaces/<str:slug>/library/annotations/<uuid:annotation_id>/",
        AnnotationDetailEndpoint.as_view(),
        name="library-annotation",
    ),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/links/",
        BookLinkListEndpoint.as_view(),
        name="library-book-links",
    ),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/wiki-pages/",
        BookWikiPageEndpoint.as_view(),
        name="library-book-wiki-pages",
    ),
    path(
        "workspaces/<str:slug>/library/links/",
        LinkedBooksEndpoint.as_view(),
        name="library-linked-books",
    ),
    path(
        "workspaces/<str:slug>/library/links/<uuid:link_id>/",
        BookLinkDetailEndpoint.as_view(),
        name="library-link",
    ),
    path(
        "workspaces/<str:slug>/library/link-targets/",
        LinkTargetSearchEndpoint.as_view(),
        name="library-link-targets",
    ),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/annotations/",
        BookAnnotationListEndpoint.as_view(),
        name="library-book-annotations",
    ),
    path(
        "workspaces/<str:slug>/library/continue-reading/",
        ContinueReadingEndpoint.as_view(),
        name="library-continue-reading",
    ),
    path(
        "workspaces/<str:slug>/library/reader-preferences/",
        ReaderPreferencesEndpoint.as_view(),
        name="library-reader-preferences",
    ),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/reading-state/",
        BookReadingStateEndpoint.as_view(),
        name="library-book-reading-state",
    ),
    path(
        "workspaces/<str:slug>/library/books/<uuid:book_id>/search/",
        BookSearchEndpoint.as_view(),
        name="library-book-search",
    ),
    path("workspaces/<str:slug>/library/tags/", BookTagListEndpoint.as_view(), name="library-tags"),
    path(
        "workspaces/<str:slug>/library/collections/", BookCollectionListEndpoint.as_view(), name="library-collections"
    ),
    path(
        "workspaces/<str:slug>/library/collections/<uuid:collection_id>/",
        BookCollectionDetailEndpoint.as_view(),
        name="library-collection",
    ),
    path(
        "workspaces/<str:slug>/library/collections/<uuid:collection_id>/books/",
        BookCollectionBooksEndpoint.as_view(),
        name="library-collection-books",
    ),
    path(
        "workspaces/<str:slug>/library/collections/<uuid:collection_id>/books/<uuid:book_id>/",
        BookCollectionBooksEndpoint.as_view(),
        name="library-collection-book",
    ),
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
