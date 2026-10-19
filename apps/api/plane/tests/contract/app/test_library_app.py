# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Library API: uploads, duplicates, permissions, downloads, chapters and the feature flag."""

# Python imports
import json
import uuid

# Third party imports
import pytest
from rest_framework import status
from rest_framework.test import APIClient

# Module imports
from plane.app.views.library import base as views
from plane.bgtasks import book_task
from plane.db.models import Book, BookChapter, BookResource, FileAsset, Workspace, WorkspaceMember
from plane.tests.factories import UserFactory
from plane.tests.library_helpers import FakeStorage
from plane.utils.book_access import book_permissions, viewable_books

HASH = "a" * 64


def url(slug, book_id=None, suffix=""):
    base = f"/api/workspaces/{slug}/library/books/"
    return f"{base}{book_id}/{suffix}" if book_id else base


def member(workspace, username, role):
    user = UserFactory(username=username, email=f"{username}@plane.so")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def book(workspace, owner, visibility=Book.VISIBILITY_PERSONAL, file_hash=None, **extra):
    return Book.objects.create(
        workspace=workspace,
        owner=owner,
        visibility=visibility,
        format="epub",
        original_filename="b.epub",
        file_hash=file_hash or uuid.uuid4().hex * 2,
        title=extra.pop("title", "A Book"),
        **extra,
    )


@pytest.fixture
def library(settings, monkeypatch):
    settings.LIBRARY_ENABLED = True
    store = {}
    fake = FakeStorage(store)
    monkeypatch.setattr(views, "S3Storage", lambda *args, **kwargs: fake)
    monkeypatch.setattr(book_task, "S3Storage", lambda *args, **kwargs: fake)
    calls = {"process": [], "purge": []}
    monkeypatch.setattr(views.process_book, "delay", lambda *args: calls["process"].append(args))
    monkeypatch.setattr(views.purge_book_files, "delay", lambda *args: calls["purge"].append(args))
    return {"storage": fake, "calls": calls}


@pytest.fixture
def people(db, workspace):
    return {
        "admin2": member(workspace, "lib-admin", 20),
        "member": member(workspace, "lib-member", 15),
        "other": member(workspace, "lib-other", 15),
        "guest": member(workspace, "lib-guest", 5),
    }


@pytest.mark.contract
@pytest.mark.django_db
class TestLibraryAccess:
    def test_disabled_library_is_404(self, settings, session_client, workspace):
        settings.LIBRARY_ENABLED = False
        assert session_client.get(url(workspace.slug)).status_code == status.HTTP_404_NOT_FOUND

    def test_guests_and_outsiders_are_refused(self, library, people, workspace):
        guest_client = people["guest"][1]
        outsider = UserFactory(username="outsider", email="outsider@plane.so")
        outsider_client = APIClient()
        outsider_client.force_authenticate(user=outsider)
        for client in (guest_client, outsider_client):
            assert client.get(url(workspace.slug)).status_code == status.HTTP_403_FORBIDDEN
            response = client.post(url(workspace.slug), {"name": "a.epub", "size": 10, "sha256": HASH}, format="json")
            assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_personal_books_are_private(self, library, people, workspace, session_client, create_user):
        owner, owner_client = people["member"]
        private = book(workspace, owner)
        for name in ("other", "admin2"):
            client = people[name][1]
            assert client.get(url(workspace.slug, private.id)).status_code == 404
            assert client.get(url(workspace.slug, private.id, "download/")).status_code == 404
            assert client.get(url(workspace.slug, private.id, "chapters/")).status_code == 404
            assert client.delete(url(workspace.slug, private.id)).status_code == 404
            assert private.id not in [b["id"] for b in client.get(url(workspace.slug)).json()["results"]]
        # the workspace owner (an admin) cannot see it either
        assert session_client.get(url(workspace.slug, private.id)).status_code == 404
        assert owner_client.get(url(workspace.slug, private.id)).status_code == 200

    def test_workspace_books_are_shared_with_members(self, library, people, workspace):
        owner, _ = people["member"]
        shared = book(workspace, owner, visibility=Book.VISIBILITY_WORKSPACE)
        other_client = people["other"][1]
        response = other_client.get(url(workspace.slug, shared.id))
        assert response.status_code == 200
        assert response.json()["permissions"] == {
            "can_view": True,
            "can_download": True,
            "can_edit": False,
            "can_manage": False,
        }
        assert other_client.patch(url(workspace.slug, shared.id), {"title": "x"}, format="json").status_code == 403
        assert other_client.delete(url(workspace.slug, shared.id)).status_code == 403
        admin_client = people["admin2"][1]
        assert admin_client.patch(url(workspace.slug, shared.id), {"title": "Fixed"}, format="json").status_code == 200
        # only the owner decides who can see the book
        assert admin_client.patch(url(workspace.slug, shared.id), {"visibility": 0}, format="json").status_code == 403

    def test_list_and_single_book_permissions_agree(self, library, people, workspace, create_user):
        users = [create_user] + [people[name][0] for name in ("admin2", "member", "other", "guest")]
        books = [
            book(workspace, owner, visibility=visibility)
            for owner in users[:4]
            for visibility in (Book.VISIBILITY_PERSONAL, Book.VISIBILITY_WORKSPACE)
        ]
        for user in users:
            listed = set(viewable_books(workspace.id, user).values_list("id", flat=True))
            for item in books:
                assert (item.id in listed) == book_permissions(item, user)["can_view"], (user.username, item.id)

    def test_other_workspace_is_out_of_reach(self, library, people, workspace):
        other_ws = Workspace.objects.create(name="Elsewhere", slug="elsewhere", owner=people["member"][0])
        WorkspaceMember.objects.create(workspace=other_ws, member=people["member"][0], role=20, is_active=True)
        foreign = book(other_ws, people["member"][0], visibility=Book.VISIBILITY_WORKSPACE)
        client = people["other"][1]
        assert client.get(url(workspace.slug, foreign.id)).status_code == 404
        assert client.get(url("elsewhere", foreign.id)).status_code == 403


