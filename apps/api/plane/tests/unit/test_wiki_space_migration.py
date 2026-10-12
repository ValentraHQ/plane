# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
The General-space data migration (0124) must move every existing wiki page into a
default space without changing anything else about the page.
"""

import pytest
from django.apps import apps
from django.utils import timezone

from plane.db.models import Page, PageVersion, Project, ProjectPage, WikiSpace, Workspace
from plane.db.wiki_space_migration import migrate_wiki_pages_to_default_space
from plane.tests.factories import UserFactory


def _wiki_page(workspace, owner, name, **extra):
    return Page.objects.create(workspace=workspace, owned_by=owner, name=name, is_global=True, **extra)


@pytest.fixture
def legacy_wiki(db, workspace, create_user):
    """A wiki as it looked before spaces existed (no page has a space)."""
    root = _wiki_page(workspace, create_user, "Handbook", description_html="<p>Root body</p>")
    child = _wiki_page(workspace, create_user, "Onboarding", parent=root)
    private = _wiki_page(workspace, create_user, "Draft", access=Page.PRIVATE_ACCESS)
    archived = _wiki_page(workspace, create_user, "Old", archived_at=timezone.now().date())
    deleted = _wiki_page(workspace, create_user, "Removed")
    deleted.delete()  # soft delete
    PageVersion.objects.create(workspace=workspace, page=root, owned_by=create_user, description_html="<p>v1</p>")
    project = Project.objects.create(name="P", identifier="MIG", workspace=workspace)
    project_page = Page.objects.create(workspace=workspace, owned_by=create_user, name="Project page")
    ProjectPage.objects.create(workspace=workspace, project=project, page=project_page)
    return {
        "root": root,
        "child": child,
        "private": private,
        "archived": archived,
        "deleted": deleted,
        "project_page": project_page,
    }


@pytest.mark.unit
class TestWikiSpaceMigration:
    @pytest.mark.django_db
    def test_all_wiki_pages_move_to_one_general_space(self, workspace, legacy_wiki):
        before = {
            p.id: (p.name, p.parent_id, p.access, p.owned_by_id, p.description_html, p.archived_at, p.updated_at)
            for p in Page._base_manager.filter(is_global=True)
        }

        migrate_wiki_pages_to_default_space(apps)

        spaces = WikiSpace.objects.filter(workspace=workspace)
        assert spaces.count() == 1
        general = spaces.get()
        assert (general.name, general.identifier, general.is_default, general.access) == (
            "General",
            "GENERAL",
            True,
            WikiSpace.ACCESS_OPEN,
        )
        assert general.created_by_id == workspace.owner_id
        # every wiki page, including archived and soft-deleted ones, is in the space and otherwise unchanged
        after = Page._base_manager.filter(is_global=True)
        assert after.count() == 5
        for page in after:
            assert page.space_id == general.id
            assert before[page.id] == (
                page.name,
                page.parent_id,
                page.access,
                page.owned_by_id,
                page.description_html,
                page.archived_at,
                page.updated_at,
            )

    @pytest.mark.django_db
    def test_versions_and_project_pages_are_untouched(self, legacy_wiki):
        migrate_wiki_pages_to_default_space(apps)

        assert PageVersion.objects.filter(page=legacy_wiki["root"], description_html="<p>v1</p>").exists()
        legacy_wiki["project_page"].refresh_from_db()
        assert legacy_wiki["project_page"].space_id is None

    @pytest.mark.django_db
    def test_running_twice_is_safe(self, workspace, legacy_wiki):
        migrate_wiki_pages_to_default_space(apps)
        migrate_wiki_pages_to_default_space(apps)

        assert WikiSpace.objects.filter(workspace=workspace).count() == 1

    @pytest.mark.django_db
    def test_identifier_clash_gets_a_suffix(self, workspace, create_user, legacy_wiki):
        WikiSpace.objects.create(workspace=workspace, name="Existing", identifier="GENERAL")

        migrate_wiki_pages_to_default_space(apps)

        general = WikiSpace.objects.get(workspace=workspace, is_default=True)
        assert general.identifier == "GENERAL2"
        assert not Page._base_manager.filter(is_global=True, space__isnull=True).exists()

    @pytest.mark.django_db
    def test_each_workspace_gets_its_own_space_and_empty_ones_none(self, workspace, create_user, legacy_wiki):
        other_owner = UserFactory(username="mig-owner", email="mig-owner@plane.so")
        other = Workspace.objects.create(name="Other", slug="mig-other", owner=other_owner)
        other_page = _wiki_page(other, other_owner, "Other wiki")
        empty = Workspace.objects.create(name="Empty", slug="mig-empty", owner=other_owner)

        migrate_wiki_pages_to_default_space(apps)

        other_page.refresh_from_db()
        assert other_page.space.workspace_id == other.id
        assert other_page.space.is_default
        assert not WikiSpace.objects.filter(workspace=empty).exists()
