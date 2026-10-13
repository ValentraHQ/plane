# Library (eBooks)

> **Fork-specific (ValentraHQ).** Upstream Plane Community Edition has no library. The library is
> **off by default** (`LIBRARY_ENABLED=0`). Read [Before enabling in production](#before-enabling-in-production)
> first.

Workspace members can upload EPUB and PDF books to a personal library or to the workspace library.
EPUBs are processed in the background into sanitized chapters for the in-browser reader. PDFs are
stored with their metadata and can be downloaded; reading PDFs in the browser comes in a later PR.

This document covers the foundation (PR 1 of the library series): data model, storage, processing,
security and the API. The library UI, the reader, annotations, wiki integration and search follow in
later PRs.

## Who can do what

All decisions are made by one resolver, `plane/utils/book_access.py`.

| | Personal book | Workspace book |
| --- | --- | --- |
| View, read, download | owner only | every workspace admin and member |
| Edit metadata, archive, delete, reprocess | owner | owner and workspace admins |
| Change visibility (personal ↔ workspace) | owner | owner |

- **Admins cannot see personal books.**
- **Guests and non-members** get 403 on every library endpoint.
- **Hidden books return 404**, so their existence is not revealed.
- **Consistency:** lists use one query (`viewable_books`) and single books use `book_permissions`. A test checks that both agree for every user and book.
- **Sharing later:** sharing with specific people or groups can be added as a new `visibility` value backed by its own table, adding one condition to each resolver function. No existing table changes.

## Uploading

1. `POST /api/workspaces/<slug>/library/books/` with `{name, size, sha256, visibility}`. The API checks:
   - the type (by extension: `.epub`, `.pdf`)
   - the size (`BOOK_FILE_SIZE_LIMIT`)
   - duplicates (the same SHA-256 already in the same library → `409` with the existing book's id)

   It then creates the book (status *uploading*) and returns a **signed upload form** for storage. The
   form's policy fixes the exact content type and caps the size at the reserved size, so storage refuses
   anything larger.
2. The browser sends the file **straight to storage**; it never passes through the API.
3. `POST …/books/<id>/upload-complete/`: the API checks that the stored object exists and has the reserved
   size, then queues processing (status *processing*).
4. The worker verifies the file's SHA-256 against the announced one, processes the book, and sets status
   *ready* or *failed* with a readable `failure_reason`.

Duplicates are blocked twice: by the check in step 1, and by partial unique constraints, which catch
concurrent uploads. The same file can be in several people's personal libraries, but only once per
personal library and once in the workspace library.

## Processing (`plane/bgtasks/book_task.py`)

**EPUB:**
- **Archive checks**, before and while unpacking (`utils/library/archive.py`):
  - entry count, per-entry size, total unpacked size and compression ratio, against the bytes actually produced, not the headers
  - unsafe names (path traversal, absolute paths, drive letters, backslashes), symlinks, duplicate entries, ZIP encryption
- **Structure:**
  - the `mimetype` and `META-INF/container.xml` files and the package document
  - DRM: `encryption.xml` may only use font obfuscation
- **XML:** parsed with entity expansion, DTD loading and network access all off. Any document that declares entities is rejected.
- **Metadata:** title, authors (roles honoured), publisher, language, ISBN (checksum-validated), date, description (HTML stripped), subjects, identifiers.
- **Table of contents:** from the EPUB 3 nav document or the EPUB 2 NCX, mapped to chapters and fragments.
- **Chapters** (`utils/library/sanitize.py`):
  - **Links:** internal links become `plane-chapter:<index>#<fragment>`, `http(s)` and `mailto` links get `rel="noopener noreferrer nofollow"`, and anything else is dropped.
  - **Images** must be resources declared by the book whose bytes really are that type; remote images are never loaded.
  - **Allow-list:** the HTML is then cleaned by nh3. No scripts, event handlers, forms, frames, objects, SVG or MathML survive. Inline styles are filtered to an allow-list of properties with plain values.
  - **CSS:** stylesheets lose `@import`, `@font-face`, scriptable properties and every `url()` that is not one of the book's own images.
- **Covers:** re-encoded by Pillow as JPEG, both full size and a thumbnail. Re-encoding strips everything but the pixels.

**PDF:** `%PDF-` header check and metadata (title, authors, subject, page count) via pypdf. Encrypted PDFs are accepted; their metadata is read only when that needs no password.

**Failures and retries:**
- **Tokens:** each attempt has a token (`Book.processing_token`). A task whose token is no longer current does nothing, so duplicate deliveries and stale retries are harmless.
- **Separate output:** an attempt writes only under its own storage prefix, `…/processed/<token>/`. The original file is never modified.
- **Atomic switch:** chapters, resources and metadata are switched in **one transaction**, with the book row locked. The previous output is deleted only after that commits.
- **Failure:** a failed attempt deletes everything it wrote. Invalid books fail at once; storage and network errors are retried with backoff (`BOOK_PROCESSING_MAX_RETRIES`).
- **Time limit:** soft 15 minutes per attempt.
- **Reprocessing:** keeps metadata the user edited (`edited_fields`).

**Deleting** a book soft-deletes it, makes any running attempt stale, and purges every stored file of the book in the background.

## Storage layout

```
<workspace>/library/<book>/original/<random>.epub|pdf      the upload, unchanged
<workspace>/library/<book>/processed/<token>/chapters/00000.json   {"html", "stylesheets", "css"}
<workspace>/library/<book>/processed/<token>/res/<hash>.png|jpg|gif|webp|css
<workspace>/library/<book>/processed/<token>/cover.jpg, cover-thumb.jpg
```

The bucket is private. Files are only ever served through signed links:
- links expire after `BOOK_SIGNED_URL_EXPIRATION`, 10 minutes by default
- they are created after a permission check
- downloads are forced to `attachment`

The stored chapters contain `plane-res:` placeholders, which the chapter endpoint resolves into signed links for each request.

## API

All endpoints are under `/api/workspaces/<slug>/library/`. They return 404 when the library is disabled.

| Method | Path | |
| --- | --- | --- |
| GET | `books/` | List: `search` (title, author, ISBN, publisher), `visibility`, `status`, `format`, `archived=true`, `order_by` (`created_at`, `title`, `updated_at`, `-…`), `limit` ≤ 100, `offset`. Returns `{count, limit, offset, results}`. |
| POST | `books/` | Reserve an upload; returns `{book, upload_data}`. |
| GET / PATCH / DELETE | `books/<id>/` | Detail (with `toc`); PATCH takes the metadata fields, `visibility` and `archived`. |
| POST | `books/<id>/upload-complete/` | Start processing after the upload. |
| POST | `books/<id>/reprocess/` | Process again (owner / admin). |
| GET | `books/<id>/download/` | `{url, expires_in}`: a signed link to the original file. |
| GET | `books/<id>/chapters/` | `[{id, index, title, href, linear, character_count}]` |
| GET | `books/<id>/chapters/<index>/` | `{index, title, html, css, previous, next, expires_in}` for the reader. |

Book objects include:
- `permissions`: `{can_view, can_download, can_edit, can_manage}`
- signed `cover_url` and `cover_thumbnail_url`
- `status` (0 uploading, 1 processing, 2 ready, 3 failed) and `failure_reason`

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `LIBRARY_ENABLED` | `0` | Turns the library on (API and worker). |
| `BOOK_FILE_SIZE_LIMIT` | `104857600` (100 MB) | Per book file. Enforced when reserving, by the storage policy, by the worker, and at the proxy for the storage route. Set it on the API, the worker **and** the proxy. |
| `FILE_SIZE_LIMIT` | `5242880` (5 MB) | Unchanged for every other upload and for every other proxy route. |
| `BOOK_MAX_ARCHIVE_ENTRIES` | `10000` | Files inside one EPUB. |
| `BOOK_MAX_UNPACKED_SIZE` | `536870912` (512 MB) | Total bytes one EPUB may unpack to. |
| `BOOK_MAX_ENTRY_SIZE` | `67108864` (64 MB) | Largest single file inside an EPUB. |
| `BOOK_MAX_COMPRESSION_RATIO` | `100` | For entries over 1 MB. |
| `BOOK_MAX_CHAPTERS` | `5000` | |
| `BOOK_PROCESSING_MAX_RETRIES` | `3` | Retries for storage or network errors. |
| `BOOK_SIGNED_URL_EXPIRATION` | `600` | Seconds. |
| `BOOK_EXCERPT_LIMIT` | `1500` | Characters, for wiki excerpts (used from PR 5). |

The proxy (`apps/proxy/Caddyfile.ce`) applies `BOOK_FILE_SIZE_LIMIT` to the storage route only. This is
safe because every upload to storage needs a signed policy that fixes its own maximum size. Keep
`BOOK_FILE_SIZE_LIMIT` ≥ `FILE_SIZE_LIMIT`.

## Before enabling in production

**Storage.** Every book keeps its original file plus a processed copy: sanitized chapters, and the
images and stylesheets the chapters use. Measured on the preview:

| Book | Original | Processed | Total | Chapter text in Postgres |
| --- | --- | --- | --- | --- |
| *Pride and Prejudice* (Project Gutenberg, 164 illustrations) | 24.8 MB | 26.1 MB (179 objects) | 2.05× | 0.7 MB |
| Synthetic, 1,000 chapters, large images | 76.0 MB | 26.2 MB (1,007 objects) | 1.35× | 7.2 MB |

Plan for **about 2.1× the size of the books you expect** in object storage, plus up to 10% of that in
Postgres for chapter text. The worst case is an EPUB whose images are all used by its chapters. When a
book is reprocessed, the old output is deleted after the new output is in place, so for a short time
up to one extra processed copy exists. Deleted books are purged from storage in the background.

**Worker.**
- Processing reads the book from a temporary file, one book at a time per worker process, so temporary disk is at most `BOOK_FILE_SIZE_LIMIT` per busy process.
- On the preview, a 72 MB, 1,000-chapter EPUB processed in about 8 s. The worker's memory rose by about 25 MB, sampled every 1–2 s, so a short peak could be missed.

**Checklist:**
1. Check free space on the object store (and on the Docker host, if MinIO runs there).
2. Set `BOOK_FILE_SIZE_LIMIT` on the API, the worker and the proxy, and keep it ≥ `FILE_SIZE_LIMIT`.
3. Set `LIBRARY_ENABLED=1` on the API and the worker.
4. Watch usage with `python manage.py library_storage_report`. It reads the database and is fast; `--storage` measures the bucket itself by listing every object.

*The ValentraHQ VM had 28 GB (19%) disk free when this was written, shared with Docker images and the
live Plane install. Free space before inviting real libraries.*

## Data model

Migration `0126_library_books` creates three new tables and changes no existing ones.

- **`books`:** owner, workspace, visibility, format, the original file (a `FileAsset` of type `BOOK_FILE`), size, SHA-256, processing state (status, token, attempts, processor version, storage prefix), metadata, `edited_fields`, covers, TOC, counts, `archived_at`.
- **`book_chapters`:** index, spine id and path, title, storage key of the sanitized chapter, plain text (used later for search and excerpts), `linear`.
- **`book_resources`:** path inside the EPUB, storage key, media type, size.

Reading state, annotations, collections and tags are added with the PRs that use them.

## Tests

- **Unit tests** (`plane/tests/unit/library/`):
  - valid EPUB 2 and EPUB 3 books
  - malformed books, ZIP safety (path traversal, symlinks, duplicates, encryption, zip bombs, entry and total limits, lying headers), XXE and billion laughs, DRM, damaged entries
  - sanitizing of hostile chapters and CSS, image type checks, PDFs
  - processing: success, invalid and unsafe books, checksum mismatch, stale tokens, duplicate deliveries, a newer attempt winning, reprocessing (output replaced, edits kept), transient errors (retry and rollback), deletion during processing, purge
- **Contract tests** (`plane/tests/contract/app/test_library_app.py`):
  - the feature flag, guests and outsiders, privacy of personal books (including from admins), workspace books
  - list/single consistency for every user and book, cross-workspace access
  - upload validation, the separate size limit, duplicates, upload completion
  - metadata edits, archive, search, delete, reprocess, downloads, chapter resource resolution

## Limitations

- PDFs are not readable in the browser yet; they can be downloaded.
- SVG images, embedded fonts and audio/video inside EPUBs are not served: SVG is dropped, and the reader uses its own fonts.
- Processing time is bounded by a 15-minute soft limit per attempt.
- Covers come from the EPUB only; PDFs have no cover.