@pytest.mark.contract
@pytest.mark.django_db
class TestLibraryUpload:
    def test_reserve_upload(self, library, people, workspace):
        user, client = people["member"]
        response = client.post(
            url(workspace.slug), {"name": "My Book.epub", "size": 1234, "sha256": HASH.upper()}, format="json"
        )
        assert response.status_code == 201, response.json()
        data = response.json()
        created = Book.objects.get(pk=data["book"]["id"])
        assert created.owner_id == user.id and created.status == Book.STATUS_UPLOADING
        assert created.file_hash == HASH and created.format == "epub" and created.title == "My Book"
        assert created.file.entity_type == FileAsset.EntityTypeContext.BOOK_FILE
        assert created.file.asset.name.startswith(f"{workspace.id}/library/{created.id}/original/")
        assert data["upload_data"]["fields"]["Content-Type"] == "application/epub+zip"

    @pytest.mark.parametrize(
        "payload, field",
        [
            ({"name": "book.docx", "size": 10, "sha256": HASH}, "name"),
            ({"name": "book.epub", "size": 200 * 1024 * 1024, "sha256": HASH}, "size"),
            ({"name": "book.epub", "size": 0, "sha256": HASH}, "size"),
            ({"name": "book.epub", "size": 10, "sha256": "nothex"}, "sha256"),
            ({"name": "book.pdf", "size": 10, "sha256": HASH, "visibility": 7}, "visibility"),
        ],
    )
    def test_validation(self, library, people, workspace, payload, field):
        response = people["member"][1].post(url(workspace.slug), payload, format="json")
        assert response.status_code == 400 and field in response.json()

    def test_size_limit_is_separate_from_ordinary_uploads(self, library, settings, people, workspace):
        settings.BOOK_FILE_SIZE_LIMIT = 50
        response = people["member"][1].post(
            url(workspace.slug), {"name": "b.epub", "size": 51, "sha256": HASH}, format="json"
        )
        assert response.status_code == 400
        assert settings.FILE_SIZE_LIMIT == 5242880

    def test_duplicates(self, library, people, workspace):
        user, client = people["member"]
        payload = {"name": "b.epub", "size": 10, "sha256": HASH}
        assert client.post(url(workspace.slug), payload, format="json").status_code == 201
        # once uploaded, the same file is a duplicate (an unfinished upload would be replaced instead)
        Book.objects.filter(owner=user).update(status=Book.STATUS_READY)
        duplicate = client.post(url(workspace.slug), payload, format="json")
        assert duplicate.status_code == 409 and duplicate.json()["book_id"]
        # someone else's personal library may hold the same file
        assert people["other"][1].post(url(workspace.slug), payload, format="json").status_code == 201
        # once in the workspace library
        shared = {**payload, "visibility": 1}
        assert client.post(url(workspace.slug), shared, format="json").status_code == 201
        Book.objects.filter(visibility=Book.VISIBILITY_WORKSPACE).update(status=Book.STATUS_READY)
        assert people["other"][1].post(url(workspace.slug), shared, format="json").status_code == 409

    def test_an_abandoned_upload_does_not_block_a_retry(
        self, library, people, workspace, django_capture_on_commit_callbacks
    ):
        user, client = people["member"]
        payload = {"name": "b.epub", "size": 10, "sha256": HASH, "visibility": 1}
        first = client.post(url(workspace.slug), payload, format="json").json()["book"]["id"]
        # someone else's unfinished upload still counts as the workspace copy
        assert people["other"][1].post(url(workspace.slug), payload, format="json").status_code == 409
        with django_capture_on_commit_callbacks(execute=True):
            retry = client.post(url(workspace.slug), payload, format="json")
        assert retry.status_code == 201 and retry.json()["book"]["id"] != first
        assert Book.all_objects.get(pk=first).deleted_at is not None
        assert library["calls"]["purge"] == [(first,)]
        # a finished book is still a real duplicate
        Book.objects.filter(pk=retry.json()["book"]["id"]).update(status=Book.STATUS_READY)
        assert client.post(url(workspace.slug), payload, format="json").status_code == 409

    def test_making_a_duplicate_shared_is_refused(self, library, people, workspace):
        user, client = people["member"]
        book(workspace, people["other"][0], visibility=Book.VISIBILITY_WORKSPACE, file_hash=HASH)
        mine = book(workspace, user, file_hash=HASH)
        response = client.patch(url(workspace.slug, mine.id), {"visibility": 1}, format="json")
        assert response.status_code == 409

    def test_upload_complete_checks_the_stored_file(
        self, library, people, workspace, django_capture_on_commit_callbacks
    ):
        user, client = people["member"]
        created = client.post(url(workspace.slug), {"name": "b.epub", "size": 5, "sha256": HASH}, format="json")
        book_id = created.json()["book"]["id"]
        key = Book.objects.get(pk=book_id).file.asset.name
        # nothing uploaded yet
        assert client.post(url(workspace.slug, book_id, "upload-complete/")).status_code == 400
        library["storage"].store[key] = {"data": b"123456", "type": "application/epub+zip"}
        assert client.post(url(workspace.slug, book_id, "upload-complete/")).status_code == 400  # wrong size
        library["storage"].store[key] = {"data": b"12345", "type": "application/epub+zip"}
        # only the uploader can complete it
        assert people["other"][1].post(url(workspace.slug, book_id, "upload-complete/")).status_code == 404
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(url(workspace.slug, book_id, "upload-complete/"))
        assert response.status_code == 200 and response.json()["status"] == Book.STATUS_PROCESSING
        stored = Book.objects.get(pk=book_id)
        assert stored.file.is_uploaded and stored.processing_token
        assert library["calls"]["process"] == [(book_id, str(stored.processing_token))]
        # completing twice does not start a second run
        with django_capture_on_commit_callbacks(execute=True):
            client.post(url(workspace.slug, book_id, "upload-complete/"))
        assert len(library["calls"]["process"]) == 1


