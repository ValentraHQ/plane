# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Search across library books: ranked metadata search and full-text search inside the books.

Visibility is decided once, by plane.utils.book_access.viewable_books; every query here starts
from that queryset, so a book the user cannot see contributes nothing (no result, snippet, count
or rank). The text of a book is searched when full-text search is on for the instance
(LIBRARY_FULLTEXT_SEARCH) and for the book (`search_content`).

Chapters carry `to_tsvector(<config>, text)`; the configuration follows the book's language
(English stemming for English books, ...), "simple" otherwise. A query is run once per
configuration among the candidate books, so the GIN index is used.
"""

# Python imports
import re
from functools import lru_cache

# Django imports
from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import connection
from django.db.models import Count, F, Q, TextField, Value, Window
from django.db.models.functions import Cast, Coalesce, RowNumber
from django.utils import timezone

# Module imports
from plane.db.models import Book, BookChapter

# ISO 639-1 codes -> PostgreSQL text search configurations that ship with PostgreSQL
LANGUAGE_CONFIGS = {
    "ar": "arabic",
    "ca": "catalan",
    "da": "danish",
    "de": "german",
    "el": "greek",
    "en": "english",
    "es": "spanish",
    "eu": "basque",
    "fi": "finnish",
    "fr": "french",
    "ga": "irish",
    "hi": "hindi",
    "hu": "hungarian",
    "hy": "armenian",
    "id": "indonesian",
    "it": "italian",
    "lt": "lithuanian",
    "nb": "norwegian",
    "ne": "nepali",
    "nl": "dutch",
    "nn": "norwegian",
    "no": "norwegian",
    "pt": "portuguese",
    "ro": "romanian",
    "ru": "russian",
    "sr": "serbian",
    "sv": "swedish",
    "ta": "tamil",
    "tr": "turkish",
    "yi": "yiddish",
}

MIN_QUERY = 2
MAX_QUERY = 200
PASSAGES_PER_BOOK = 3
SNIPPET = 90


@lru_cache(maxsize=1)
def _available_configs():
    with connection.cursor() as cursor:
        cursor.execute("SELECT cfgname FROM pg_ts_config")
        return frozenset(row[0] for row in cursor.fetchall())


def search_config_for(language):
    """The text search configuration for a book language such as 'en' or 'pt-BR'."""
    code = (language or "").strip().lower().replace("_", "-").split("-")[0]
    config = LANGUAGE_CONFIGS.get(code, "simple")
    return config if config in _available_configs() else "simple"


def index_book_text(book_id):
    """(Re)build the chapter vectors of one book. Returns the number of chapters indexed."""
    book = Book.objects.filter(pk=book_id).first()
    if book is None or book.status != Book.STATUS_READY:
        return 0
    config = search_config_for(book.language)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE book_chapters SET search_vector = to_tsvector(%s::regconfig, left(text, %s)) "
            "WHERE book_id = %s AND deleted_at IS NULL",
            [config, settings.BOOK_INDEX_CHAPTER_LIMIT, book.id],
        )
        count = cursor.rowcount
    Book.objects.filter(pk=book.id).update(search_config=config, text_indexed_at=timezone.now())
    return count


# --- queries ---


def clean_query(raw):
    return " ".join((raw or "").split())[:MAX_QUERY]


def query_terms(query):
    """Words and quoted phrases of a web-style query, without operators and excluded words."""
    phrases = re.findall(r'"([^"]+)"', query)
    rest = re.sub(r'"[^"]*"', " ", query)
    words = [
        w
        for w in re.findall(r"-?[\w'’]+", rest)
        if not w.startswith("-") and w.lower() not in ("or", "and", "not") and len(w) >= MIN_QUERY
    ]
    return [p.strip() for p in phrases if p.strip()] + words


def _metadata_vector():
    def text(field):
        # JSON lists (authors, tags, subjects) as text: the brackets and quotes are not words
        return Coalesce(Cast(field, output_field=TextField()), Value("", output_field=TextField()))

    return (
        SearchVector("title", weight="A", config="simple")
        + SearchVector(text("authors"), weight="A", config="simple")
        + SearchVector(text("tags"), text("subjects"), weight="B", config="simple")
        + SearchVector("publisher", "isbn", "description", weight="C", config="simple")
    )


def metadata_matches(books, query):
    """{book_id: score} for books whose details match: ranked full-text over title, authors, tags,
    subjects, publisher, ISBN and description, plus plain substring matches (partial words while
    typing, ISBN fragments). A title match counts most."""
    search = SearchQuery(query, config="simple", search_type="websearch")
    ranked = (
        books.annotate(meta_vector=_metadata_vector())
        .annotate(meta_rank=SearchRank(F("meta_vector"), search))
        .filter(
            Q(meta_vector=search)
            | Q(title__icontains=query)
            | Q(isbn__icontains=query)
            | Q(publisher__icontains=query)
            | Q(authors__icontains=query)
            | Q(tags__icontains=query)
        )
        .values_list("id", "meta_rank", "title")
    )
    lowered = query.lower()
    scores = {}
    for book_id, rank, title in ranked:
        bonus = 1.0 if lowered in (title or "").lower() else 0.0
        scores[book_id] = float(rank or 0) + bonus + 0.05
    return scores


def content_matches(books, query):
    """{book_id: {"rank", "count", "chapters"}} for books whose text matches: the best rank, how
    many chapters match, and the best PASSAGES_PER_BOOK chapters (rows with index, title, rank)."""
    if not settings.LIBRARY_FULLTEXT_SEARCH:
        return {}
    searchable = books.filter(search_content=True, status=Book.STATUS_READY, text_indexed_at__isnull=False)
    results = {}
    # order_by(): the model's default ordering would otherwise make the configs repeat
    for config in set(searchable.order_by().values_list("search_config", flat=True).distinct()):
        search = SearchQuery(query, config=config or "simple", search_type="websearch")
        matching = BookChapter.objects.filter(book__in=searchable.filter(search_config=config), search_vector=search)
        counts = dict(matching.order_by().values("book_id").annotate(n=Count("id")).values_list("book_id", "n"))
        # the best chapters of every book (not of all books together, or one big book crowds the rest out)
        best = (
            matching.annotate(rank=SearchRank(F("search_vector"), search, cover_density=True))
            .annotate(position=Window(RowNumber(), partition_by=[F("book_id")], order_by=F("rank").desc()))
            .filter(position__lte=PASSAGES_PER_BOOK)
            .order_by("book_id", "position")
            .values("book_id", "index", "title", "rank")
        )
        for row in best:
            entry = results.setdefault(
                row["book_id"], {"rank": 0.0, "count": counts.get(row["book_id"], 0), "chapters": []}
            )
            entry["chapters"].append(row)
            entry["rank"] = max(entry["rank"], float(row["rank"]))
    return results


def passage(text, query, terms):
    """Where the query is in a chapter's text: (match, occurrence, before, after), or None.

    The text is whitespace-collapsed like the reader's in-book search, and `occurrence` counts
    earlier case-insensitive occurrences of `match`, so the reader can find the same place."""
    flat = " ".join(text.split())
    best = None
    for term in [query, *terms]:
        if not term:
            continue
        if " " in term or len(term) < 5:
            pattern = re.compile(r"(?<!\w)" + re.escape(term), re.IGNORECASE)
        else:
            # stemming: "running" also finds "runs" / "runner"; look for the word's stem
            stem = term[: max(4, len(term) - 3)]
            pattern = re.compile(r"(?<!\w)" + re.escape(stem) + r"\w*", re.IGNORECASE)
        found = pattern.search(flat)
        if found and (best is None or found.start() < best.start()):
            best = found
        if best is not None and term is query:
            break  # the whole query, verbatim, wins
    if best is None:
        return None
    start, end = best.span()
    match = flat[start:end]
    occurrence = len(re.findall(re.escape(match), flat[:start], re.IGNORECASE))
    return {
        "match": match,
        "occurrence": occurrence,
        "before": flat[max(0, start - SNIPPET) : start],
        "after": flat[end : end + SNIPPET],
    }
