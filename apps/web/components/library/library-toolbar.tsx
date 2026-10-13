/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { SearchOutline } from "@makeplane/propel/icons";
import type { TBookFilters, TBookFormat, TBookOrderBy } from "@plane/types";
// hooks
import { useLibrary } from "@/hooks/store/use-library";

const SORT_OPTIONS: { value: TBookOrderBy; label: string }[] = [
  { value: "-created_at", label: "Recently added" },
  { value: "title", label: "Title A–Z" },
  { value: "-title", label: "Title Z–A" },
  { value: "-updated_at", label: "Recently updated" },
];

const selectClass =
  "h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-secondary focus:outline-2 focus:outline-accent-strong";

/** Search, format / tag filters and sort for the book grid. */
export const LibraryToolbar = observer(function LibraryToolbar() {
  const { filters, setFilters, tags, count, isLoading } = useLibrary();
  const [search, setSearch] = useState(filters.search);

  // keep the box in sync when filters are reset elsewhere
  useEffect(() => setSearch(filters.search), [filters.search]);

  // search as you type, without a request per keystroke
  useEffect(() => {
    if (search === filters.search) return;
    const timer = setTimeout(() => setFilters({ search: search.trim() }), 300);
    return () => clearTimeout(timer);
  }, [filters.search, search, setFilters]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="relative flex min-w-0 flex-1 items-center sm:max-w-sm">
        <span className="sr-only">Search books</span>
        <SearchOutline className="pointer-events-none absolute left-2 size-4 text-placeholder" />
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search title, author, ISBN, tag…"
          className="h-8 w-full rounded-md border border-subtle bg-surface-1 pr-2 pl-8 text-13 text-primary placeholder:text-placeholder focus:outline-2 focus:outline-accent-strong"
        />
      </label>
      <label className="flex items-center gap-1">
        <span className="sr-only">Format</span>
        <select
          className={selectClass}
          value={filters.format ?? ""}
          onChange={(e) => setFilters({ format: (e.target.value || null) as TBookFormat | null })}
        >
          <option value="">All formats</option>
          <option value="epub">EPUB</option>
          <option value="pdf">PDF</option>
        </select>
      </label>
      <label className="flex items-center gap-1">
        <span className="sr-only">Tag</span>
        <select
          className={selectClass}
          value={filters.tag ?? ""}
          onChange={(e) => setFilters({ tag: e.target.value || null })}
          disabled={tags.length === 0 && !filters.tag}
        >
          <option value="">All tags</option>
          {tags.map((tag) => (
            <option key={tag.name} value={tag.name}>
              {tag.name} ({tag.count})
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1">
        <span className="sr-only">Reading</span>
        <select
          className={selectClass}
          value={filters.reading ?? ""}
          onChange={(e) => setFilters({ reading: (e.target.value || null) as TBookFilters["reading"] })}
        >
          <option value="">Any progress</option>
          <option value="unread">Not started</option>
          <option value="reading">Reading</option>
          <option value="completed">Finished</option>
        </select>
      </label>
      <label className="flex items-center gap-1">
        <span className="sr-only">Sort by</span>
        <select
          className={selectClass}
          value={filters.order_by}
          onChange={(e) => setFilters({ order_by: e.target.value as TBookOrderBy })}
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {!isLoading && (
        <span className="ml-auto text-12 text-tertiary" aria-live="polite">
          {count} {count === 1 ? "book" : "books"}
        </span>
      )}
    </div>
  );
});