@pytest.mark.contract
@pytest.mark.django_db
class TestLibraryManagement:
    def test_edit_metadata_marks_fields_as_edited(self, library, people, workspace):
        user, client = people["member"]
        mine = book(workspace, user)
        response = client.patch(
            url(workspace.slug, mine.id), {"title": " New ", "authors": ["A", " ", "B"]}, format="json"
        )
        assert response.status_code == 200
        mine.refresh_from_db()
        assert mine.title == "New" and mine.authors == ["A", "B"]
        assert set(mine.edited_fields) == {"title", "authors"}

    def test_stale_unfinished_uploads_are_not_listed(self, library, people, workspace):
        from datetime import timedelta

        from django.utils import timezone

        user, client = people["member"]
        fresh = book(workspace, user, status=Book.STATUS_UPLOADING)
        stale = book(workspace, user, status=Book.STATUS_UPLOADING)
        Book.objects.filter(pk=stale.id).update(created_at=timezone.now() - timedelta(hours=2))
        ids = [b["id"] for b in client.get(url(workspace.slug)).json()["results"]]
        assert str(fresh.id) in ids and str(stale.id) not in ids

    def test_archive_filter_and_search(self, library, people, workspace):
        user, client = people["member"]
        kept = book(workspace, user, title="Dune", authors=["Frank Herbert"])
        archived = book(workspace, user, title="Emma")
        client.patch(url(workspace.slug, archived.id), {"archived": True}, format="json")
        ids = lambda **q: [b["id"] for b in client.get(url(workspace.slug), q).json()["results"]]  # noqa: E731
        assert ids() == [str(kept.id)]
        assert ids(archived="true") == [str(archived.id)]
        assert ids(search="herbert") == [str(kept.id)]

    def test_delete(self, library, people, workspace, django_capture_on_commit_callbacks):
        user, client = people["member"]
        mine = book(workspace, user, processing_token=uuid.uuid4())
        with django_capture_on_commit_callbacks(execute=True):
            assert client.delete(url(workspace.slug, mine.id)).status_code == 204
        stored = Book.all_objects.get(pk=mine.id)
        assert stored.deleted_at is not None and stored.processing_token is None
        assert client.get(url(workspace.slug, mine.id)).status_code == 404
        assert library["calls"]["purge"] == [(str(mine.id),)]
        # the same file can be added again afterwards
        payload = {"name": "b.epub", "size": 10, "sha256": mine.file_hash}
        assert client.post(url(workspace.slug), payload, format="json").status_code == 201

    def test_reprocess(self, library, people, workspace, django_capture_on_commit_callbacks):
        user, client = people["member"]
        mine = book(workspace, user, status=Book.STATUS_FAILED, failure_reason="old")
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(url(workspace.slug, mine.id, "reprocess/"))
        assert response.status_code == 200 and response.json()["status"] == Book.STATUS_PROCESSING
        assert response.json()["failure_reason"] == ""
        assert len(library["calls"]["process"]) == 1
        assert people["other"][1].post(url(workspace.slug, mine.id, "reprocess/")).status_code == 404

    def test_download_is_a_short_lived_attachment_link(self, library, people, workspace):
        user, client = people["member"]
        mine = book(workspace, user, visibility=Book.VISIBILITY_WORKSPACE)
        mine.file = FileAsset.objects.create(
            asset="k/orig.epub", workspace=workspace, entity_type="BOOK_FILE", is_uploaded=True
        )
        mine.save()
        response = people["other"][1].get(url(workspace.slug, mine.id, "download/"))
        assert response.status_code == 200
        assert "disposition=attachment" in response.json()["url"] and "filename=b.epub" in response.json()["url"]


