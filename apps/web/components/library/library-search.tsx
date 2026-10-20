/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { SearchOutline } from "@makeplane/propel/icons";
import type { TBookFormat, TLibrarySearchPassage, TLibrarySearchResponse, TLibrarySearchResult } from "@plane/types";
import { EBookVisibility } from "@plane/types";
// hooks
import { useInstance } from "@/hooks/store/use-instance";
// services
import { LibraryService } from "@/services/library.service";
import { libraryErrorMessage } from "@/store/library.store";
// local imports
import { BookCover } from "./book-cover";
import { bookAuthors, bookTitle, plural } from "./utils";

const service = new LibraryService();
const PAGE = 20;
const selectClass =
  "h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-secondary focus:outline-2 focus:outline-accent-strong";

const passageHref = (slug: string, bookId: string, p: TLibrarySearchPassage) =>
  `/${slug}/library/books/${bookId}/read?${new URLSearchParams({
    chapter: String(p.chapter),
    find: p.match,
    occurrence: String(p.occurrence),
  }).toString()}`;

function Result({ workspaceSlug, result }: { workspaceSlug: string; result: TLibrarySearchResult }) {
  const { book, passages } = result;
  const more = result.chapter_matches - passages.length;
  return (
    <li className="flex gap-4 rounded-lg border border-subtle p-3">
      <Link href={`/${workspaceSlug}/library/books/${book.id}`} className="w-14 shrink-0" tabIndex={-1} aria-hidden>
        <BookCover book={book} />
      </Link>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex min-w-0 flex-col">
          <Link
            href={`/${workspaceSlug}/library/books/${book.id}`}
            className="truncate text-14 font-medium text-primary hover:underline"
          >
            {bookTitle(book)}
          </Link>
          <span className="truncate text-12 text-tertiary">
            {bookAuthors(book)}
            {result.matched_details && " · matches the book's details"}
            {result.matched_text && ` · found in ${plural(result.chapter_matches, "chapter")}`}
          </span>
        </div>
        {passages.length > 0 && (
          <ul className="flex flex-col gap-1.5" aria-label={`Passages in ${bookTitle(book)}`}>
            {passages.map((p) => (
              <li key={`${p.chapter}:${p.occurrence}:${p.match}`}>
                <Link
                  href={passageHref(workspaceSlug, book.id, p)}
                  className="block rounded-md px-2 py-1 text-12 text-secondary hover:bg-layer-transparent-hover"
                >
                  <span className="mr-2 text-11 font-medium text-tertiary">
                    {p.chapter_title || `Section ${p.chapter + 1}`}
                  </span>
                  …{p.before}
                  <mark className="rounded-sm bg-[rgba(250,204,21,0.45)] px-0.5 text-primary">{p.match}</mark>
                  {p.after}…
                </Link>
              </li>
            ))}
          </ul>
        )}
        {more > 0 && (
          <Link
            href={`/${workspaceSlug}/library/books/${book.id}/read`}
            className="text-12 text-accent-primary hover:underline"
          >
            Open the book to search the {plural(more, "other chapter")}
          </Link>
        )}
      </div>
    </li>
  );
}

/** Search across the books the user can see: their details and, when enabled, their text. */
export const LibrarySearch = observer(function LibrarySearch({ workspaceSlug }: { workspaceSlug: string }) {
  const params = useSearchParams();
  const { config } = useInstance();
  const fulltext = config?.is_library_fulltext_enabled !== false;
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [format, setFormat] = useState<TBookFormat | "">("");
  const [shelf, setShelf] = useState<"" | "0" | "1">("");
  const [inText, setInText] = useState(true);
  const [data, setData] = useState<TLibrarySearchResponse | undefined>();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | undefined>();

  // search as you type; the query is kept in the address so the page can be shared or reloaded
  useEffect(() => {
    const q = query.trim();
    const url = new URL(window.location.href);
    if (q) url.searchParams.set("q", q);
    else url.searchParams.delete("q");
    window.history.replaceState(window.history.state, "", url.toString());
    if (q.length < 2) {
      setData(undefined);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setIsLoading(true);
      setError(undefined);
      service
        .searchLibrary(workspaceSlug, {
          q,
          content: inText,
          file_format: format || null,
          visibility: shelf === "" ? null : (Number(shelf) as EBookVisibility),
          limit: PAGE,
        })
        .then((response) => {
          if (!cancelled) setData(response);
          return response;
        })
        .catch((err) => !cancelled && setError(libraryErrorMessage(err, "The search failed.")))
        .finally(() => !cancelled && setIsLoading(false));
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [workspaceSlug, query, format, shelf, inText]);

  const loadMore = async () => {
    if (!data) return;
    setIsLoading(true);
    try {
      const next = await service.searchLibrary(workspaceSlug, {
        q: data.query,
        content: inText,
        file_format: format || null,
        visibility: shelf === "" ? null : (Number(shelf) as EBookVisibility),
        limit: PAGE,
        offset: data.results.length,
      });
      setData({ ...next, results: [...data.results, ...next.results] });
    } catch (err) {
      setError(libraryErrorMessage(err, "The search failed."));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative flex min-w-0 flex-1 basis-64 items-center">
          <span className="sr-only">Search the library</span>
          <SearchOutline className="pointer-events-none absolute left-2 size-4 text-placeholder" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the page exists to search
            autoFocus
            placeholder={fulltext ? "Search titles, authors and the text of books" : "Search titles, authors, tags…"}
            className="h-9 w-full rounded-md border border-subtle bg-surface-1 pr-2 pl-8 text-13 text-primary placeholder:text-placeholder focus:outline-2 focus:outline-accent-strong"
          />
        </label>
        <select
          aria-label="Format"
          className={selectClass}
          value={format}
          onChange={(e) => setFormat(e.target.value as TBookFormat | "")}
        >
          <option value="">All formats</option>
          <option value="epub">EPUB</option>
          <option value="pdf">PDF</option>
        </select>
        <select
          aria-label="Shelf"
          className={selectClass}
          value={shelf}
          onChange={(e) => setShelf(e.target.value as "" | "0" | "1")}
        >
          <option value="">All books</option>
          <option value={String(EBookVisibility.PERSONAL)}>Only me</option>
          <option value={String(EBookVisibility.WORKSPACE)}>Shared with workspace</option>
        </select>
        {fulltext && (
          <label className="flex items-center gap-2 text-13 text-secondary">
            <input type="checkbox" checked={inText} onChange={(e) => setInText(e.target.checked)} />
            Search inside books
          </label>
        )}
      </div>

      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      {query.trim().length < 2 && (
        <p className="py-10 text-center text-13 text-tertiary">
          Type at least two characters. Use quotes for a phrase (“white rabbit”) and a minus to leave a word out (rabbit
          -hole).
        </p>
      )}
      {data && query.trim().length >= 2 && (
        <>
          <p className="text-12 text-tertiary" aria-live="polite">
            {plural(data.count, "book")}
            {!data.content_searched && " · titles and details only"}
          </p>
          {data.results.length === 0 ? (
            <p className="py-10 text-center text-13 text-tertiary">No books match “{data.query}”.</p>
          ) : (
            <ul className="flex flex-col gap-3" aria-label="Search results">
              {data.results.map((result) => (
                <Result key={result.book.id} workspaceSlug={workspaceSlug} result={result} />
              ))}
            </ul>
          )}
          {data.results.length < data.count && (
            <div className="flex justify-center">
              <Button
                stretch="auto"
                variant="secondary"
                size="md"
                label={isLoading ? "Loading…" : "Show more"}
                disabled={isLoading}
                onClick={() => void loadMore()}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
});
