# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path


from plane.app.views import (
    PageViewSet,
    PageFavoriteViewSet,
    PagesDescriptionViewSet,
    PageVersionEndpoint,
    PageDuplicateEndpoint,
    WorkspacePageViewSet,
    WorkspacePagesDescriptionViewSet,
    WorkspacePageVersionEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages-summary/",
        PageViewSet.as_view({"get": "summary"}),
        name="project-pages-summary",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/",
        PageViewSet.as_view({"get": "list", "post": "create"}),
        name="project-pages",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/",
        PageViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="project-pages",
    ),
    # favorite pages
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/favorite-pages/<uuid:page_id>/",
        PageFavoriteViewSet.as_view({"post": "create", "delete": "destroy"}),
        name="user-favorite-pages",
    ),
    # archived pages
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/archive/",
        PageViewSet.as_view({"post": "archive", "delete": "unarchive"}),
        name="project-page-archive-unarchive",
    ),
    # lock and unlock
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/lock/",
        PageViewSet.as_view({"post": "lock", "delete": "unlock"}),
        name="project-pages-lock-unlock",
    ),
    # private and public page
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/access/",
        PageViewSet.as_view({"post": "access"}),
        name="project-pages-access",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/description/",
        PagesDescriptionViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="page-description",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/versions/",
        PageVersionEndpoint.as_view(),
        name="page-versions",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/versions/<uuid:pk>/",
        PageVersionEndpoint.as_view(),
        name="page-versions",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/duplicate/",
        PageDuplicateEndpoint.as_view(),
        name="page-duplicate",
    ),
    # workspace wiki (pages outside projects)
    path(
        "workspaces/<str:slug>/wiki/pages/",
        WorkspacePageViewSet.as_view({"get": "list", "post": "create"}),
        name="workspace-wiki-pages",
    ),
    path(
        "workspaces/<str:slug>/wiki/pages/<uuid:page_id>/",
        WorkspacePageViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="workspace-wiki-pages",
    ),
    path(
        "workspaces/<str:slug>/wiki/pages/<uuid:page_id>/archive/",
        WorkspacePageViewSet.as_view({"post": "archive", "delete": "unarchive"}),
        name="workspace-wiki-page-archive-unarchive",
    ),
    path(
        "workspaces/<str:slug>/wiki/pages/<uuid:page_id>/lock/",
        WorkspacePageViewSet.as_view({"post": "lock", "delete": "unlock"}),
        name="workspace-wiki-page-lock-unlock",
    ),
    path(
        "workspaces/<str:slug>/wiki/pages/<uuid:page_id>/access/",
        WorkspacePageViewSet.as_view({"post": "access"}),
        name="workspace-wiki-page-access",
    ),
    path(
        "workspaces/<str:slug>/wiki/pages/<uuid:page_id>/description/",
        WorkspacePagesDescriptionViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="workspace-wiki-page-description",
    ),
    path(
        "workspaces/<str:slug>/wiki/pages/<uuid:page_id>/versions/",
        WorkspacePageVersionEndpoint.as_view(),
        name="workspace-wiki-page-versions",
    ),
    path(
        "workspaces/<str:slug>/wiki/pages/<uuid:page_id>/versions/<uuid:pk>/",
        WorkspacePageVersionEndpoint.as_view(),
        name="workspace-wiki-page-versions",
    ),
]
