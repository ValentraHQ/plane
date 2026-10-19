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
import { setToast } from "@plane/blocks/toast";
import type { TBookAnnotation, TBookAnnotationListResponse } from "@plane/types";
import { EBookAnnotationVisibility } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
// services
import { LibraryService } from "@/services/library.service";
import { libraryErrorMessage } from "@/store/library.store";
// local imports
import { HIGHLIGHTS } from "./reader/reader-frame";
import { plural } from "./utils";

const service = new LibraryService();
const KIND_LABEL = { highlight: "Highlight", note: "Note", bookmark: "Bookmark" } as const;
const PAGE = 100;

/** Every highlight, note and bookmark of the user, across the books they can still see. */
export const LibraryNotes = observer(function LibraryNotes({ workspaceSlug }: { workspaceSlug: string }) {
  const params = useSearchParams();
  const book = params.get("book") ?? undefined;
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [data, setData] = useState<TBookAnnotationListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    service
      .listMyAnnotations(workspaceSlug, { book, kind: kind || undefined, search: query || undefined, limit: PAGE })
      .then((response) => {
        if (!cancelled) setData(response);
        return response;
      })
      .catch((err) => !cancelled && setError(libraryErrorMessage(err, "Your notes could not be loaded.")));
    return () => {
      cancelled = true;
    };
  }, [book, kind, query, workspaceSlug]);

  const loadMore = async () => {
    if (!data) return;
    const more = await service.listMyAnnotations(workspaceSlug, {
      book,
      kind: kind || undefined,
      search: query || undefined,
      limit: PAGE,
      offset: data.results.length,
    });
    setData({ ...more, results: [...data.results, ...more.results] });
  };

  const link = (a: TBookAnnotation) =>
    `/${workspaceSlug}/library/books/${a.book}/read?chapter=${a.chapter}&offset=${a.start_offset}`;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative flex min-w-0 flex-1 items-center">
          <span className="sr-only">Search notes</span>
          <SearchOutline className="pointer-events-none absolute left-2 size-4 text-placeholder" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search highlights and notes"
            className="h-8 w-full rounded-md border border-subtle bg-surface-1 pr-2 pl-8 text-13 text-primary placeholder:text-placeholder"
          />
        </label>
        <select
          aria-label="Kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-secondary"
        >
          <option value="">All kinds</option>
          <option value="highlight">Highlights</option>
          <option value="note">Notes</option>
          <option value="bookmark">Bookmarks</option>
        </select>
        <Button
          variant="secondary"
          size="md"
          stretch="auto"
          label="Export Markdown"
          onClick={() =>
            void service
              .exportAnnotations(workspaceSlug, book)
              .catch((err) =>
                setToast({ type: "error", title: "Error!", message: libraryErrorMessage(err, "The export failed.") })
              )
          }
        />
      </div>
      {book && (
        <p className="text-12 text-tertiary">
          Showing one book.{" "}
          <Link href={`/${workspaceSlug}/library/notes`} className="text-accent-primary hover:underline">
            Show all books
          </Link>
        </p>
      )}
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      {data && (
        <p className="text-12 text-tertiary" aria-live="polite">
          {data.count} {data.count === 1 ? "item" : "items"}
          {data.counts.highlight ? ` · ${plural(data.counts.highlight, "highlight")}` : ""}
          {data.counts.note ? ` · ${plural(data.counts.note, "note")}` : ""}
          {data.counts.bookmark ? ` · ${plural(data.counts.bookmark, "bookmark")}` : ""}
        </p>
      )}
      {data && data.results.length === 0 && (
        <p className="py-10 text-center text-13 text-tertiary">
          {query || kind
            ? "Nothing matches."
            : "No highlights, notes or bookmarks yet. Select text while reading to add one."}
        </p>
      )}
      <ul className="flex flex-col gap-2" aria-label="Notes and highlights">
        {data?.results.map((a) => (
          <li key={a.id}>
            <Link
              href={link(a)}
              className="flex gap-3 rounded-lg border border-subtle p-3 hover:bg-layer-transparent-hover"
            >
              <span
                aria-hidden
                className="mt-1 w-1 shrink-0 self-stretch rounded-full"
                style={{
                  background: a.kind === "highlight" ? HIGHLIGHTS[a.color || "yellow"] : "rgba(128,128,128,0.4)",
                }}
              />
              <span className="flex min-w-0 flex-col gap-1">
                <span className="truncate text-12 text-tertiary">
                  {KIND_LABEL[a.kind]} · {a.book_title}
                  {a.chapter_title ? ` · ${a.chapter_title}` : ""} · {renderFormattedDate(a.created_at)}
                  {a.visibility === EBookAnnotationVisibility.SHARED ? " · Shared" : ""}
                </span>
                {a.quote && <span className="line-clamp-3 text-13 text-secondary">{a.quote}</span>}
                {a.note && <span className="text-13 whitespace-pre-wrap text-primary">{a.note}</span>}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {data && data.results.length < data.count && (
        <Button variant="secondary" size="md" stretch="auto" label="Show more" onClick={() => void loadMore()} />
      )}
    </div>
  );
});