@pytest.mark.contract
@pytest.mark.django_db
class TestLibraryChapters:
    def test_chapter_resolves_resources_after_the_permission_check(self, library, people, workspace):
        user, client = people["member"]
        mine = book(workspace, user, status=Book.STATUS_READY)
        store = library["storage"].store
        store["p/ch0.json"] = {
            "data": json.dumps(
                {
                    "html": '<p><img src="plane-res:OEBPS/a%20b.png"><img src="plane-res:OEBPS/unknown.png"></p>',
                    "stylesheets": ["OEBPS/s.css"],
                    "css": "p{color:red}",
                }
            ).encode(),
            "type": "application/json",
        }
        store["p/s.css"] = {"data": b'div{background:url("plane-res:OEBPS/a%20b.png")}', "type": "text/css"}
        BookChapter.objects.create(
            workspace=workspace, book=mine, index=0, spine_id="c", href="x", content_key="p/ch0.json"
        )
        BookChapter.objects.create(workspace=workspace, book=mine, index=1, spine_id="d", href="y", content_key="p/x")
        BookResource.objects.create(
            workspace=workspace, book=mine, path="OEBPS/a b.png", storage_key="p/img.png", media_type="image/png"
        )
        BookResource.objects.create(
            workspace=workspace, book=mine, path="OEBPS/s.css", storage_key="p/s.css", media_type="text/css"
        )

        data = client.get(url(workspace.slug, mine.id, "chapters/0/")).json()
        assert 'src="https://signed.example/p/img.png' in data["html"]
        assert 'src="about:blank"' in data["html"]  # unknown resources never resolve
        assert "https://signed.example/p/img.png" in data["css"] and "color:red" in data["css"]
        assert (data["previous"], data["next"]) == (None, 1)
        assert client.get(url(workspace.slug, mine.id, "chapters/9/")).status_code == 404
        assert people["other"][1].get(url(workspace.slug, mine.id, "chapters/0/")).status_code == 404

    def test_chapter_of_unready_book(self, library, people, workspace):
        user, client = people["member"]
        mine = book(workspace, user, status=Book.STATUS_PROCESSING)
        assert client.get(url(workspace.slug, mine.id, "chapters/0/")).status_code == 409


def coll_url(slug, collection_id=None, suffix=""):
    base = f"/api/workspaces/{slug}/library/collections/"
    return f"{base}{collection_id}/{suffix}" if collection_id else base


@pytest.mark.contract
@pytest.mark.django_db
class TestLibraryTags:
    def test_tags_are_cleaned_and_filterable(self, library, people, workspace):
        user, client = people["member"]
        mine = book(workspace, user)
        response = client.patch(
            url(workspace.slug, mine.id), {"tags": [" Air  Law ", "air law", "Drones", ""]}, format="json"
        )
        assert response.status_code == 200 and response.json()["tags"] == ["Air Law", "Drones"]
        mine.refresh_from_db()
        assert "tags" not in mine.edited_fields  # tags are not extracted metadata
        ids = [b["id"] for b in client.get(url(workspace.slug), {"tag": "Drones"}).json()["results"]]
        assert ids == [str(mine.id)]
        assert [b["id"] for b in client.get(url(workspace.slug), {"search": "air law"}).json()["results"]] == [
            str(mine.id)
        ]

    def test_tag_list_never_reveals_private_books(self, library, people, workspace):
        member_user, member_client = people["member"]
        other_user, other_client = people["other"]
        book(workspace, member_user, tags=["Secret Merger"])
        book(workspace, member_user, visibility=Book.VISIBILITY_WORKSPACE, tags=["Ops", "secret merger"])
        book(workspace, other_user, tags=["ops"])
        assert member_client.get(f"/api/workspaces/{workspace.slug}/library/tags/").json() == [
            {"name": "Ops", "count": 1},
            {"name": "Secret Merger", "count": 2},
        ]
        assert other_client.get(f"/api/workspaces/{workspace.slug}/library/tags/").json() == [
            {"name": "Ops", "count": 2},
            {"name": "secret merger", "count": 1},
        ]

    def test_only_editors_can_tag(self, library, people, workspace):
        shared = book(workspace, people["member"][0], visibility=Book.VISIBILITY_WORKSPACE)
        assert (
            people["other"][1].patch(url(workspace.slug, shared.id), {"tags": ["x"]}, format="json").status_code == 403
        )


