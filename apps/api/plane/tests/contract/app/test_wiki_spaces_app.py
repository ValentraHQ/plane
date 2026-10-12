# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Documentation spaces: space CRUD, members, the space permission matrix applied to
every wiki page endpoint, moving pages, the sidebar tree, and the permission
endpoint used to authorize real-time editing connections.
"""

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    Page,
    PageVersion,
    Project,
    ProjectMember,
    ProjectPage,
    WikiSpace,
    WikiSpaceMember,
    WorkspaceMember,
)
from plane.tests.factories import UserFactory

ADMIN, MEMBER, GUEST = 20, 15, 5


def _api(slug, path=""):
    return f"/api/workspaces/{slug}/wiki/{path}"


def _client_for(workspace, username, role):
    user = UserFactory(username=username, email=f"{username}@plane.so")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _space(workspace, identifier, access=WikiSpace.ACCESS_OPEN, **extra):
    return WikiSpace.objects.create(
        workspace=workspace, name=identifier.title(), identifier=identifier, access=access, **extra
    )


def _page(space, owner, name, parent=None, access=Page.PUBLIC_ACCESS, **extra):
    return Page.objects.create(
        workspace=space.workspace,
        space=space,
        owned_by=owner,
        name=name,
        parent=parent,
        access=access,
        is_global=True,
        **extra,
    )


@pytest.fixture
def people(db, workspace):
    """Workspace admin = the session user; plus a member, a second member and a guest."""
    member, member_client = _client_for(workspace, "sp-member", MEMBER)
    other, other_client = _client_for(workspace, "sp-other", MEMBER)
    guest, guest_client = _client_for(workspace, "sp-guest", GUEST)
    return {
        "member": member,
        "member_client": member_client,
        "other": other,
        "other_client": other_client,
        "guest": guest,
        "guest_client": guest_client,
    }


@pytest.mark.contract
class TestWikiSpaceCrud:
    @pytest.mark.django_db
    def test_member_creates_space_and_becomes_its_admin(self, workspace, people):
        response = people["member_client"].post(
            _api(workspace.slug, "spaces/"), {"name": "Engineering", "identifier": "eng"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["identifier"] == "ENG"
        assert response.json()["my_role"] == WikiSpaceMember.ROLE_ADMIN
        assert WikiSpaceMember.objects.filter(
            space_id=response.json()["id"], member=people["member"], role=WikiSpaceMember.ROLE_ADMIN
        ).exists()

    @pytest.mark.django_db
    @pytest.mark.parametrize("identifier", ["x", "TOO-LONG-IDENT", "has space", ""])
    def test_invalid_identifier_is_rejected(self, session_client, workspace, identifier):
        response = session_client.post(
            _api(workspace.slug, "spaces/"), {"name": "N", "identifier": identifier}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_duplicate_identifier_is_rejected(self, session_client, workspace):
        _space(workspace, "ENG")

        response = session_client.post(
            _api(workspace.slug, "spaces/"), {"name": "Again", "identifier": "eng"}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_guest_has_no_wiki_access(self, workspace, people):
        _space(workspace, "ENG")

        assert people["guest_client"].get(_api(workspace.slug, "spaces/")).status_code == 403
        assert (
            people["guest_client"]
            .post(_api(workspace.slug, "spaces/"), {"name": "G", "identifier": "GG"}, format="json")
            .status_code
            == 403
        )

    @pytest.mark.django_db
    def test_list_shows_open_and_member_spaces_with_roles(self, session_client, workspace, people):
        open_space = _space(workspace, "OPEN")
        restricted = _space(workspace, "SECRET", access=WikiSpace.ACCESS_RESTRICTED)
        joined = _space(workspace, "JOINED", access=WikiSpace.ACCESS_RESTRICTED)
        WikiSpaceMember.objects.create(
            workspace=workspace, space=joined, member=people["member"], role=WikiSpaceMember.ROLE_VIEWER
        )

        member_view = {
            s["identifier"]: s["my_role"] for s in people["member_client"].get(_api(workspace.slug, "spaces/")).json()
        }
        admin_view = {s["identifier"] for s in session_client.get(_api(workspace.slug, "spaces/")).json()}

        assert member_view == {"OPEN": WikiSpaceMember.ROLE_EDITOR, "JOINED": WikiSpaceMember.ROLE_VIEWER}
        assert admin_view == {"OPEN", "SECRET", "JOINED"}
        assert restricted.identifier not in member_view and open_space.identifier in member_view

    @pytest.mark.django_db
    def test_page_count_only_counts_visible_pages(self, workspace, create_user, people):
        space = _space(workspace, "ENG")
        _page(space, create_user, "Public")
        _page(space, create_user, "Admin private", access=Page.PRIVATE_ACCESS)
        _page(space, create_user, "Archived", archived_at=timezone.now().date())

        spaces = people["member_client"].get(_api(workspace.slug, "spaces/")).json()

        assert spaces[0]["page_count"] == 1

    @pytest.mark.django_db
    def test_only_space_admin_updates_space(self, workspace, people):
        space = _space(workspace, "ENG")

        by_editor = people["member_client"].patch(
            _api(workspace.slug, f"spaces/{space.id}/"), {"name": "X"}, format="json"
        )
        WikiSpaceMember.objects.create(
            workspace=workspace, space=space, member=people["member"], role=WikiSpaceMember.ROLE_ADMIN
        )
        by_admin = people["member_client"].patch(
            _api(workspace.slug, f"spaces/{space.id}/"), {"name": "Eng docs"}, format="json"
        )

        assert by_editor.status_code == status.HTTP_403_FORBIDDEN
        assert by_admin.status_code == status.HTTP_200_OK
        assert by_admin.json()["name"] == "Eng docs"

    @pytest.mark.django_db
    def test_delete_rules(self, session_client, workspace, create_user):
        with_pages = _space(workspace, "FULL")
        _page(with_pages, create_user, "Keep me", access=Page.PRIVATE_ACCESS)
        default = _space(workspace, "GENERAL", is_default=True)
        empty = _space(workspace, "EMPTY")

        assert session_client.delete(_api(workspace.slug, f"spaces/{with_pages.id}/")).status_code == 400
        assert session_client.delete(_api(workspace.slug, f"spaces/{default.id}/")).status_code == 400
        assert session_client.delete(_api(workspace.slug, f"spaces/{empty.id}/")).status_code == 204
        assert not WikiSpace.objects.filter(pk=empty.id).exists()


@pytest.mark.contract
class TestWikiSpaceMembers:
    @pytest.mark.django_db
    def test_admin_manages_members(self, session_client, workspace, people):
        space = _space(workspace, "ENG", access=WikiSpace.ACCESS_RESTRICTED)
        url = _api(workspace.slug, f"spaces/{space.id}/members/")

        added = session_client.post(url, {"member": str(people["member"].id), "role": 5}, format="json")
        duplicate = session_client.post(url, {"member": str(people["member"].id), "role": 5}, format="json")
        guest = session_client.post(url, {"member": str(people["guest"].id), "role": 15}, format="json")
        changed = session_client.patch(f"{url}{added.json()['id']}/", {"role": 15}, format="json")
        listed = session_client.get(url)
        removed = session_client.delete(f"{url}{added.json()['id']}/")

        assert added.status_code == 201
        assert duplicate.status_code == 400
        assert guest.status_code == 400
        assert changed.json()["role"] == 15
        assert [m["member"] for m in listed.json()] == [str(people["member"].id)]
        assert removed.status_code == 204
        assert not WikiSpaceMember.objects.filter(space=space, member=people["member"]).exists()

    @pytest.mark.django_db
    def test_non_admin_cannot_manage_members(self, workspace, people):
        space = _space(workspace, "ENG")

        response = people["member_client"].post(
            _api(workspace.slug, f"spaces/{space.id}/members/"), {"member": str(people["other"].id)}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.contract
class TestWikiSpacePagePermissions:
    @pytest.mark.django_db
    def test_restricted_space_is_invisible_to_non_members(self, workspace, create_user, people):
        space = _space(workspace, "SECRET", access=WikiSpace.ACCESS_RESTRICTED)
        page = _page(space, create_user, "Secret plan")
        PageVersion.objects.create(workspace=workspace, page=page, owned_by=create_user)
        c, slug = people["member_client"], workspace.slug

        assert c.get(_api(slug, f"spaces/{space.id}/")).status_code == 404
        assert c.get(_api(slug, f"spaces/{space.id}/pages-tree/")).status_code == 404
        assert c.get(_api(slug, "pages/"), {"space_id": str(space.id)}).status_code == 404
        assert str(page.id) not in [p["id"] for p in c.get(_api(slug, "pages/")).json()]
        for suffix in ["", "description/", "versions/", "permissions/"]:
            assert c.get(_api(slug, f"pages/{page.id}/{suffix}")).status_code == 404, suffix
        assert c.patch(_api(slug, f"pages/{page.id}/"), {"name": "x"}, format="json").status_code == 404
        assert c.post(_api(slug, "pages/"), {"name": "x", "space": str(space.id)}, format="json").status_code == 400

    @pytest.mark.django_db
    def test_viewer_can_read_but_not_write(self, workspace, create_user, people):
        space = _space(workspace, "DOCS", access=WikiSpace.ACCESS_RESTRICTED)
        WikiSpaceMember.objects.create(
            workspace=workspace, space=space, member=people["member"], role=WikiSpaceMember.ROLE_VIEWER
        )
        page = _page(space, create_user, "Guide")
        c, slug = people["member_client"], workspace.slug

        assert c.get(_api(slug, f"pages/{page.id}/")).status_code == 200
        assert c.get(_api(slug, f"pages/{page.id}/description/")).status_code == 200
        assert c.get(_api(slug, f"pages/{page.id}/permissions/")).json() == {
            "can_view": True,
            "can_edit": False,
            "can_manage": False,
            "can_edit_content": False,
        }
        assert c.patch(_api(slug, f"pages/{page.id}/"), {"name": "x"}, format="json").status_code == 403
        assert (
            c.patch(
                _api(slug, f"pages/{page.id}/description/"), {"description_html": "<p>x</p>"}, format="json"
            ).status_code
            == 403
        )
        assert c.post(_api(slug, "pages/"), {"name": "x", "space": str(space.id)}, format="json").status_code == 403
        assert c.post(_api(slug, f"pages/{page.id}/archive/")).status_code == 403

    @pytest.mark.django_db
    def test_explicit_viewer_overrides_open_space_default(self, workspace, create_user, people):
        space = _space(workspace, "OPEN")
        WikiSpaceMember.objects.create(
            workspace=workspace, space=space, member=people["member"], role=WikiSpaceMember.ROLE_VIEWER
        )
        page = _page(space, create_user, "Guide")

        response = people["member_client"].patch(
            _api(workspace.slug, f"pages/{page.id}/"), {"name": "x"}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_editor_edits_but_cannot_manage_others_pages(self, workspace, create_user, people):
        space = _space(workspace, "OPEN")
        page = _page(space, create_user, "Admin's page")
        c, slug = people["member_client"], workspace.slug

        assert c.patch(_api(slug, f"pages/{page.id}/"), {"name": "Renamed"}, format="json").status_code == 200
        assert c.post(_api(slug, f"pages/{page.id}/lock/")).status_code == 403
        assert c.post(_api(slug, f"pages/{page.id}/archive/")).status_code == 403
        assert c.post(_api(slug, f"pages/{page.id}/move/"), {"parent": None}, format="json").status_code == 403

    @pytest.mark.django_db
    def test_locked_and_archived_pages_are_read_only_for_live_editing(self, session_client, workspace, create_user):
        space = _space(workspace, "OPEN")
        locked = _page(space, create_user, "Locked", is_locked=True)
        archived = _page(space, create_user, "Archived", archived_at=timezone.now().date())

        for page in (locked, archived):
            perms = session_client.get(_api(workspace.slug, f"pages/{page.id}/permissions/")).json()
            assert perms["can_edit"] is True and perms["can_edit_content"] is False

    @pytest.mark.django_db
    def test_create_requires_space_and_matching_parent_space(self, session_client, workspace, create_user):
        eng, ops = _space(workspace, "ENG"), _space(workspace, "OPS")
        root = _page(eng, create_user, "Root")
        slug = workspace.slug

        no_space = session_client.post(_api(slug, "pages/"), {"name": "x"}, format="json")
        mismatch = session_client.post(
            _api(slug, "pages/"), {"name": "x", "parent": str(root.id), "space": str(ops.id)}, format="json"
        )
        child = session_client.post(_api(slug, "pages/"), {"name": "Child", "parent": str(root.id)}, format="json")

        assert no_space.status_code == 400
        assert mismatch.status_code == 400
        assert child.status_code == 201 and child.json()["space"] == str(eng.id)

    @pytest.mark.django_db
    def test_parent_change_by_update_cannot_cross_spaces(self, session_client, workspace, create_user):
        eng, ops = _space(workspace, "ENG"), _space(workspace, "OPS")
        page = _page(eng, create_user, "Page")
        foreign = _page(ops, create_user, "Foreign")

        response = session_client.patch(
            _api(workspace.slug, f"pages/{page.id}/"), {"parent": str(foreign.id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.contract
class TestWikiMove:
    @pytest.mark.django_db
    def test_move_within_space_sets_parent_and_order(self, session_client, workspace, create_user):
        space = _space(workspace, "ENG")
        a, b = _page(space, create_user, "A"), _page(space, create_user, "B")

        response = session_client.post(
            _api(workspace.slug, f"pages/{b.id}/move/"), {"parent": str(a.id), "sort_order": 123.5}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        b.refresh_from_db()
        assert (b.parent_id, b.sort_order, b.space_id) == (a.id, 123.5, space.id)

    @pytest.mark.django_db
    def test_move_to_other_space_takes_the_subtree(self, session_client, workspace, create_user):
        eng, ops = _space(workspace, "ENG"), _space(workspace, "OPS")
        root = _page(eng, create_user, "Root")
        child = _page(eng, create_user, "Child", parent=root)
        grandchild = _page(eng, create_user, "Grandchild", parent=child)

        response = session_client.post(
            _api(workspace.slug, f"pages/{root.id}/move/"), {"space": str(ops.id)}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        for page in (root, child, grandchild):
            page.refresh_from_db()
            assert page.space_id == ops.id
        assert root.parent_id is None and grandchild.parent_id == child.id

    @pytest.mark.django_db
    def test_move_rejects_cycles_archived_pages_and_viewer_targets(self, workspace, create_user, people):
        eng = _space(workspace, "ENG")
        read_only = _space(workspace, "RO", access=WikiSpace.ACCESS_RESTRICTED)
        WikiSpaceMember.objects.create(
            workspace=workspace, space=read_only, member=people["member"], role=WikiSpaceMember.ROLE_VIEWER
        )
        own = _page(eng, people["member"], "Own")
        own_child = _page(eng, people["member"], "Own child", parent=own)
        archived = _page(eng, people["member"], "Archived", archived_at=timezone.now().date())
        c, slug = people["member_client"], workspace.slug

        cycle = c.post(_api(slug, f"pages/{own.id}/move/"), {"parent": str(own_child.id)}, format="json")
        to_viewer_space = c.post(_api(slug, f"pages/{own.id}/move/"), {"space": str(read_only.id)}, format="json")
        moved_archived = c.post(_api(slug, f"pages/{archived.id}/move/"), {"parent": None}, format="json")
        own_move = c.post(_api(slug, f"pages/{own_child.id}/move/"), {"parent": None}, format="json")

        assert cycle.status_code == 400
        assert to_viewer_space.status_code == 403
        assert moved_archived.status_code == 400
        assert own_move.status_code == 200


@pytest.mark.contract
class TestWikiTree:
    @pytest.mark.django_db
    def test_tree_lists_visible_live_pages(self, workspace, create_user, people):
        space = _space(workspace, "ENG")
        root = _page(space, create_user, "Root", sort_order=2)
        child = _page(space, create_user, "Child", parent=root)
        _page(space, create_user, "Admin private", access=Page.PRIVATE_ACCESS)
        _page(space, create_user, "Archived", archived_at=timezone.now().date())
        mine = _page(space, people["member"], "Mine", access=Page.PRIVATE_ACCESS, sort_order=1)

        tree = people["member_client"].get(_api(workspace.slug, f"spaces/{space.id}/pages-tree/")).json()

        assert [n["id"] for n in tree] == [str(mine.id), str(root.id), str(child.id)]
        assert next(n for n in tree if n["id"] == str(child.id))["parent"] == str(root.id)


@pytest.mark.contract
class TestProjectPagePermissionsEndpoint:
    @pytest.mark.django_db
    def test_project_page_permissions(self, session_client, workspace, create_user, people):
        project = Project.objects.create(name="P", identifier="PPM", workspace=workspace)
        ProjectMember.objects.create(workspace=workspace, project=project, member=create_user, role=20)
        ProjectMember.objects.create(workspace=workspace, project=project, member=people["guest"], role=5)
        page = Page.objects.create(workspace=workspace, owned_by=create_user, name="Spec", access=Page.PUBLIC_ACCESS)
        ProjectPage.objects.create(workspace=workspace, project=project, page=page)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/pages/{page.id}/permissions/"

        owner = session_client.get(url)
        guest = people["guest_client"].get(url)
        outsider = people["other_client"].get(url)

        assert owner.json()["can_edit_content"] is True
        # a guest without guest_view_all_features may not see others' pages, live or not
        assert guest.status_code == 403 or guest.json()["can_view"] is False
        assert outsider.status_code == 403
