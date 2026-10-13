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
