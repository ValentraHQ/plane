# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Nested pages: child pages are reachable, listed per parent, and the parent
link is validated (same project, not archived, no cycles).
"""

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import Page, Project, ProjectMember, ProjectPage
from plane.tests.factories import UserFactory


def _make_project(workspace, user, identifier):
    project = Project.objects.create(name=identifier, identifier=identifier, workspace=workspace)
    ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=20, is_active=True)
    return project


def _make_page(workspace, project, user, name, parent=None, **extra):
    page = Page.objects.create(
        workspace=workspace, owned_by=user, access=Page.PUBLIC_ACCESS, name=name, parent=parent, **extra
    )
    ProjectPage.objects.create(workspace=workspace, project=project, page=page)
    return page


def _pages_url(slug, project_id):
    return f"/api/workspaces/{slug}/projects/{project_id}/pages/"


def _page_url(slug, project_id, page_id):
    return f"{_pages_url(slug, project_id)}{page_id}/"


@pytest.fixture
def tree(db, workspace, create_user):
    """root -> child -> grandchild, all in one project."""
    project = _make_project(workspace, create_user, "NST")
    root = _make_page(workspace, project, create_user, "Root")
    child = _make_page(workspace, project, create_user, "Child", parent=root)
    grandchild = _make_page(workspace, project, create_user, "Grandchild", parent=child)
    return project, root, child, grandchild


@pytest.mark.contract
class TestNestedPages:
    @pytest.mark.django_db
    def test_child_page_can_be_retrieved(self, session_client, workspace, tree):
        project, _, child, _ = tree

        response = session_client.get(_page_url(workspace.slug, project.id, child.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["parent"] == str(child.parent_id)

    @pytest.mark.django_db
    def test_hidden_page_returns_error_not_500(self, session_client, workspace, tree):
        """Another member's private (nested) page must be refused cleanly, never a 500.
        Guards retrieve, which now returns 404 when the queryset hides the page."""
        project, root, _, _ = tree
        other = UserFactory(username="other-member", email="other-member@plane.so")
        ProjectMember.objects.create(workspace=workspace, project=project, member=other, role=20, is_active=True)
        private = _make_page(workspace, project, other, "Private", parent=root)
        Page.objects.filter(pk=private.pk).update(access=Page.PRIVATE_ACCESS)

        response = session_client.get(_page_url(workspace.slug, project.id, private.id))

        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    @pytest.mark.django_db
    def test_list_defaults_to_top_level_with_sub_page_count(self, session_client, workspace, tree):
        project, root, _, _ = tree

        response = session_client.get(_pages_url(workspace.slug, project.id))

        assert response.status_code == status.HTTP_200_OK
        pages = response.json()
        assert [p["id"] for p in pages] == [str(root.id)]
        assert pages[0]["sub_pages_count"] == 1

    @pytest.mark.django_db
    def test_list_children_by_parent_id(self, session_client, workspace, tree):
        project, root, child, _ = tree

        response = session_client.get(_pages_url(workspace.slug, project.id), {"parent_id": str(root.id)})

        assert response.status_code == status.HTTP_200_OK
        assert [p["id"] for p in response.json()] == [str(child.id)]

    @pytest.mark.django_db
    def test_list_rejects_invalid_parent_id(self, session_client, workspace, tree):
        project = tree[0]

        response = session_client.get(_pages_url(workspace.slug, project.id), {"parent_id": "not-a-uuid"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_archived_children_are_not_counted(self, session_client, workspace, create_user, tree):
        project, root, child, _ = tree
        _make_page(workspace, project, create_user, "Old", parent=root, archived_at=timezone.now().date())

        response = session_client.get(_pages_url(workspace.slug, project.id))

        assert response.json()[0]["sub_pages_count"] == 1

    @pytest.mark.django_db
    def test_create_under_parent_in_same_project(self, session_client, workspace, tree):
        project, root, _, _ = tree

        response = session_client.post(
            _pages_url(workspace.slug, project.id), {"name": "New child", "parent": str(root.id)}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["parent"] == str(root.id)

    @pytest.mark.django_db
    def test_create_rejects_parent_from_another_project(self, session_client, workspace, create_user, tree):
        project = tree[0]
        other_project = _make_project(workspace, create_user, "OTH")
        foreign = _make_page(workspace, other_project, create_user, "Foreign")

        response = session_client.post(
            _pages_url(workspace.slug, project.id), {"name": "x", "parent": str(foreign.id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Page.objects.filter(name="x").exists()

    @pytest.mark.django_db
    def test_create_rejects_archived_parent(self, session_client, workspace, create_user, tree):
        project = tree[0]
        archived = _make_page(workspace, project, create_user, "Archived", archived_at=timezone.now().date())

        response = session_client.post(
            _pages_url(workspace.slug, project.id), {"name": "x", "parent": str(archived.id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_update_rejects_self_as_parent(self, session_client, workspace, tree):
        project, root, _, _ = tree

        response = session_client.patch(
            _page_url(workspace.slug, project.id, root.id), {"parent": str(root.id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_update_rejects_descendant_as_parent(self, session_client, workspace, tree):
        project, root, _, grandchild = tree

        response = session_client.patch(
            _page_url(workspace.slug, project.id, root.id), {"parent": str(grandchild.id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        root.refresh_from_db()
        assert root.parent_id is None

    @pytest.mark.django_db
    def test_update_moves_page_and_back_to_top_level(self, session_client, workspace, tree):
        project, root, child, grandchild = tree

        moved = session_client.patch(
            _page_url(workspace.slug, project.id, grandchild.id), {"parent": str(root.id)}, format="json"
        )
        to_top = session_client.patch(_page_url(workspace.slug, project.id, child.id), {"parent": None}, format="json")

        assert moved.status_code == status.HTTP_200_OK
        assert to_top.status_code == status.HTTP_200_OK
        grandchild.refresh_from_db()
        child.refresh_from_db()
        assert grandchild.parent_id == root.id
        assert child.parent_id is None
