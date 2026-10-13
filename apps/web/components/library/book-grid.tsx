/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { GlobeOutline, LockOutline } from "@makeplane/propel/icons";
import { EmptyStateDetailed } from "@plane/blocks/empty-state";
import { EBookStatus, EBookVisibility } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useLibrary } from "@/hooks/store/use-library";
// local imports
import { BookActionsMenu } from "./book-actions-menu";
import { BookCover } from "./book-cover";
import { STATUS_LABELS, bookAuthors, bookTitle } from "./utils";

type CardProps = { workspaceSlug: string; bookId: string };

export const BookCard = observer(function BookCard({ workspaceSlug, bookId }: CardProps) {
  const { getBookById } = useLibrary();
  const book = getBookById(bookId);
  if (!book) return null;
  const href = `/${workspaceSlug}/library/books/${book.id}`;
  const shared = book.visibility === EBookVisibility.WORKSPACE;

  return (
    <li className="group relative flex flex-col gap-2" data-testid="book-card">
      <Link href={href} className="block rounded-md focus-visible:outline-2 focus-visible:outline-accent-strong">
        <BookCover book={book} className={cn({ "opacity-60": book.status !== EBookStatus.READY })} />
      </Link>
      <div className="shadow-sm absolute top-1.5 right-1.5 rounded-md bg-surface-1/90 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
        <BookActionsMenu workspaceSlug={workspaceSlug} book={book} />
      </div>
      {book.status !== EBookStatus.READY && (
        <span className="absolute top-1.5 left-1.5">
          <Badge
            size="sm"
            variant={book.status === EBookStatus.FAILED ? "danger" : "brand"}
            label={STATUS_LABELS[book.status]}
          />
        </span>
      )}
      <div className="flex min-w-0 flex-col gap-0.5">
        <Link href={href} className="line-clamp-2 text-13 leading-snug font-medium text-primary hover:underline">
          {bookTitle(book)}
        </Link>
        <span className="truncate text-12 text-tertiary">{bookAuthors(book)}</span>
        <span className="flex items-center gap-1.5 text-11 text-placeholder">
          {shared ? (
            <GlobeOutline className="size-3" aria-label="Shared with the workspace" />
          ) : (
            <LockOutline className="size-3" aria-label="Only you" />
          )}
          <span className="uppercase">{book.format}</span>
          {book.archived_at && <span>· Archived</span>}
        </span>
      </div>
    </li>
  );
});

type GridProps = {
  workspaceSlug: string;
  onUpload: () => void;
  canUpload: boolean;
};

export const BookGrid = observer(function BookGrid({ workspaceSlug, onUpload, canUpload }: GridProps) {
  const {
    listIds,
    isLoading,
    isLoadingMore,
    hasMore,
    count,
    loadError,
    filters,
    fetchMoreBooks,
    resetFilters,
    fetchBooks,
  } = useLibrary();
  const sentinel = useRef<HTMLDivElement>(null);

  // load the next page when the end of the grid scrolls into view
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasMore) return;
    const intersection = new IntersectionObserver(
      (entries) => entries.some((entry) => entry.isIntersecting) && void fetchMoreBooks(workspaceSlug),
      { rootMargin: "400px" }
    );
    intersection.observe(node);
    return () => intersection.disconnect();
  }, [fetchMoreBooks, hasMore, workspaceSlug, listIds.length]);

  const filtered =
    !!filters.search || filters.visibility !== null || !!filters.format || !!filters.tag || !!filters.collection;

  if (isLoading && listIds.length === 0) {
    return (
      <ul
        className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
        aria-busy="true"
        aria-label="Loading books"
      >
        {Array.from({ length: 12 }, (_, i) => (
          <li key={i} className="flex flex-col gap-2">
            <div className="aspect-[2/3] w-full animate-pulse rounded-md bg-layer-3" />
            <div className="h-3 w-3/4 animate-pulse rounded-sm bg-layer-3" />
            <div className="h-3 w-1/2 animate-pulse rounded-sm bg-layer-3" />
          </li>
        ))}
      </ul>
    );
  }
  if (loadError) {
    return (
      <div className="grid place-items-center gap-3 py-16 text-center" role="alert">
        <p className="text-13 text-secondary">{loadError}</p>
        <Button
          variant="secondary"
          size="md"
          stretch="auto"
          label="Try again"
          onClick={() => void fetchBooks(workspaceSlug)}
        />
      </div>
    );
  }
  if (listIds.length === 0) {
    if (filtered || filters.archived) {
      return (
        <div className="grid place-items-center gap-3 py-16 text-center">
          <p className="text-14 font-medium text-primary">
            {filters.archived && !filtered ? "No archived books" : "No books match"}
          </p>
          {filtered && (
            <Button variant="secondary" size="md" stretch="auto" label="Clear filters" onClick={resetFilters} />
          )}
        </div>
      );
    }
    return (
      <EmptyStateDetailed
        assetKey="page"
        title="Your library is empty"
        description={
          canUpload
            ? "Add EPUB or PDF books: keep them to yourself or share them with the workspace. Drop files anywhere on this page."
            : "No books have been shared with this workspace yet."
        }
        actions={canUpload ? [{ label: "Upload books", onClick: onUpload, variant: "primary" }] : undefined}
      />
    );
  }
  return (
    <>
      <p className="sr-only" aria-live="polite">
        {count} books
      </p>
      <ul
        className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
        aria-label="Books"
      >
        {listIds.map((bookId) => (
          <BookCard key={bookId} workspaceSlug={workspaceSlug} bookId={bookId} />
        ))}
      </ul>
      <div ref={sentinel} className="h-8" />
      {isLoadingMore && <p className="py-4 text-center text-12 text-tertiary">Loading more…</p>}
    </>
  );
});