@pytest.mark.contract
@pytest.mark.django_db
class TestLibraryCollections:
    def test_personal_collection_is_private(self, library, people, workspace, session_client):
        user, client = people["member"]
        created = client.post(coll_url(workspace.slug), {"name": "  To read  "}, format="json")
        assert created.status_code == 201 and created.json()["name"] == "To read"
        cid = created.json()["id"]
        for other in (people["other"][1], people["admin2"][1], session_client):
            assert all(c["id"] != cid for c in other.get(coll_url(workspace.slug)).json())
            assert other.patch(coll_url(workspace.slug, cid), {"name": "x"}, format="json").status_code == 404
            assert other.get(url(workspace.slug), {"collection": cid}).status_code == 404

    def test_add_list_and_remove_books(self, library, people, workspace):
        user, client = people["member"]
        cid = client.post(coll_url(workspace.slug), {"name": "Shelf"}, format="json").json()["id"]
        a, b = book(workspace, user, title="A"), book(workspace, user, title="B")
        added = client.post(
            coll_url(workspace.slug, cid, "books/"), {"book_ids": [str(a.id), str(b.id)]}, format="json"
        )
        assert added.json() == {"added": 2}
        # adding again is harmless
        assert client.post(
            coll_url(workspace.slug, cid, "books/"), {"book_ids": [str(a.id)]}, format="json"
        ).json() == {"added": 0}
        listed = client.get(url(workspace.slug), {"collection": cid}).json()["results"]
        assert {x["id"] for x in listed} == {str(a.id), str(b.id)}
        assert client.get(coll_url(workspace.slug)).json()[0]["book_count"] == 2
        assert client.get(url(workspace.slug, a.id)).json()["collection_ids"] == [cid]
        assert client.delete(coll_url(workspace.slug, cid, f"books/{a.id}/")).status_code == 204
        assert client.get(coll_url(workspace.slug)).json()[0]["book_count"] == 1
        # deleting the collection keeps the books
        assert client.delete(coll_url(workspace.slug, cid)).status_code == 204
        assert client.get(url(workspace.slug, b.id)).status_code == 200

    def test_cannot_add_books_one_cannot_see(self, library, people, workspace):
        user, client = people["member"]
        cid = client.post(coll_url(workspace.slug), {"name": "Shelf"}, format="json").json()["id"]
        theirs = book(workspace, people["other"][0])
        response = client.post(coll_url(workspace.slug, cid, "books/"), {"book_ids": [str(theirs.id)]}, format="json")
        assert response.status_code == 404
        bad = client.post(coll_url(workspace.slug, cid, "books/"), {"book_ids": ["not-a-uuid"]}, format="json")
        assert bad.status_code == 400

    def test_shared_collection_rules(self, library, people, workspace):
        user, client = people["member"]
        other_client = people["other"][1]
        shared = client.post(coll_url(workspace.slug), {"name": "Team shelf", "visibility": 1}, format="json").json()
        mine_personal = book(workspace, user)
        mine_shared = book(workspace, user, visibility=Book.VISIBILITY_WORKSPACE)
        # personal books cannot go on a shared shelf
        refused = client.post(
            coll_url(workspace.slug, shared["id"], "books/"), {"book_ids": [str(mine_personal.id)]}, format="json"
        )
        assert refused.status_code == 400
        client.post(
            coll_url(workspace.slug, shared["id"], "books/"), {"book_ids": [str(mine_shared.id)]}, format="json"
        )
        # other members see it but cannot change it; admins can
        assert any(c["id"] == shared["id"] for c in other_client.get(coll_url(workspace.slug)).json())
        assert (
            other_client.patch(coll_url(workspace.slug, shared["id"]), {"name": "x"}, format="json").status_code == 403
        )
        assert (
            people["admin2"][1]
            .patch(coll_url(workspace.slug, shared["id"]), {"name": "Ops shelf"}, format="json")
            .status_code
            == 200
        )
        assert (
            people["admin2"][1]
            .patch(coll_url(workspace.slug, shared["id"]), {"visibility": 0}, format="json")
            .status_code
            == 403
        )
        # making the book personal takes it off the shared shelf
        client.patch(url(workspace.slug, mine_shared.id), {"visibility": 0}, format="json")
        assert other_client.get(url(workspace.slug), {"collection": shared["id"]}).json()["results"] == []
        assert client.get(url(workspace.slug), {"collection": shared["id"]}).json()["results"] == []

    def test_sharing_a_collection_with_personal_books_is_refused(self, library, people, workspace):
        user, client = people["member"]
        cid = client.post(coll_url(workspace.slug), {"name": "Mine"}, format="json").json()["id"]
        client.post(
            coll_url(workspace.slug, cid, "books/"), {"book_ids": [str(book(workspace, user).id)]}, format="json"
        )
        response = client.patch(coll_url(workspace.slug, cid), {"visibility": 1}, format="json")
        assert response.status_code == 400 and "personal book" in response.json()["error"]
        assert client.patch(coll_url(workspace.slug, cid), {"visibility": 7}, format="json").status_code == 400

    def test_guests_have_no_collections(self, library, people, workspace):
        assert people["guest"][1].get(coll_url(workspace.slug)).status_code == 403
        assert people["guest"][1].get(f"/api/workspaces/{workspace.slug}/library/tags/").status_code == 403


@pytest.mark.contract
@pytest.mark.django_db
def test_instance_config_exposes_the_library_flag(settings, api_client):
    settings.LIBRARY_ENABLED = True
    from django.utils import timezone

    from plane.license.models import Instance

    Instance.objects.create(
        instance_name="Test", instance_id="test-instance", current_version="test", last_checked_at=timezone.now()
    )
    config = api_client.get("/api/instances/").json()["config"]
    assert config["is_library_enabled"] is True and config["book_file_size_limit"] == settings.BOOK_FILE_SIZE_LIMIT


def chapter(workspace, owner_book, index, text, title=""):
    return BookChapter.objects.create(
        workspace=workspace,
        book=owner_book,
        index=index,
        spine_id=f"c{index}",
        href=f"c{index}.xhtml",
        content_key=f"k{index}",
        text=text,
        title=title,
        character_count=len(text),
    )


