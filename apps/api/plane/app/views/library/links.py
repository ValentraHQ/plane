# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Books and the rest of the workspace: wiki pages created from passages and notes, and links
between a book and a page, project or work item. Visibility rules live in plane.utils.book_access
(a link needs both ends visible); pages are created through the wiki's own create_wiki_page, so
space roles, parent restrictions and page access apply exactly as in the wiki.
"""

# Python imports
import re
from html import escape
from urllib.parse import urlencode

# Django imports
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q

# Third party imports
from rest_framework import serializers, status
from rest_framework.response import Response

# Module imports
from plane.app.serializers.library import BookSerializer
from plane.app.views.page.workspace import create_wiki_page
from plane.db.models import Book, BookChapter, BookLink, Page, ProjectMember, ProjectPage
from plane.utils.book_access import (
    MEMBER,
    book_permissions,
    link_permissions,
    viewable_books,
    viewable_issues,
    viewable_pages,
    viewable_projects,
    visible_links,
)
from plane.utils.host import base_host

from .annotations import MAX_NOTE
from .base import LibraryBaseEndpoint, _forbidden, _is_uuid, _not_found

MAX_PASSAGES = 100
SEARCH_LIMIT = 20
ISSUE_KEY = re.compile(r"^\s*([A-Za-z0-9]{1,12})-(\d{1,9})\s*$")


def _bad_request(message, code=None, **extra):
    body = {"error": message, **extra}
    if code:
        body["code"] = code
    return Response(body, status=status.HTTP_400_BAD_REQUEST)


# --- serializing ---


def serialize_target(link):
    if link.target_type == BookLink.TARGET_PAGE:
        page = link.page
        project_id = (
            None
            if page.space_id
            else ProjectPage.objects.filter(page=page).values_list("project_id", flat=True).first()
        )
        return {
            "id": str(page.id),
            "name": page.name or "Untitled",
            "space_id": str(page.space_id) if page.space_id else None,
            "project_id": str(project_id) if project_id else None,
        }
    if link.target_type == BookLink.TARGET_PROJECT:
        project = link.project
        return {"id": str(project.id), "name": project.name, "identifier": project.identifier}
    issue = link.issue
    return {
        "id": str(issue.id),
        "name": issue.name,
        "project_id": str(issue.project_id),
        "project_identifier": issue.project.identifier,
        "sequence_id": issue.sequence_id,
    }


def serialize_link(link, user, book_perms, book_data=None):
    data = {
        "id": str(link.id),
        "book": str(link.book_id),
        "target_type": link.target_type,
        "target": serialize_target(link),
        "origin": link.origin,
        "chapter": link.chapter,
        "start_offset": link.start_offset,
        "created_by": str(link.created_by_id) if link.created_by_id else None,
        "created_at": link.created_at,
        "permissions": link_permissions(link, user, book_perms),
    }
    if book_data is not None:
        data["book_detail"] = book_data
    return data


def _links(queryset):
    return queryset.select_related("page", "project", "issue", "issue__project")


# --- targets ---


def find_target(workspace, user, target_type, target_id):
    """The target if the user may link a book to it: visible to them, and for projects and work
    items a member role in the project. Returns (target, error response)."""
    if not _is_uuid(target_id):
        return None, _bad_request("A target is required.")
    if target_type == BookLink.TARGET_PAGE:
        target = viewable_pages(workspace.slug, user).filter(pk=target_id).first()
    elif target_type == BookLink.TARGET_PROJECT:
        target = viewable_projects(workspace.id, user, min_role=MEMBER).filter(pk=target_id).first()
    elif target_type == BookLink.TARGET_ISSUE:
        target = viewable_issues(workspace.id, user).filter(pk=target_id).select_related("project").first()
        if (
            target is not None
            and not ProjectMember.objects.filter(
                project_id=target.project_id, member=user, is_active=True, role__gte=MEMBER
            ).exists()
        ):
            return None, _forbidden("You need to be a member of the project to link a book to its work items.")
    else:
        return None, _bad_request("Links go to a page, a project or a work item.")
    if target is None:
        return None, Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return target, None


class BookLinkListEndpoint(LibraryBaseEndpoint):
    """The links of one book (GET), and linking it to a page, project or work item (POST)."""

    def get(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, perms = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        links = _links(visible_links(self.workspace, request.user, Book.objects.filter(pk=book.id), role=role))
        return Response([serialize_link(link, request.user, perms) for link in links])

    def post(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, perms = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        target_type = request.data.get("target_type")
        target, error = find_target(self.workspace, request.user, target_type, request.data.get("target_id"))
        if error:
            return error
        existing = BookLink.objects.filter(book=book, **{target_type: target}).first()
        if existing:
            return Response(serialize_link(existing, request.user, perms), status=status.HTTP_200_OK)
        try:
            with transaction.atomic():
                link = BookLink.objects.create(
                    workspace=self.workspace, book=book, target_type=target_type, **{target_type: target}
                )
        except IntegrityError:
            # a concurrent request linked the same pair
            link = BookLink.objects.get(book=book, **{target_type: target})
        return Response(serialize_link(link, request.user, perms), status=status.HTTP_201_CREATED)


class BookLinkDetailEndpoint(LibraryBaseEndpoint):
    def delete(self, request, slug, link_id):
        role, error = self.access(request)
        if error:
            return error
        books = viewable_books(self.workspace.id, request.user, role=role)
        link = visible_links(self.workspace, request.user, books, role=role).filter(pk=link_id).first()
        if link is None:
            return _not_found()
        perms = book_permissions(link.book, request.user, role=role)
        if not link_permissions(link, request.user, perms)["can_delete"]:
            return _forbidden("Only the person who added this link or an editor of the book can remove it.")
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LinkedBooksEndpoint(LibraryBaseEndpoint):
    """Books linked to one page, project or work item (?target_type=&target_id=), as far as the
    user can see both."""

    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        target_type = request.query_params.get("target_type")
        target_id = request.query_params.get("target_id")
        if target_type not in dict(BookLink.TARGET_CHOICES) or not _is_uuid(target_id):
            return _bad_request("target_type and target_id are required.")
        books = viewable_books(self.workspace.id, request.user, role=role)
        links = _links(
            visible_links(self.workspace, request.user, books, role=role)
            .filter(**{f"{target_type}_id": target_id})
            .select_related("book", "book__owner")
        )
        context = self.context(request, role)
        result = []
        for link in links:
            perms = book_permissions(link.book, request.user, role=role)
            result.append(
                serialize_link(link, request.user, perms, book_data=BookSerializer(link.book, context=context).data)
            )
        return Response(result)


class LinkTargetSearchEndpoint(LibraryBaseEndpoint):
    """Pages, projects or work items the user could link a book to (?target_type=&search=)."""

    def get(self, request, slug):
        role, error = self.access(request)
        if error:
            return error
        target_type = request.query_params.get("target_type")
        query = request.query_params.get("search", "").strip()[:200]
        user, workspace = request.user, self.workspace
        if target_type == BookLink.TARGET_PAGE:
            pages = viewable_pages(workspace.slug, user).filter(archived_at__isnull=True)
            if query:
                pages = pages.filter(name__icontains=query)
            pages = list(pages.order_by("-updated_at")[:SEARCH_LIMIT])
            projects = dict(
                ProjectPage.objects.filter(page__in=[p.id for p in pages if not p.space_id]).values_list(
                    "page_id", "project_id"
                )
            )
            results = [
                {
                    "id": str(p.id),
                    "name": p.name or "Untitled",
                    "space_id": str(p.space_id) if p.space_id else None,
                    "project_id": str(projects[p.id]) if p.id in projects else None,
                }
                for p in pages
            ]
        elif target_type == BookLink.TARGET_PROJECT:
            projects = viewable_projects(workspace.id, user, min_role=MEMBER)
            if query:
                projects = projects.filter(Q(name__icontains=query) | Q(identifier__iexact=query))
            results = [
                {"id": str(p.id), "name": p.name, "identifier": p.identifier}
                for p in projects.order_by("name")[:SEARCH_LIMIT]
            ]
        elif target_type == BookLink.TARGET_ISSUE:
            member_projects = viewable_projects(workspace.id, user, min_role=MEMBER)
            issues = viewable_issues(workspace.id, user).filter(project__in=member_projects)
            key = ISSUE_KEY.match(query)
            if key:
                issues = issues.filter(project__identifier__iexact=key.group(1), sequence_id=int(key.group(2)))
            elif query:
                issues = issues.filter(name__icontains=query)
            results = [
                {
                    "id": str(i.id),
                    "name": i.name,
                    "project_id": str(i.project_id),
                    "project_identifier": i.project.identifier,
                    "sequence_id": i.sequence_id,
                }
                for i in issues.select_related("project").order_by("-updated_at")[:SEARCH_LIMIT]
            ]
        else:
            return _bad_request("target_type must be page, project or issue.")
        return Response(results)


# --- wiki pages from passages and notes ---


class PassageSerializer(serializers.Serializer):
    chapter = serializers.IntegerField(min_value=0)
    start_offset = serializers.IntegerField(min_value=0, default=0)
    quote = serializers.CharField(allow_blank=True, required=False, default="", max_length=20000)
    note = serializers.CharField(allow_blank=True, required=False, default="", max_length=MAX_NOTE)

    def validate(self, data):
        if not data["quote"].strip() and not data["note"].strip():
            raise serializers.ValidationError("Each passage needs a quote or a note.")
        return data


class WikiPageFromBookSerializer(serializers.Serializer):
    space = serializers.UUIDField()
    parent = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    intro = serializers.CharField(allow_blank=True, required=False, default="", max_length=MAX_NOTE)
    passages = PassageSerializer(many=True, allow_empty=False, max_length=MAX_PASSAGES)
    # shared with the space (a public page) rather than private to the author
    share = serializers.BooleanField(default=False)
    # the author confirms they may share these excerpts; required when sharing
    confirm_excerpts = serializers.BooleanField(default=False)


def _squash(text):
    """Text without whitespace, to compare a quote with the chapter however its lines were broken."""
    return re.sub(r"\s+", "", text)


def _paragraphs(text):
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    return "".join(f"<p>{'<br>'.join(escape(line) for line in block.splitlines())}</p>" for block in blocks)


def reader_url(base, slug, book, chapter=None, offset=None):
    url = f"{base.rstrip('/')}/{slug}/library/books/{book.id}"
    if chapter is None:
        return url
    return f"{url}/read?{urlencode({'chapter': chapter, 'offset': offset or 0})}"


def wiki_page_html(book, passages, intro, titles, base, slug):
    """The page body: the intro, then per chapter its quotes (blockquotes) and notes, each with a
    link back to the passage, and a source line. Everything is escaped."""
    parts = [_paragraphs(intro)] if intro.strip() else []
    current = None
    for passage in passages:
        if passage["chapter"] != current:
            current = passage["chapter"]
            parts.append(f"<h3>{escape(titles.get(current) or f'Section {current + 1}')}</h3>")
        if passage["quote"].strip():
            parts.append(f"<blockquote>{_paragraphs(passage['quote'])}</blockquote>")
        if passage["note"].strip():
            parts.append(_paragraphs(passage["note"]))
        link = escape(reader_url(base, slug, book, passage["chapter"], passage["start_offset"]))
        parts.append(f'<p><a href="{link}">Open this passage in the book</a></p>')
    title = escape(book.title or book.original_filename)
    source = f'<strong>Source:</strong> <a href="{escape(reader_url(base, slug, book))}">{title}</a>'
    if book.authors:
        source += f" by {escape(', '.join(book.authors))}"
    if book.publisher:
        source += f", {escape(book.publisher)}"
    if book.published_date:
        source += f" ({escape(str(book.published_date)[:4])})"
    parts += ["<hr>", f"<p>{source}.</p>"]
    return "".join(parts)


class BookWikiPageEndpoint(LibraryBaseEndpoint):
    """
    Create a wiki page from passages and notes of a book. The page is private to its author
    unless `share` is set, which also needs `confirm_excerpts`. Every quote must come from the
    book (it is checked against the chapter text) and is limited to BOOK_EXCERPT_LIMIT
    characters, BOOK_EXCERPT_PAGE_LIMIT for the page as a whole.
    """

    def post(self, request, slug, book_id):
        role, error = self.access(request)
        if error:
            return error
        book, perms = self.get_book(request, book_id, role)
        if book is None:
            return _not_found()
        if book.format != Book.FORMAT_EPUB or book.status != Book.STATUS_READY:
            return Response({"error": "This book cannot be quoted yet."}, status=status.HTTP_409_CONFLICT)
        serializer = WikiPageFromBookSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        passages = sorted(data["passages"], key=lambda p: (p["chapter"], p["start_offset"]))
        for passage in passages:
            passage["quote"] = passage["quote"].strip()

        # excerpt limits
        limit, page_limit = settings.BOOK_EXCERPT_LIMIT, settings.BOOK_EXCERPT_PAGE_LIMIT
        for index, passage in enumerate(passages):
            if len(passage["quote"]) > limit:
                return _bad_request(
                    f"Excerpts are limited to {limit} characters.", code="excerpt_too_long", passage=index, limit=limit
                )
        total = sum(len(p["quote"]) for p in passages)
        if total > page_limit:
            return _bad_request(
                f"A page can quote at most {page_limit} characters of a book.",
                code="excerpts_too_long",
                limit=page_limit,
            )

        # every quote must be a passage of the book
        chapters = {
            c["index"]: c
            for c in BookChapter.objects.filter(book=book, index__in={p["chapter"] for p in passages}).values(
                "index", "title", "text"
            )
        }
        for index, passage in enumerate(passages):
            chapter = chapters.get(passage["chapter"])
            if chapter is None:
                return _bad_request("That chapter does not exist.", code="unknown_chapter", passage=index)
            if passage["quote"] and _squash(passage["quote"]) not in _squash(chapter["text"]):
                return _bad_request("A quote was not found in the book.", code="quote_not_found", passage=index)

        if data["share"] and not data["confirm_excerpts"]:
            return _bad_request(
                "Confirm that these excerpts may be shared with everyone in the space.",
                code="confirmation_required",
            )

        titles = {index: c["title"] for index, c in chapters.items()}
        base = base_host(request=request, is_app=True)
        name = data["title"].strip() or f"Notes on {book.title or book.original_filename}"
        page_data = {
            "name": name[:255],
            "space": str(data["space"]),
            "parent": str(data["parent"]) if data.get("parent") else None,
            "access": Page.PUBLIC_ACCESS if data["share"] else Page.PRIVATE_ACCESS,
            "description_html": wiki_page_html(book, passages, data["intro"], titles, base, slug),
        }
        # the wiki's own creation path: space role, parent restrictions and page access apply
        page, error = create_wiki_page(slug, request.user, page_data)
        if error:
            return error
        first = passages[0]
        link = BookLink.objects.create(
            workspace=self.workspace,
            book=book,
            target_type=BookLink.TARGET_PAGE,
            page=page,
            origin=BookLink.ORIGIN_CREATED,
            chapter=first["chapter"],
            start_offset=first["start_offset"],
        )
        return Response(
            {
                "page": {"id": str(page.id), "name": page.name, "space": str(page.space_id), "access": page.access},
                "link": serialize_link(link, request.user, perms),
            },
            status=status.HTTP_201_CREATED,
        )
