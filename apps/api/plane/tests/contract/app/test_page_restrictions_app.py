# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Page restrictions and the central page resolver (plane.utils.page_access):
inherited view/edit restrictions and private ancestors on wiki and project pages,
enforced on pages, descriptions, versions, permissions, search, favourites and
recent visits; the restrictions API; and the search title leak.
"""

import itertools

import pytest
from rest_framework.test import APIClient

from plane.db.models import (
    Page,
    PageRestriction,
    PageVersion,
    Project,
    ProjectMember,
    ProjectPage,
    UserFavorite,
    UserRecentVisit,
    WikiSpace,
    WikiSpaceMember,
    WorkspaceMember,
)
from plane.tests.factories import UserFactory
from plane.utils.page_access import page_permissions, viewable_project_pages
from plane.utils.wiki_permissions import viewable_wiki_pages

ADMIN, MEMBER, GUEST = 20, 15, 5
VIEW, EDIT = PageRestriction.VIEW, PageRestriction.EDIT


def _user(workspace, username, role=MEMBER):
    user = UserFactory(username=username, email=f"{username}@plane.so")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _restrict(page, kind, *members):
    for member in members:
        PageRestriction.objects.create(workspace=page.workspace, page=page, kind=kind, member=member)


@pytest.fixture
def wiki(db, workspace, create_user):
    """
    Open space ENG with:
        Handbook (owner: alice)              VIEW restricted to bob
          └─ Salaries (owner: carol)         public, inherits the restriction
        Runbook (owner: alice)               EDIT restricted to bob
          └─ Steps (owner: alice)            inherits the edit restriction
        Secret (owner: alice, private)
          └─ Leak (owner: carol, public)     hidden by the private parent
    alice, bob, carol, dave are workspace members (editors of the open space);
    the session user is a workspace admin.
    """
    alice, alice_c = _user(workspace, "alice")
    bob, bob_c = _user(workspace, "bob")
    carol, carol_c = _user(workspace, "carol")
    dave, dave_c = _user(workspace, "dave")
    space = WikiSpace.objects.create(workspace=workspace, name="Eng", identifier="ENG")

    def page(name, owner, parent=None, access=Page.PUBLIC_ACCESS):
        return Page.objects.create(
            workspace=workspace, space=space, is_global=True, name=name, owned_by=owner, parent=parent, access=access
        )

    handbook = page("Handbook", alice)
    salaries = page("Salaries", carol, parent=handbook)
    runbook = page("Runbook", alice)
    steps = page("Steps", alice, parent=runbook)
    secret = page("Secret", alice, access=Page.PRIVATE_ACCESS)
    leak = page("Leak", carol, parent=secret)
    _restrict(handbook, VIEW, bob)
    _restrict(runbook, EDIT, bob)
    PageVersion.objects.create(workspace=workspace, page=salaries, owned_by=carol, description_html="<p>v1</p>")
    return {
        "space": space,
        "users": {"admin": create_user, "alice": alice, "bob": bob, "carol": carol, "dave": dave},
        "clients": {"alice": alice_c, "bob": bob_c, "carol": carol_c, "dave": dave_c},
        "pages": {
            "handbook": handbook,
            "salaries": salaries,
            "runbook": runbook,
            "steps": steps,
            "secret": secret,
            "leak": leak,
        },
    }


def _w(workspace, path):
    return f"/api/workspaces/{workspace.slug}/wiki/{path}"


@pytest.mark.contract
class TestWikiInheritedRestrictions:
    @pytest.mark.django_db
    def test_view_restriction_hides_the_whole_subtree(self, workspace, session_client, wiki):
        pages, clients = wiki["pages"], wiki["clients"]
        salaries = pages["salaries"]
        dave = clients["dave"]
        # dave is an editor of the open space but not on the Handbook's view list
        for path in ["", "description/", "versions/", "permissions/", "restrictions/"]:
            assert dave.get(_w(workspace, f"pages/{salaries.id}/{path}")).status_code == 404, path
        tree = dave.get(_w(workspace, f"spaces/{wiki['space'].id}/pages-tree/")).json()
        assert {n["name"] for n in tree} == {"Runbook", "Steps"}
        listed = dave.get(_w(workspace, f"pages/?space_id={wiki['space'].id}")).json()
        assert "Handbook" not in {p["name"] for p in listed}
        # listed member, owner of the restricted page, and admins pass; carol (owner of the
        # child but not on the parent's list) does not, a child cannot bypass its parent
        assert clients["bob"].get(_w(workspace, f"pages/{salaries.id}/")).status_code == 200
        assert clients["alice"].get(_w(workspace, f"pages/{salaries.id}/")).status_code == 200
        assert session_client.get(_w(workspace, f"pages/{salaries.id}/")).status_code == 200
        assert clients["carol"].get(_w(workspace, f"pages/{salaries.id}/")).status_code == 404

    @pytest.mark.django_db
    def test_private_parent_hides_public_children(self, workspace, session_client, wiki):
        leak = wiki["pages"]["leak"]
        # not even a workspace admin sees beneath someone else's private page
        assert session_client.get(_w(workspace, f"pages/{leak.id}/")).status_code == 404
        assert wiki["clients"]["carol"].get(_w(workspace, f"pages/{leak.id}/")).status_code == 404
        assert wiki["clients"]["alice"].get(_w(workspace, f"pages/{leak.id}/")).status_code == 200

    @pytest.mark.django_db
    def test_edit_restriction_is_inherited_and_read_only(self, workspace, wiki):
        steps = wiki["pages"]["steps"]
        dave, bob = wiki["clients"]["dave"], wiki["clients"]["bob"]
        perms = dave.get(_w(workspace, f"pages/{steps.id}/permissions/")).json()
        assert perms == {"can_view": True, "can_edit": False, "can_manage": False, "can_edit_content": False}
        assert dave.patch(_w(workspace, f"pages/{steps.id}/"), {"name": "x"}, format="json").status_code == 403
        assert (
            dave.patch(
                _w(workspace, f"pages/{steps.id}/description/"), {"description_html": "<p>x</p>"}, format="json"
            ).status_code
            == 403
        )
        # cannot add pages under it, nor move pages into it
        assert (
            dave.post(_w(workspace, "pages/"), {"name": "Sub", "parent": str(steps.id)}, format="json").status_code
            == 403
        )
        mine = dave.post(_w(workspace, "pages/"), {"name": "Mine", "space": str(wiki["space"].id)}, format="json")
        assert mine.status_code == 201
        moved = dave.post(_w(workspace, f"pages/{mine.json()['id']}/move/"), {"parent": str(steps.id)}, format="json")
        assert moved.status_code == 403
        # bob is on the edit list
        assert bob.get(_w(workspace, f"pages/{steps.id}/permissions/")).json()["can_edit"] is True
        assert bob.patch(_w(workspace, f"pages/{steps.id}/"), {"name": "Steps v2"}, format="json").status_code == 200

    @pytest.mark.django_db
    def test_detail_carries_effective_permissions(self, workspace, wiki):
        data = wiki["clients"]["dave"].get(_w(workspace, f"pages/{wiki['pages']['steps'].id}/")).json()
        assert data["permissions"]["can_view"] is True
        assert data["permissions"]["can_edit"] is False

    @pytest.mark.django_db
    def test_tree_flags_own_restrictions(self, workspace, wiki):
        tree = wiki["clients"]["bob"].get(_w(workspace, f"spaces/{wiki['space'].id}/pages-tree/")).json()
        flags = {n["name"]: (n["view_restricted"], n["edit_restricted"]) for n in tree}
        assert flags["Handbook"] == (True, False)
        assert flags["Salaries"] == (False, False)
        assert flags["Runbook"] == (False, True)


@pytest.mark.contract
class TestRestrictionsApi:
    @pytest.mark.django_db
    def test_read_shows_own_and_inherited(self, workspace, wiki):
        data = wiki["clients"]["bob"].get(_w(workspace, f"pages/{wiki['pages']['salaries'].id}/restrictions/")).json()
        assert data["view"] == [] and data["edit"] == []
        assert data["inherited"] == [
            {"page": str(wiki["pages"]["handbook"].id), "name": "Handbook", "view": True, "edit": False}
        ]
        assert data["can_manage"] is False

    @pytest.mark.django_db
    def test_owner_replaces_lists_and_removal_is_audited(self, workspace, wiki):
        runbook = wiki["pages"]["runbook"]
        users, alice = wiki["users"], wiki["clients"]["alice"]
        url = _w(workspace, f"pages/{runbook.id}/restrictions/")
        response = alice.put(url, {"view": [str(users["bob"].id), str(users["carol"].id)], "edit": []}, format="json")
        assert response.status_code == 200
        assert sorted(response.json()["view"]) == sorted([str(users["bob"].id), str(users["carol"].id)])
        assert response.json()["edit"] == []
        # dave is now out, the edit restriction is gone
        assert wiki["clients"]["dave"].get(_w(workspace, f"pages/{runbook.id}/")).status_code == 404
        assert wiki["clients"]["carol"].get(_w(workspace, f"pages/{runbook.id}/permissions/")).json()["can_edit"]
        removed = PageRestriction.all_objects.filter(page=runbook, kind=EDIT, member=users["bob"]).get()
        assert removed.deleted_at is not None

    @pytest.mark.django_db
    def test_only_managers_and_valid_members(self, workspace, create_user, wiki):
        steps = wiki["pages"]["steps"]
        url = _w(workspace, f"pages/{steps.id}/restrictions/")
        payload = {"view": [str(wiki["users"]["bob"].id)]}
        # bob may edit (he is on the inherited edit list) but does not own the page
        assert wiki["clients"]["bob"].put(url, payload, format="json").status_code == 403
        # a restricted user cannot even see the page
        assert (
            wiki["clients"]["dave"]
            .put(_w(workspace, f"pages/{wiki['pages']['handbook'].id}/restrictions/"), payload, format="json")
            .status_code
            == 404
        )
        outsider = UserFactory(username="outsider", email="outsider@plane.so")
        guest, _ = _user(workspace, "guesty", GUEST)
        alice = wiki["clients"]["alice"]
        for bad in ([str(outsider.id)], [str(guest.id)], ["not-a-uuid"]):
            assert alice.put(url, {"view": bad}, format="json").status_code == 400
        assert alice.put(url, {"view": "x"}, format="json").status_code == 400
        assert alice.put(url, {}, format="json").status_code == 400

    @pytest.mark.django_db
    def test_restricted_space_members_only(self, workspace, wiki):
        users = wiki["users"]
        space = WikiSpace.objects.create(
            workspace=workspace, name="HR", identifier="HR", access=WikiSpace.ACCESS_RESTRICTED
        )
        WikiSpaceMember.objects.create(workspace=workspace, space=space, member=users["alice"], role=ADMIN)
        page = Page.objects.create(workspace=workspace, space=space, is_global=True, name="P", owned_by=users["alice"])
        url = _w(workspace, f"pages/{page.id}/restrictions/")
        alice = wiki["clients"]["alice"]
        # dave has no role in the restricted space, so he cannot be listed
        assert alice.put(url, {"view": [str(users["dave"].id)]}, format="json").status_code == 400
        assert alice.put(url, {"view": [str(users["alice"].id)]}, format="json").status_code == 200


@pytest.fixture
def project_setup(db, workspace, create_user):
    """Project PR with admin (session user), member bob, member carol, guest gil (no guest_view_all)."""
    project = Project.objects.create(name="PR", identifier="PR", workspace=workspace)
    bob, bob_c = _user(workspace, "pbob")
    carol, carol_c = _user(workspace, "pcarol")
    gil, gil_c = _user(workspace, "pgil", GUEST)
    for user, role in [(create_user, ADMIN), (bob, MEMBER), (carol, MEMBER), (gil, GUEST)]:
        ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=role)

    def page(name, owner, parent=None, access=Page.PUBLIC_ACCESS):
        p = Page.objects.create(workspace=workspace, name=name, owned_by=owner, parent=parent, access=access)
        ProjectPage.objects.create(workspace=workspace, project=project, page=p)
        return p

    roadmap = page("Roadmap secret plans", bob)
    child = page("Roadmap child", bob, parent=roadmap)
    _restrict(roadmap, VIEW, bob)
    private = page("Private draft plans", bob, access=Page.PRIVATE_ACCESS)
    under_private = page("Under private plans", carol, parent=private)
    public = page("Public plans", bob)
    PageVersion.objects.create(workspace=workspace, page=public, owned_by=bob, description_html="<p>v1</p>")
    return {
        "project": project,
        "users": {"admin": create_user, "bob": bob, "carol": carol, "gil": gil},
        "clients": {"bob": bob_c, "carol": carol_c, "gil": gil_c},
        "pages": {
            "roadmap": roadmap,
            "child": child,
            "private": private,
            "under_private": under_private,
            "public": public,
        },
    }


def _p(workspace, project, path):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/{path}"


@pytest.mark.contract
class TestProjectPages:
    @pytest.mark.django_db
    def test_restrictions_and_private_parents_apply(self, workspace, session_client, project_setup):
        project, pages, carol = project_setup["project"], project_setup["pages"], project_setup["clients"]["carol"]
        for name in ["roadmap", "child", "private", "under_private"]:
            for path in ["", "description/", "versions/", "permissions/"]:
                status_code = carol.get(_p(workspace, project, f"pages/{pages[name].id}/{path}")).status_code
                # upstream's ProjectPagePermission already answers 403 for others' private pages
                assert status_code in ((403, 404) if name == "private" else (404,)), (name, path)
        assert carol.get(_p(workspace, project, f"pages/{pages['public'].id}/")).status_code == 200
        # project admin passes the view restriction, but not someone else's private page
        assert session_client.get(_p(workspace, project, f"pages/{pages['child'].id}/")).status_code == 200
        assert session_client.get(_p(workspace, project, f"pages/{pages['under_private'].id}/")).status_code == 404
        listed = {p["name"] for p in carol.get(_p(workspace, project, "pages/")).json()}
        assert listed == {"Public plans"}
        summary = carol.get(_p(workspace, project, "pages-summary/")).json()
        assert summary["public_pages"] == 1

    @pytest.mark.django_db
    def test_guest_cannot_read_others_content(self, workspace, project_setup):
        project, public, gil = (
            project_setup["project"],
            project_setup["pages"]["public"],
            project_setup["clients"]["gil"],
        )
        # previously the description and versions endpoints skipped the guest rule
        for path in ["", "description/", "versions/", "permissions/"]:
            assert gil.get(_p(workspace, project, f"pages/{public.id}/{path}")).status_code == 404, path
        project.guest_view_all_features = True
        project.save()
        assert gil.get(_p(workspace, project, f"pages/{public.id}/description/")).status_code == 200

    @pytest.mark.django_db
    def test_edit_restriction_blocks_writes(self, workspace, project_setup):
        project, public = project_setup["project"], project_setup["pages"]["public"]
        _restrict(public, EDIT, project_setup["users"]["bob"])
        carol = project_setup["clients"]["carol"]
        assert (
            carol.patch(_p(workspace, project, f"pages/{public.id}/"), {"name": "x"}, format="json").status_code == 403
        )
        assert (
            carol.patch(
                _p(workspace, project, f"pages/{public.id}/description/"),
                {"description_html": "<p>x</p>"},
                format="json",
            ).status_code
            == 403
        )
        assert carol.post(_p(workspace, project, f"pages/{public.id}/lock/")).status_code == 403
        assert carol.get(_p(workspace, project, f"pages/{public.id}/permissions/")).json()["can_edit_content"] is False

    @pytest.mark.django_db
    def test_duplicate_keeps_restrictions(self, workspace, project_setup):
        project, roadmap = project_setup["project"], project_setup["pages"]["roadmap"]
        bob = project_setup["clients"]["bob"]
        copy = bob.post(_p(workspace, project, f"pages/{roadmap.id}/duplicate/"))
        assert copy.status_code == 201
        copy_id = copy.json()["id"]
        assert set(PageRestriction.objects.filter(page_id=copy_id).values_list("kind", "member_id")) == {
            (VIEW, project_setup["users"]["bob"].id)
        }
        assert project_setup["clients"]["carol"].get(_p(workspace, project, f"pages/{copy_id}/")).status_code == 404

    @pytest.mark.django_db
    def test_project_restrictions_endpoint(self, workspace, project_setup):
        project, public = project_setup["project"], project_setup["pages"]["public"]
        url = _p(workspace, project, f"pages/{public.id}/restrictions/")
        users = project_setup["users"]
        assert project_setup["clients"]["carol"].put(url, {"view": []}, format="json").status_code == 403
        response = project_setup["clients"]["bob"].put(url, {"view": [str(users["bob"].id)]}, format="json")
        assert response.status_code == 200
        assert project_setup["clients"]["carol"].get(_p(workspace, project, f"pages/{public.id}/")).status_code == 404


@pytest.mark.contract
class TestSearchAndListsDoNotLeak:
    @pytest.mark.django_db
    def test_global_search(self, workspace, project_setup):
        carol = project_setup["clients"]["carol"]
        response = carol.get(f"/api/workspaces/{workspace.slug}/search/?search=plans&entities=page")
        names = {p["name"] for p in response.json()["results"]["page"]}
        # before: "Private draft plans" (bob's private page) and the restricted ones leaked
        assert names == {"Public plans"}
        gil = project_setup["clients"]["gil"]
        guest_names = {
            p["name"]
            for p in gil.get(f"/api/workspaces/{workspace.slug}/search/?search=plans&entities=page").json()["results"][
                "page"
            ]
        }
        assert guest_names == set()

    @pytest.mark.django_db
    def test_mention_search(self, workspace, project_setup):
        project = project_setup["project"]
        carol = project_setup["clients"]["carol"]
        url = f"/api/workspaces/{workspace.slug}/entity-search/?query_type=page&query=Roadmap&project_id={project.id}"
        assert carol.get(url).json()["page"] == []
        bob_names = {p["name"] for p in project_setup["clients"]["bob"].get(url).json()["page"]}
        assert bob_names == {"Roadmap secret plans", "Roadmap child"}

    @pytest.mark.django_db
    def test_favourites_and_recent_visits(self, workspace, project_setup):
        project, roadmap, public = (
            project_setup["project"],
            project_setup["pages"]["roadmap"],
            project_setup["pages"]["public"],
        )
        carol_user, carol = project_setup["users"]["carol"], project_setup["clients"]["carol"]
        # carol could see these before the restriction was added
        for page in (roadmap, public):
            UserFavorite.objects.create(
                workspace=workspace, project=project, user=carol_user, entity_type="page", entity_identifier=page.id
            )
            UserRecentVisit.objects.create(
                workspace=workspace, project=project, user=carol_user, entity_name="page", entity_identifier=page.id
            )
        favourites = carol.get(f"/api/workspaces/{workspace.slug}/user-favorites/").json()
        assert {f["entity_identifier"] for f in favourites if f["entity_type"] == "page"} == {str(public.id)}
        visits = carol.get(f"/api/workspaces/{workspace.slug}/recent-visits/").json()
        assert {v["entity_identifier"] for v in visits if v["entity_name"] == "page"} == {str(public.id)}
        # and she cannot favourite a page she cannot see
        assert carol.post(_p(workspace, project, f"favorite-pages/{roadmap.id}/")).status_code == 404


@pytest.mark.contract
class TestQueryAndPageResolverAgree:
    """The SQL used for lists and search must match the per-page resolver for every user and page."""

    @pytest.mark.django_db
    def test_wiki(self, workspace, wiki):
        for user, page in itertools.product(wiki["users"].values(), wiki["pages"].values()):
            in_list = viewable_wiki_pages(workspace.slug, user).filter(pk=page.pk).exists()
            assert in_list == page_permissions(page, user)["can_view"], (user.username, page.name)

    @pytest.mark.django_db
    def test_project(self, workspace, project_setup):
        project = project_setup["project"]
        for user, page in itertools.product(project_setup["users"].values(), project_setup["pages"].values()):
            in_list = viewable_project_pages(workspace.slug, user, project.id).filter(pk=page.pk).exists()
            assert in_list == page_permissions(page, user, project_id=project.id)["can_view"], (
                user.username,
                page.name,
            )
