# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Workspace wiki: is_global pages outside projects, under /workspaces/<slug>/wiki/pages/.
"""

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Page, PageVersion, Project, ProjectMember, ProjectPage, WorkspaceMember
from plane.tests.factories import UserFactory


def _wiki_url(slug, page_id=None, suffix=""):
    base = f"/api/workspaces/{slug}/wiki/pages/"
    return f"{base}{page_id}/{suffix}" if page_id else base


def _wiki_page(workspace, owner, name, parent=None, access=Page.PUBLIC_ACCESS, **extra):
    return Page.objects.create(
        workspace=workspace, owned_by=owner, name=name, parent=parent, access=access, is_global=True, **extra
    )


def _member(workspace, username, role):
    user = UserFactory(username=username, email=f"{username}@plane.so")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


@pytest.fixture
def member(db, workspace):
    return _member(workspace, "wiki-member", 15)


@pytest.mark.contract
class TestWorkspaceWiki:
    @pytest.mark.django_db
    def test_create_top_level_page(self, session_client, workspace):
        response = session_client.post(_wiki_url(workspace.slug), {"name": "Handbook"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        page = Page.objects.get(pk=response.json()["id"])
        assert page.is_global is True
        assert not ProjectPage.objects.filter(page=page).exists()
        assert response.json()["project_ids"] == []

    @pytest.mark.django_db
    def test_list_top_level_and_children(self, session_client, workspace, create_user):
        root = _wiki_page(workspace, create_user, "Root")
        child = _wiki_page(workspace, create_user, "Child", parent=root)

        top = session_client.get(_wiki_url(workspace.slug))
        children = session_client.get(_wiki_url(workspace.slug), {"parent_id": str(root.id)})

        assert [p["id"] for p in top.json()] == [str(root.id)]
        assert top.json()[0]["sub_pages_count"] == 1
        assert [p["id"] for p in children.json()] == [str(child.id)]

    @pytest.mark.django_db
    def test_create_sub_page(self, session_client, workspace, create_user):
        root = _wiki_page(workspace, create_user, "Root")

        response = session_client.post(
            _wiki_url(workspace.slug), {"name": "Sub", "parent": str(root.id)}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["parent"] == str(root.id)

    @pytest.mark.django_db
    def test_wiki_and_project_pages_are_separate(self, session_client, workspace, create_user):
        project = Project.objects.create(name="P", identifier="WKP", workspace=workspace)
        ProjectMember.objects.create(workspace=workspace, project=project, member=create_user, role=20)
        project_page = Page.objects.create(workspace=workspace, owned_by=create_user, name="Project page")
        ProjectPage.objects.create(workspace=workspace, project=project, page=project_page)
        wiki_page = _wiki_page(workspace, create_user, "Wiki page")

        wiki_ids = [p["id"] for p in session_client.get(_wiki_url(workspace.slug)).json()]
        project_ids = [
            p["id"] for p in session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/pages/").json()
        ]

        assert wiki_ids == [str(wiki_page.id)]
        assert project_ids == [str(project_page.id)]
        assert session_client.get(_wiki_url(workspace.slug, project_page.id)).status_code == 404

    @pytest.mark.django_db
    def test_parent_from_a_project_is_rejected(self, session_client, workspace, create_user):
        project = Project.objects.create(name="P", identifier="WKX", workspace=workspace)
        project_page = Page.objects.create(workspace=workspace, owned_by=create_user, name="Project page")
        ProjectPage.objects.create(workspace=workspace, project=project, page=project_page)

        response = session_client.post(
            _wiki_url(workspace.slug), {"name": "x", "parent": str(project_page.id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_private_page_is_hidden_from_other_members(self, workspace, create_user, member):
        _, member_client = member
        private = _wiki_page(workspace, create_user, "Private", access=Page.PRIVATE_ACCESS)
        PageVersion.objects.create(workspace=workspace, page=private, owned_by=create_user)

        listed = [p["id"] for p in member_client.get(_wiki_url(workspace.slug)).json()]

        assert str(private.id) not in listed
        assert member_client.get(_wiki_url(workspace.slug, private.id)).status_code == 404
        assert member_client.get(_wiki_url(workspace.slug, private.id, "description/")).status_code == 404
        assert member_client.get(_wiki_url(workspace.slug, private.id, "versions/")).status_code == 404

    @pytest.mark.django_db
    def test_guests_and_non_members_are_refused(self, db, workspace):
        _, guest_client = _member(workspace, "wiki-guest", 5)
        outsider = UserFactory(username="wiki-outsider", email="wiki-outsider@plane.so")
        outsider_client = APIClient()
        outsider_client.force_authenticate(user=outsider)

        assert guest_client.get(_wiki_url(workspace.slug)).status_code == status.HTTP_403_FORBIDDEN
        assert outsider_client.get(_wiki_url(workspace.slug)).status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_member_cannot_lock_or_archive_others_page_but_admin_can(
        self, session_client, workspace, create_user, member
    ):
        member_user, member_client = member
        page = _wiki_page(workspace, member_user, "Member's page")
        admins_page = _wiki_page(workspace, create_user, "Admin's page")

        assert member_client.post(_wiki_url(workspace.slug, admins_page.id, "lock/")).status_code == 403
        assert member_client.post(_wiki_url(workspace.slug, admins_page.id, "archive/")).status_code == 403
        assert session_client.post(_wiki_url(workspace.slug, page.id, "lock/")).status_code == 204
        assert session_client.post(_wiki_url(workspace.slug, page.id, "archive/")).status_code == 200

    @pytest.mark.django_db
    def test_only_owner_changes_access(self, session_client, workspace, member):
        member_user, member_client = member
        page = _wiki_page(workspace, member_user, "Member's page")

        by_admin = session_client.post(
            _wiki_url(workspace.slug, page.id, "access/"), {"access": Page.PRIVATE_ACCESS}, format="json"
        )
        by_owner = member_client.post(
            _wiki_url(workspace.slug, page.id, "access/"), {"access": Page.PRIVATE_ACCESS}, format="json"
        )

        assert by_admin.status_code == status.HTTP_403_FORBIDDEN
        assert by_owner.status_code == status.HTTP_204_NO_CONTENT
        page.refresh_from_db()
        assert page.access == Page.PRIVATE_ACCESS

    @pytest.mark.django_db
    def test_update_rejects_cycle_and_allows_move(self, session_client, workspace, create_user):
        root = _wiki_page(workspace, create_user, "Root")
        child = _wiki_page(workspace, create_user, "Child", parent=root)
        other = _wiki_page(workspace, create_user, "Other")

        cycle = session_client.patch(_wiki_url(workspace.slug, root.id), {"parent": str(child.id)}, format="json")
        move = session_client.patch(_wiki_url(workspace.slug, child.id), {"parent": str(other.id)}, format="json")

        assert cycle.status_code == status.HTTP_400_BAD_REQUEST
        assert move.status_code == status.HTTP_200_OK
        child.refresh_from_db()
        assert child.parent_id == other.id

    @pytest.mark.django_db
    def test_archive_cascades_and_delete_keeps_children(self, session_client, workspace, create_user):
        root = _wiki_page(workspace, create_user, "Root")
        child = _wiki_page(workspace, create_user, "Child", parent=root)

        not_archived = session_client.delete(_wiki_url(workspace.slug, root.id))
        archived = session_client.post(_wiki_url(workspace.slug, root.id, "archive/"))
        child.refresh_from_db()
        deleted = session_client.delete(_wiki_url(workspace.slug, root.id))

        assert not_archived.status_code == status.HTTP_400_BAD_REQUEST
        assert archived.status_code == status.HTTP_200_OK
        assert child.archived_at is not None
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        child.refresh_from_db()
        assert child.parent_id is None

    @pytest.mark.django_db
    def test_locked_page_description_cannot_change(self, session_client, workspace, create_user):
        page = _wiki_page(workspace, create_user, "Locked", is_locked=True)

        response = session_client.patch(
            _wiki_url(workspace.slug, page.id, "description/"), {"description_html": "<p>x</p>"}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_archived_parent_rejected(self, session_client, workspace, create_user):
        archived = _wiki_page(workspace, create_user, "Old", archived_at=timezone.now().date())

        response = session_client.post(
            _wiki_url(workspace.slug), {"name": "x", "parent": str(archived.id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