@pytest.mark.contract
@pytest.mark.django_db
class TestLibraryReading:
    def test_position_progress_and_status(self, library, people, workspace):
        user, client = people["member"]
        shared = book(workspace, user, visibility=Book.VISIBILITY_WORKSPACE, status=Book.STATUS_READY, chapter_count=3)
        state_url = url(workspace.slug, shared.id, "reading-state/")
        assert client.get(state_url).json()["status"] == 0
        saved = client.put(
            state_url, {"position": {"chapter": 1, "offset": 120, "quote": "It was"}, "progress": 42.5}, format="json"
        ).json()
        assert saved["status"] == 1 and saved["progress"] == 42.5 and saved["position"]["chapter"] == 1
        assert saved["last_opened_at"]
        done = client.put(state_url, {"status": 2, "progress": 100}, format="json").json()
        assert done["status"] == 2 and done["completed_at"]
        reset = client.put(state_url, {"status": 0}, format="json").json()
        assert reset == {**reset, "status": 0, "progress": 0, "position": {}, "completed_at": None}
        # a chapter that does not exist is refused
        assert client.put(state_url, {"position": {"chapter": 9, "offset": 0}}, format="json").status_code == 400
        assert client.put(state_url, {"progress": 140}, format="json").status_code == 400

    def test_reading_state_is_private(self, library, people, workspace):
        user, client = people["member"]
        other_client = people["other"][1]
        shared = book(workspace, user, visibility=Book.VISIBILITY_WORKSPACE, status=Book.STATUS_READY, chapter_count=2)
        client.put(
            url(workspace.slug, shared.id, "reading-state/"),
            {"position": {"chapter": 1, "offset": 5}, "progress": 70},
            format="json",
        )
        # another member reading the same book starts from scratch and never sees the first one's progress
        assert other_client.get(url(workspace.slug, shared.id, "reading-state/")).json()["progress"] == 0
        listed = other_client.get(url(workspace.slug)).json()["results"]
        assert next(b for b in listed if b["id"] == str(shared.id))["my_reading"]["progress"] == 0
        mine = client.get(url(workspace.slug)).json()["results"]
        assert next(b for b in mine if b["id"] == str(shared.id))["my_reading"]["progress"] == 70
        assert client.get(url(workspace.slug, shared.id)).json()["my_reading"]["status"] == 1
        # nobody can read or write state for a book they cannot see
        private = book(workspace, user, status=Book.STATUS_READY, chapter_count=1)
        assert other_client.get(url(workspace.slug, private.id, "reading-state/")).status_code == 404
        assert (
            other_client.put(
                url(workspace.slug, private.id, "reading-state/"), {"progress": 1}, format="json"
            ).status_code
            == 404
        )

    def test_continue_reading_and_reading_filter(self, library, people, workspace):
        user, client = people["member"]
        reading = book(workspace, user, status=Book.STATUS_READY, chapter_count=2, title="Reading")
        finished = book(workspace, user, status=Book.STATUS_READY, chapter_count=2, title="Finished")
        archived = book(workspace, user, status=Book.STATUS_READY, chapter_count=2, title="Archived")
        untouched = book(workspace, user, status=Book.STATUS_READY, chapter_count=2, title="Untouched")
        for item in (reading, archived):
            client.put(
                url(workspace.slug, item.id, "reading-state/"),
                {"position": {"chapter": 0, "offset": 1}, "progress": 10},
                format="json",
            )
        client.put(url(workspace.slug, finished.id, "reading-state/"), {"status": 2}, format="json")
        client.patch(url(workspace.slug, archived.id), {"archived": True}, format="json")
        ids = [b["id"] for b in client.get(f"/api/workspaces/{workspace.slug}/library/continue-reading/").json()]
        assert ids == [str(reading.id)]

        def filtered(value):
            return {b["id"] for b in client.get(url(workspace.slug), {"reading": value}).json()["results"]}

        assert filtered("reading") == {str(reading.id)}
        assert filtered("completed") == {str(finished.id)}
        assert filtered("unread") == {str(untouched.id)}
        # another member has their own (empty) list
        assert people["other"][1].get(f"/api/workspaces/{workspace.slug}/library/continue-reading/").json() == []

    def test_reader_preferences(self, library, people, workspace):
        user, client = people["member"]
        prefs_url = f"/api/workspaces/{workspace.slug}/library/reader-preferences/"
        defaults = client.get(prefs_url).json()
        assert defaults["theme"] == "light" and defaults["layout"] == "paginated"
        saved = client.put(prefs_url, {"theme": "sepia", "font_size": 22}, format="json").json()
        assert saved["theme"] == "sepia" and saved["font_size"] == 22 and saved["layout"] == "paginated"
        assert client.put(prefs_url, {"font_size": 99}, format="json").status_code == 400
        assert client.put(prefs_url, {"theme": "neon"}, format="json").status_code == 400
        # preferences belong to the person
        assert people["other"][1].get(prefs_url).json()["theme"] == "light"

    def test_search_inside_a_book(self, library, people, workspace):
        user, client = people["member"]
        item = book(workspace, user, status=Book.STATUS_READY, chapter_count=2)
        chapter(workspace, item, 0, "Alice was beginning to get very tired.\\nSo she was considering ALICE.", "One")
        chapter(workspace, item, 1, "Down the rabbit-hole went Alice.", "Two")
        search_url = url(workspace.slug, item.id, "search/")
        found = client.get(search_url, {"q": "alice"}).json()
        assert [(r["chapter"], r["occurrence"]) for r in found["results"]] == [(0, 0), (0, 1), (1, 0)]
        first = found["results"][0]
        assert (
            first["match"] == "Alice"
            and first["after"].startswith(" was beginning")
            and first["chapter_title"] == "One"
        )
        assert client.get(search_url, {"q": "a"}).json()["results"] == []
        assert client.get(search_url, {"q": "dragons"}).json()["results"] == []
        assert people["other"][1].get(search_url, {"q": "alice"}).status_code == 404


