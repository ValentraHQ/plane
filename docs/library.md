# Library (eBooks)

> **Fork-specific (ValentraHQ).** Upstream Plane Community Edition has no library. The library is
> **off by default** (`LIBRARY_ENABLED=0`). Read [Before enabling in production](#before-enabling-in-production)
> first.

Workspace members can upload EPUB and PDF books to a personal library or to the workspace library.
EPUBs are processed in the background into sanitized chapters for the in-browser reader. PDFs are
stored with their metadata and can be downloaded; reading PDFs in the browser comes in a later PR.

This document covers the foundation (PR 1 of the library series), the library UI (PR 2), the
reader (PR 3), annotations (PR 4) and wiki integration (PR 5). Search across books follows in a later PR.

## Reading (web)

**Read** on an EPUB's page (or _Continue reading · 42%_, or _Read again_) opens the reader at
`/library/books/<id>/read`. The library shows a **Continue reading** row, progress bars on the cards
and a _Reading_ filter (_Not started_, _Reading_, _Finished_). The book menu has _Mark as finished_ /
_Mark as unread_.

- **One chapter at a time.** The next chapter is fetched in advance, so a 1,000-chapter book opens as quickly as a short one. A chapter is fetched again a minute before its image links expire.
- **Isolation.** Each chapter is rendered in an `<iframe sandbox="allow-same-origin">` (no scripts, forms, pop-ups or top navigation) with its own Content-Security-Policy: `default-src 'none'`, images only from the origins of the book's signed links, inline styles, and nothing else. This is a second line of defense behind the server-side sanitizing.
- **Links.** Internal links (`plane-chapter:`) open the chapter in the reader. `http(s)` and `mailto` links open in a new tab with `noopener,noreferrer`.
- **Layout and settings.** Pages (CSS columns: one column per page, so a page turn is exactly one frame width) or Scroll.
  - Themes: Light, Sepia, Dark and Auto (follows the app). The theme overrides the book's colours, so text is always readable.
  - Text size 12–32 px, the book's own font or Serif / Sans-serif / Monospace / Dyslexia-friendly, line spacing, and margins.
  - Settings are applied in place (no reload, no lost place) and saved per person for every device (`reader-preferences/`).
- **Navigation.**
  - keyboard: ←/→, PageUp/PageDown, Space and Shift+Space, Esc to close panels
  - mouse: arrow buttons beside the page
  - touch: tap the left or right quarter of the page, or swipe
  - contents panel, search panel, full screen
  - on phones the app sidebar closes so the book gets the whole width
- **Search inside the book.** Matches across chapters with snippets. A result opens its chapter at that occurrence, with the text selected.
- **Position and progress.**
  - The position is a character offset into the chapter's text plus a short quote, so it survives font, size, margin and window changes. It is saved 1.5 s after each move and again (with `fetch(..., {keepalive: true})`) when the tab is hidden or closed.
  - Progress is the share of the book's characters before the reading point.
  - Reaching the end of the last chapter marks the book finished.
  - Reading state is private: nobody else sees your position, progress or status.

## Highlights, notes and bookmarks (web)

- **Highlight:** select text in the reader. A toolbar offers five colours (yellow, green, blue, pink, purple), _Note_ and _Copy_. Clicking a highlight opens it: change the colour, add or edit a note, share it, or delete it.
- **Note:** _Note_ on the toolbar saves the selection with a note (a note needs text). Notes are drawn with a dotted underline.
- **Bookmark:** the bookmark button in the reader header marks the current page; pressed again, it removes the bookmark.
- **Notes panel** (speech-bubble button): everything in this book, grouped by chapter, with _All / Mine / Shared_ when others have shared something. Clicking an entry opens its passage. _Export Markdown_ downloads your own annotations of this book.
- **Notes & highlights** (`/library/notes`, linked from the library sidebar): all your annotations across the books you can still see, newest first, with search (quote and note text), a kind filter and _Export Markdown_. Each entry links to `/library/books/<id>/read?chapter=<n>&offset=<o>`, which opens the reader at that passage. The book page shows a summary (_Your notes: 3 highlights · 1 note_) with _See all_ and _Export Markdown_.
- **Stable references.** An annotation stores its chapter, start and end character offsets into the chapter text, the quoted text and 32 characters before and after it. When a chapter is drawn, the offsets are used if the text there still matches the quote; otherwise every occurrence of the quote is scored by how well its surroundings match and how close it is to the old offset, and the best one is used. If the quote is gone (the book was replaced by a different edition), the annotation is kept and listed as _not found in the text_. Highlights are drawn with `<mark>` elements around text nodes, which never changes the text the offsets refer to.
- **Private by default.** An annotation is visible only to its author until they tick _Share with everyone who can read this book_. Only annotations on workspace books can be shared. Shared annotations are shown with a dashed underline and the author's name, and only the author can change them. A workspace admin can delete a shared annotation (moderation) but cannot see private ones. When a book is made personal again, the other members lose access to it and to their annotations on it, and the owner no longer sees them; sharing the book again brings them back.
- **Export** includes only your own annotations: a `# <book>` section per book, a `## <chapter>` heading per chapter, each quote as a `>` block followed by its note, and bookmarks as list items.

## Wiki pages and links (web)

- **A wiki page from the book.** *Wiki page* appears on the selection toolbar, on a highlight or note, and in the reader's Notes panel (all your highlights and notes of the book, which you can tick off one by one). The dialog lets you choose:
  - the title (by default *Notes on <book>*)
  - a space you can write in, and optionally a parent page
  - an introduction
  - who can see the page
- **The page** contains the introduction, then per chapter each quote as a blockquote with your note and an *Open this passage in the book* link, then a source line (title, authors, publisher, year) linking to the book. It is created through the wiki's own create path, so space roles, parent restrictions and private pages apply as in the wiki. The book page lists it under *Linked* as *created from the book*, with a link to the passage.
- **Private by default.** The page is private (only you) unless you choose *Everyone in <space>*.
  - Sharing shows how many characters will be quoted and a copyright reminder, and needs the box *I may share these excerpts…* ticked.
  - The server refuses a shared page without that confirmation.
  - When the book is personal, the dialog says that others will see the excerpts but cannot open the book.
- **Excerpt limits** apply to every page:
  - each quote is at most `BOOK_EXCERPT_LIMIT` characters (1,500); the dialog shortens longer ones at a word boundary and says so
  - a page quotes at most `BOOK_EXCERPT_PAGE_LIMIT` characters in total (10,000)
  - the server checks every quote against the chapter text (ignoring whitespace), so a page can only quote what the book says
- **Links.** *Link…* on the book page links the book to a work item (search by name or by ID such as `WEB-12`), a project or a page. A work item shows a **Books** section with its linked books, *Link a book* and *Unlink*.
  - A link is shown only to people who can see both the book and the target, so it never reveals a personal book or a project someone is not in.
  - Linking to a project or work item needs a member role in that project (not guest).
  - The person who added a link and anyone who can edit the book can remove it.

## Using the library (web)

- **Library** in the sidebar, for workspace admins and members. It is hidden when `LIBRARY_ENABLED` is off, and for guests.
- **Shelves:** _All books_, _Only me_, _Shared with workspace_, _Archived_, then your collections.
- **Grid:** covers, or a generated cover when a book has none. Search by title, author, ISBN, publisher or tag; filter by format and tag; sort by date added, title or date updated. More books load as you scroll.
- **Uploading:** use **Upload books**, or drop EPUB/PDF files anywhere on the page. Choose _Only me_ or _Everyone in the workspace_. Several files go one after another, and a panel shows each file going through checking (SHA-256), upload and processing. A duplicate links to the existing book.
- **Book page:** cover, details, tags, subjects and table of contents.
  - The actions depend on your permissions: _Download_, _Edit details_ (metadata and tags), _Collections…_, _Share with workspace_ / _Make personal_ (owner only), _Archive_ / _Restore_, _Process again_, _Delete_.
  - A failed book shows why it failed.
  - Clicking a tag shows the library filtered by that tag.
- **Collections** are shelves: private (_Only me_) or shared with the workspace.
  - A shared collection holds workspace books only, and a book made personal leaves shared collections automatically.
  - Shared collections are managed by their owner and workspace admins; only the owner changes who can see a collection.
  - Deleting a collection keeps its books.
- **Tags** are free-form labels on a book, set by anyone who can edit it.
  - The tag list a person sees is built only from books they can see, so a tag never reveals a private book.
  - Tags are de-duplicated case-insensitively, keeping the first spelling.
- **Unfinished uploads:** a reservation that is never completed (browser closed, upload failed) is hidden after an hour and deleted after a day, together with anything already stored. The daily job is `delete_abandoned_uploads`, at 02:15 UTC.
- **Hashing:** files are hashed in the browser with Web Crypto when available (https or localhost). On plain-http installs, an incremental SHA-256 (`@noble/hashes`) is used, which also avoids loading the whole file into memory.

## Who can do what

All decisions are made by one resolver, `plane/utils/book_access.py`.

|                                           | Personal book | Workspace book                   |
| ----------------------------------------- | ------------- | -------------------------------- |
| View, read, download                      | owner only    | every workspace admin and member |
| Edit metadata, archive, delete, reprocess | owner         | owner and workspace admins       |
| Change visibility (personal ↔ workspace)  | owner         | owner                            |

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

   It then creates the book (status _uploading_) and returns a **signed upload form** for storage. The
   form's policy fixes the exact content type and caps the size at the reserved size, so storage refuses
   anything larger.

2. The browser sends the file **straight to storage**; it never passes through the API.
3. `POST …/books/<id>/upload-complete/`: the API checks that the stored object exists and has the reserved
   size, then queues processing (status _processing_).
4. The worker verifies the file's SHA-256 against the announced one, processes the book, and sets status
   _ready_ or _failed_ with a readable `failure_reason`.

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

| Method               | Path                                |                                                                                                                                                                                                                                              |
| -------------------- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET                  | `books/`                            | List: `search` (title, author, ISBN, publisher), `visibility`, `status`, `format`, `archived=true`, `order_by` (`created_at`, `title`, `updated_at`, `-…`), `limit` ≤ 100, `offset`. Returns `{count, limit, offset, results}`.              |
| POST                 | `books/`                            | Reserve an upload; returns `{book, upload_data}`.                                                                                                                                                                                            |
| GET / PATCH / DELETE | `books/<id>/`                       | Detail (with `toc`); PATCH takes the metadata fields, `visibility` and `archived`.                                                                                                                                                           |
| POST                 | `books/<id>/upload-complete/`       | Start processing after the upload.                                                                                                                                                                                                           |
| POST                 | `books/<id>/reprocess/`             | Process again (owner / admin).                                                                                                                                                                                                               |
| GET                  | `books/<id>/download/`              | `{url, expires_in}`: a signed link to the original file.                                                                                                                                                                                     |
| GET                  | `books/<id>/chapters/`              | `[{id, index, title, href, linear, character_count}]`                                                                                                                                                                                        |
| GET                  | `books/<id>/chapters/<index>/`      | `{index, title, html, css, previous, next, expires_in}` for the reader.                                                                                                                                                                      |
| GET / PUT            | `books/<id>/reading-state/`         | The user's own `{position: {chapter, offset, quote}, progress, status, last_opened_at, completed_at}`. PUT takes any of `position`, `progress` (0–100), `status` (0 unread, 1 reading, 2 finished; unread clears the position) and `opened`. |
| GET                  | `books/<id>/search/?q=`             | `{query, results: [{chapter, chapter_title, occurrence, before, match, after}], truncated}`: at most 25 per chapter and 100 in total, case-insensitive, at least 2 characters.                                                               |
| GET                  | `continue-reading/`                 | Books the user is reading (ready, not archived, still visible to them), most recently opened first, at most 12.                                                                                                                              |
| GET / PUT            | `reader-preferences/`               | `{font_family, font_size, line_height, margin, theme, layout}`, the same on every device.                                                                                                                                                    |
| GET                  | `tags/`                             | `[{name, count}]` across the books the user can see.                                                                                                                                                                                         |
| GET / POST           | `collections/`                      | The user's visible collections (with `book_count` and `permissions`); create `{name, description, visibility}`.                                                                                                                              |
| PATCH / DELETE       | `collections/<id>/`                 | Owner or workspace admin; only the owner changes `visibility`, and a collection holding personal books cannot be shared.                                                                                                                     |
| POST                 | `collections/<id>/books/`           | `{book_ids: [...]}` (at most 200): adds books the user can see. Personal books cannot go into a shared collection.                                                                                                                           |
| DELETE               | `collections/<id>/books/<book_id>/` | Removes one book.                                                                                                                                                                                                                            |
| GET / POST           | `books/<id>/annotations/`           | GET: the annotations of this book the user can see (their own and shared ones), filtered by `chapter`, `kind` and `mine=true`. POST `{kind, chapter, start_offset, end_offset, quote, prefix, suffix, color, note, visibility}`; 409 if the book is not a ready EPUB. |
| PATCH / DELETE       | `annotations/<id>/`                 | PATCH `{color, note, visibility}`: author only. DELETE: the author, or a workspace admin for a shared annotation. Annotations the user cannot see return 404.                                                                                |
| GET                  | `annotations/`                      | The user's own annotations across visible books, newest first: `book`, `kind`, `search`, `limit` ≤ 200, `offset`. Returns `{count, counts: {highlight, note, bookmark}, results}`.                                                         |
| POST                 | `books/<id>/wiki-pages/`            | `{space, parent?, title?, intro?, passages: [{chapter, start_offset, quote, note}] (1–100), share, confirm_excerpts}`: creates a wiki page (private unless `share`). 400 with `code` `excerpt_too_long`, `excerpts_too_long`, `quote_not_found`, `unknown_chapter` or `confirmation_required`; 409 if the book is not a ready EPUB. Returns `{page, link}`. |
| GET / POST           | `books/<id>/links/`                 | The book's links the user can see (both ends visible); POST `{target_type: page\|project\|issue, target_id}` (an existing link returns 200).                                                                                                      |
| DELETE               | `links/<id>/`                       | The person who added the link, or an editor of the book.                                                                                                                                                                                     |
| GET                  | `links/?target_type=&target_id=`    | Books linked to a page, project or work item, with `book_detail`.                                                                                                                                                                            |
| GET                  | `link-targets/?target_type=&search=` | Pages, projects (member role) or work items (member role; `KEY-12` matches the ID) the user could link to, at most 20.                                                                                                                      |
| GET                  | `annotations/export/`               | The user's own annotations as Markdown (`text/markdown` attachment), for all books or one `?book=<id>`.                                                                                                                                     |

The book list also takes `reading=unread|reading|completed` (the user's own status), `tag=<name>` and `collection=<id>`, and its search also matches tags. Book
objects include `tags`, `owner_detail` and the user's own `my_reading` (`{progress, status, last_opened_at}`), and the detail view adds the `collection_ids` the user can
see. PATCH also takes `tags`. The instance config (`/api/instances/`) reports `is_library_enabled` and
`book_file_size_limit`.

Book objects include:

- `permissions`: `{can_view, can_download, can_edit, can_manage}`
- signed `cover_url` and `cover_thumbnail_url`
- `status` (0 uploading, 1 processing, 2 ready, 3 failed) and `failure_reason`

## Configuration

| Variable                      | Default              |                                                                                                                                                                        |
| ----------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LIBRARY_ENABLED`             | `0`                  | Turns the library on (API and worker).                                                                                                                                 |
| `BOOK_FILE_SIZE_LIMIT`        | `104857600` (100 MB) | Per book file. Enforced when reserving, by the storage policy, by the worker, and at the proxy for the storage route. Set it on the API, the worker **and** the proxy. |
| `FILE_SIZE_LIMIT`             | `5242880` (5 MB)     | Unchanged for every other upload and for every other proxy route.                                                                                                      |
| `BOOK_MAX_ARCHIVE_ENTRIES`    | `10000`              | Files inside one EPUB.                                                                                                                                                 |
| `BOOK_MAX_UNPACKED_SIZE`      | `536870912` (512 MB) | Total bytes one EPUB may unpack to.                                                                                                                                    |
| `BOOK_MAX_ENTRY_SIZE`         | `67108864` (64 MB)   | Largest single file inside an EPUB.                                                                                                                                    |
| `BOOK_MAX_COMPRESSION_RATIO`  | `100`                | For entries over 1 MB.                                                                                                                                                 |
| `BOOK_MAX_CHAPTERS`           | `5000`               |                                                                                                                                                                        |
| `BOOK_PROCESSING_MAX_RETRIES` | `3`                  | Retries for storage or network errors.                                                                                                                                 |
| `BOOK_SIGNED_URL_EXPIRATION`  | `600`                | Seconds.                                                                                                                                                               |
| `BOOK_EXCERPT_LIMIT`          | `1500`               | Characters per quote copied into a wiki page.                                                                                                                          |
| `BOOK_EXCERPT_PAGE_LIMIT`     | `10000`              | Characters quoted in one wiki page, all quotes together.                                                                                                               |

The proxy (`apps/proxy/Caddyfile.ce`) applies `BOOK_FILE_SIZE_LIMIT` to the storage route only. This is
safe because every upload to storage needs a signed policy that fixes its own maximum size. Keep
`BOOK_FILE_SIZE_LIMIT` ≥ `FILE_SIZE_LIMIT`.

## Before enabling in production

**Storage.** Every book keeps its original file plus a processed copy: sanitized chapters, and the
images and stylesheets the chapters use. Measured on the preview:

| Book                                                         | Original | Processed               | Total | Chapter text in Postgres |
| ------------------------------------------------------------ | -------- | ----------------------- | ----- | ------------------------ |
| _Pride and Prejudice_ (Project Gutenberg, 164 illustrations) | 24.8 MB  | 26.1 MB (179 objects)   | 2.05× | 0.7 MB                   |
| Synthetic, 1,000 chapters, large images                      | 76.0 MB  | 26.2 MB (1,007 objects) | 1.35× | 7.2 MB                   |

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
4. After upgrading the processor, re-process books made by an older version:
   `python manage.py library_reprocess --outdated` (also `--failed`, `--book <id>…` and `--dry-run`).
   Version 2 keeps SVG cover images that use only `xlink:href`, such as Project Gutenberg cover pages.
5. Watch usage with `python manage.py library_storage_report`. It reads the database and is fast; `--storage` measures the bucket itself by listing every object.

_The ValentraHQ VM had 28 GB (19%) disk free when this was written, shared with Docker images and the
live Plane install. Free space before inviting real libraries._

## Data model

Migration `0126_library_books` creates three new tables and changes no existing ones. Migration
`0127_library_tags_collections` adds `books.tags` (a JSON list) and two tables, `book_collections`
and `book_collection_items`. Migration `0128_library_reading`
adds `book_reading_states` (book, user, position, progress, status, last opened, completed; unique per
book and user) and `reader_preferences` (one row per user).

- **`books`:** owner, workspace, visibility, format, the original file (a `FileAsset` of type `BOOK_FILE`), size, SHA-256, processing state (status, token, attempts, processor version, storage prefix), metadata, `edited_fields`, covers, TOC, counts, `archived_at`.
- **`book_chapters`:** index, spine id and path, title, storage key of the sanitized chapter, plain text (used later for search and excerpts), `linear`.
- **`book_resources`:** path inside the EPUB, storage key, media type, size.

- **`book_collections`:** owner, workspace, name, description, visibility, sort order.
- **`book_collection_items`:** collection, book, sort order; unique per collection and book.

Migration `0130_library_links` adds `book_links`: workspace, book, `target_type` (`page`, `project`, `issue`) with exactly one of `page`, `project`, `issue` set (a check constraint), `origin` (`linked` or `created`), and for created pages the `chapter` and `start_offset` of the first passage. Unique per book and target. No existing table changes.

Migration `0129_library_annotations` adds `book_annotations`:

- **`book_annotations`:** workspace, book, user (the author), kind (`highlight`, `note`, `bookmark`), colour, chapter, start and end offsets, quote, prefix and suffix (64 characters each), note, visibility (0 private, 1 shared). Indexed by book and user, by book and visibility (shared annotations), and by user and creation date (the Notes page). It is soft-deleted like other Plane models.

Validation: offsets must be in order and span at most 20,000 characters; highlights and notes need a selection; notes need text; the quote is at most 4,000 characters (the browser sends the start of longer passages, and the offsets cover the rest) and notes at most 10,000.

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
  - annotations: kinds and validation, private by default, sharing only on workspace books, shared annotations hidden when a book becomes personal, admin moderation, the cross-book list, Markdown export, guests
  - wiki pages from books: private by default with a link back, escaping, quotes checked against the book, excerpt limits, confirmation for sharing, the wiki's space and restriction rules
  - links: visible only with both ends, project membership for projects and work items, guests, duplicates, who may remove

## Limitations

- PDFs are not readable in the browser yet; they can be downloaded.
- *Wiki page* always creates a new page; adding passages to an existing page is done by copying them in the editor.
- Linked books are shown on the book page and on work items. Wiki and project pages show their source in the page text, not in a separate panel.
- SVG images, embedded fonts and audio/video inside EPUBs are not served: SVG is dropped, and the reader uses its own fonts.
- Processing time is bounded by a 15-minute soft limit per attempt.
- Covers come from the EPUB only; PDFs have no cover.