def ann_url(slug, book_id=None, annotation_id=None, suffix=""):
    if annotation_id:
        return f"/api/workspaces/{slug}/library/annotations/{annotation_id}/{suffix}"
    if book_id:
        return f"/api/workspaces/{slug}/library/books/{book_id}/annotations/"
    return f"/api/workspaces/{slug}/library/annotations/{suffix}"


def readable(workspace, owner, **extra):
    item = book(workspace, owner, status=Book.STATUS_READY, chapter_count=3, **extra)
    for index in range(3):
        chapter(workspace, item, index, f"Text of chapter {index}.", title=f"Chapter {index + 1}")
    return item


HIGHLIGHT = {
    "chapter": 1,
    "start_offset": 5,
    "end_offset": 30,
    "quote": "the passage",
    "prefix": "before ",
    "suffix": " after",
}


@pytest.mark.contract
@pytest.mark.django_db
class TestLibraryAnnotations:
    def test_create_kinds_and_validation(self, library, people, workspace):
        user, client = people["member"]
        item = readable(workspace, user)
        created = client.post(ann_url(workspace.slug, item.id), {**HIGHLIGHT, "color": "green"}, format="json")
        assert created.status_code == 201, created.json()
        data = created.json()
        assert (data["kind"], data["color"], data["chapter_title"], data["visibility"]) == (
            "highlight",
            "green",
            "Chapter 2",
            0,
        )
        assert data["permissions"] == {"can_edit": True, "can_delete": True}
        note = client.post(
            ann_url(workspace.slug, item.id), {**HIGHLIGHT, "kind": "note", "note": "Remember this"}, format="json"
        )
        assert note.status_code == 201 and note.json()["color"] == ""
        mark = client.post(
            ann_url(workspace.slug, item.id),
            {"kind": "bookmark", "chapter": 2, "start_offset": 7, "end_offset": 7},
            format="json",
        )
        assert mark.status_code == 201
        bad = [
            ({**HIGHLIGHT, "end_offset": 1}, "end_offset"),
            ({**HIGHLIGHT, "end_offset": 30000}, "end_offset"),
            ({**HIGHLIGHT, "end_offset": 5}, "end_offset"),
            ({**HIGHLIGHT, "kind": "note", "note": "  "}, "note"),
            ({**HIGHLIGHT, "color": "neon"}, "color"),
            ({**HIGHLIGHT, "quote": "x" * 5000}, "quote"),
        ]
        for payload, field in bad:
            response = client.post(ann_url(workspace.slug, item.id), payload, format="json")
            assert response.status_code == 400 and field in response.json(), (payload, response.json())
        assert (
            client.post(ann_url(workspace.slug, item.id), {**HIGHLIGHT, "chapter": 3}, format="json").status_code == 400
        )
        unready = book(workspace, user, status=Book.STATUS_PROCESSING, chapter_count=3)
        assert client.post(ann_url(workspace.slug, unready.id), HIGHLIGHT, format="json").status_code == 409

    def test_private_by_default_and_explicit_sharing(self, library, people, workspace):
        user, client = people["member"]
        other_client = people["other"][1]
        shared_book = readable(workspace, user, visibility=Book.VISIBILITY_WORKSPACE)
        private = client.post(ann_url(workspace.slug, shared_book.id), HIGHLIGHT, format="json").json()
        assert other_client.get(ann_url(workspace.slug, shared_book.id)).json() == []
        assert (
            other_client.patch(
                ann_url(workspace.slug, annotation_id=private["id"]), {"color": "pink"}, format="json"
            ).status_code
            == 404
        )
        shared = client.patch(ann_url(workspace.slug, annotation_id=private["id"]), {"visibility": 1}, format="json")
        assert shared.status_code == 200
        seen = other_client.get(ann_url(workspace.slug, shared_book.id)).json()
        assert [a["id"] for a in seen] == [private["id"]] and seen[0]["permissions"] == {
            "can_edit": False,
            "can_delete": False,
        }
        assert seen[0]["user_detail"]["display_name"] == user.display_name
        assert (
            other_client.patch(
                ann_url(workspace.slug, annotation_id=private["id"]), {"note": "x"}, format="json"
            ).status_code
            == 403
        )
        assert other_client.delete(ann_url(workspace.slug, annotation_id=private["id"])).status_code == 403
        # others' shared annotations are not "mine"
        assert other_client.get(ann_url(workspace.slug)).json()["count"] == 0
        assert other_client.get(ann_url(workspace.slug, shared_book.id), {"mine": "true"}).json() == []

    def test_sharing_needs_a_workspace_book(self, library, people, workspace):
        user, client = people["member"]
        personal = readable(workspace, user)
        assert (
            client.post(ann_url(workspace.slug, personal.id), {**HIGHLIGHT, "visibility": 1}, format="json").status_code
            == 400
        )
        created = client.post(ann_url(workspace.slug, personal.id), HIGHLIGHT, format="json").json()
        assert (
            client.patch(
                ann_url(workspace.slug, annotation_id=created["id"]), {"visibility": 1}, format="json"
            ).status_code
            == 400
        )

    def test_shared_annotations_disappear_when_the_book_becomes_personal(self, library, people, workspace):
        owner, owner_client = people["member"]
        other_user, other_client = people["other"]
        item = readable(workspace, owner, visibility=Book.VISIBILITY_WORKSPACE)
        theirs = other_client.post(
            ann_url(workspace.slug, item.id), {**HIGHLIGHT, "visibility": 1}, format="json"
        ).json()
        assert [a["id"] for a in owner_client.get(ann_url(workspace.slug, item.id)).json()] == [theirs["id"]]
        owner_client.patch(url(workspace.slug, item.id), {"visibility": 0}, format="json")
        # the owner no longer sees someone else's annotations on a book that is now private to them ...
        assert owner_client.get(ann_url(workspace.slug, item.id)).json() == []
        # ... and the other member can no longer reach the book or the annotation
        assert other_client.get(ann_url(workspace.slug, item.id)).status_code == 404
        assert other_client.get(ann_url(workspace.slug)).json()["count"] == 0
        # sharing the book again brings the annotation back, still shared
        owner_client.patch(url(workspace.slug, item.id), {"visibility": 1}, format="json")
        assert [a["id"] for a in owner_client.get(ann_url(workspace.slug, item.id)).json()] == [theirs["id"]]
        assert other_client.get(ann_url(workspace.slug)).json()["count"] == 1

    def test_admins_can_remove_shared_annotations_only(self, library, people, workspace):
        user, client = people["member"]
        admin_client = people["admin2"][1]
        item = readable(workspace, user, visibility=Book.VISIBILITY_WORKSPACE)
        shared = client.post(ann_url(workspace.slug, item.id), {**HIGHLIGHT, "visibility": 1}, format="json").json()
        private = client.post(ann_url(workspace.slug, item.id), HIGHLIGHT, format="json").json()
        assert admin_client.get(ann_url(workspace.slug, item.id)).json()[0]["permissions"] == {
            "can_edit": False,
            "can_delete": True,
        }
        assert (
            admin_client.patch(
                ann_url(workspace.slug, annotation_id=shared["id"]), {"note": "x"}, format="json"
            ).status_code
            == 403
        )
        assert admin_client.delete(ann_url(workspace.slug, annotation_id=private["id"])).status_code == 404
        assert admin_client.delete(ann_url(workspace.slug, annotation_id=shared["id"])).status_code == 204
        assert client.delete(ann_url(workspace.slug, annotation_id=private["id"])).status_code == 204

    def test_my_annotations_across_books(self, library, people, workspace):
        user, client = people["member"]
        first, second = readable(workspace, user, title="Alpha"), readable(workspace, user, title="Beta")
        client.post(ann_url(workspace.slug, first.id), {**HIGHLIGHT, "quote": "orbital mechanics"}, format="json")
        client.post(
            ann_url(workspace.slug, second.id),
            {**HIGHLIGHT, "kind": "note", "note": "check the delta-v"},
            format="json",
        )
        client.post(
            ann_url(workspace.slug, second.id),
            {"kind": "bookmark", "chapter": 0, "start_offset": 0, "end_offset": 0},
            format="json",
        )
        mine = client.get(ann_url(workspace.slug)).json()
        assert mine["count"] == 3 and mine["counts"] == {"highlight": 1, "note": 1, "bookmark": 1}
        assert {a["book_title"] for a in mine["results"]} == {"Alpha", "Beta"}
        assert client.get(ann_url(workspace.slug), {"search": "delta"}).json()["count"] == 1
        assert client.get(ann_url(workspace.slug), {"book": str(first.id)}).json()["count"] == 1
        assert client.get(ann_url(workspace.slug), {"kind": "bookmark"}).json()["count"] == 1

    def test_markdown_export(self, library, people, workspace):
        user, client = people["member"]
        other_client = people["other"][1]
        item = readable(workspace, user, visibility=Book.VISIBILITY_WORKSPACE, title="Orbits", authors=["Ada Author"])
        client.post(
            ann_url(workspace.slug, item.id),
            {**HIGHLIGHT, "quote": "Line one\nLine two", "note": "My thought"},
            format="json",
        )
        other_client.post(
            ann_url(workspace.slug, item.id), {**HIGHLIGHT, "quote": "someone else", "visibility": 1}, format="json"
        )
        response = client.get(ann_url(workspace.slug, suffix="export/"), {"book": str(item.id)})
        assert response.status_code == 200 and response["Content-Type"].startswith("text/markdown")
        assert "Orbits - notes.md" in response["Content-Disposition"]
        text = response.content.decode()
        assert text.startswith("# Orbits\n") and "*Ada Author*" in text and "## Chapter 2" in text
        assert "> Line one\n> Line two" in text and "My thought" in text
        assert "someone else" not in text  # only the user's own annotations

    def test_guests_have_no_annotations(self, library, people, workspace):
        guest_client = people["guest"][1]
        assert guest_client.get(ann_url(workspace.slug)).status_code == 403
        assert guest_client.get(ann_url(workspace.slug, suffix="export/")).status_code == 403
