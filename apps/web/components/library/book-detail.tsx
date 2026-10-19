/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { GlobeOutline, LockOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import type { TBook, TBookTocEntry } from "@plane/types";
import { EBookReadingStatus, EBookStatus, EBookVisibility } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
// hooks
import { useLibrary } from "@/hooks/store/use-library";
import { useAppRouter } from "@/hooks/use-app-router";
import { LibraryService } from "@/services/library.service";
import { libraryErrorMessage } from "@/store/library.store";
// local imports
import { BookActionsMenu } from "./book-actions-menu";
import { BookCover } from "./book-cover";
import { BookEditModal } from "./book-edit-modal";
import { STATUS_LABELS, bookAuthors, bookTitle, formatBytes, plural } from "./utils";

function TocList({ entries, depth = 0 }: { entries: TBookTocEntry[]; depth?: number }) {
  return (
    <ol className={depth ? "mt-1 flex flex-col gap-1 border-l border-subtle pl-3" : "flex flex-col gap-1"}>
      {entries.map((entry, index) => (
        // oxlint-disable-next-line react/no-array-index-key -- TOC entries have no identity; the list never reorders
        <li key={`${depth}-${index}`} className="text-13 text-secondary">
          {entry.title || "Untitled"}
          {entry.children.length > 0 && depth < 3 && <TocList entries={entry.children} depth={depth + 1} />}
        </li>
      ))}
    </ol>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-11 tracking-wide text-tertiary uppercase">{label}</dt>
      <dd className="text-13 break-words text-primary">{children}</dd>
    </div>
  );
}

type Props = { workspaceSlug: string; bookId: string };

const notesService = new LibraryService();

export const BookDetail = observer(function BookDetail({ workspaceSlug, bookId }: Props) {
  const router = useAppRouter();
  const { getBookById, fetchBook, downloadBook, reprocessBook, setFilters } = useLibrary();
  const book = getBookById(bookId);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const { data: notes } = useSWR(
    book?.format === "epub" ? `LIBRARY_BOOK_NOTES_${bookId}` : null,
    () => notesService.listMyAnnotations(workspaceSlug, { book: bookId, limit: 1 }),
    { revalidateOnFocus: false }
  );
  const processing = book?.status === EBookStatus.PROCESSING || book?.status === EBookStatus.UPLOADING;
  const { error, isLoading } = useSWR(
    `LIBRARY_BOOK_${bookId}`,
    () => fetchBook(workspaceSlug, bookId),
    // keep checking while the worker processes the book
    { refreshInterval: processing ? 2000 : 0, revalidateOnFocus: false }
  );

  if (!book) {
    if (isLoading) return <div className="grid h-full place-items-center text-13 text-tertiary">Loading…</div>;
    return (
      <div className="grid h-full place-items-center gap-3 p-6 text-center">
        <div className="flex flex-col items-center gap-3">
          <p className="text-14 font-medium text-primary">This book is not available</p>
          <p className="max-w-sm text-13 text-tertiary">
            {error ? libraryErrorMessage(error, "It does not exist, or you do not have access to it.") : ""}
          </p>
          <Button
            variant="secondary"
            size="md"
            stretch="auto"
            label="Back to the library"
            onClick={() => router.push(`/${workspaceSlug}/library`)}
          />
        </div>
      </div>
    );
  }

  const facts: [string, React.ReactNode][] = [
    ["Format", book.format.toUpperCase()],
    ["Size", formatBytes(book.file_size)],
    [
      book.format === "pdf" ? "Pages" : "Chapters",
      book.format === "pdf" ? (book.page_count ?? "—") : book.chapter_count || "—",
    ],
    ["Language", book.language || "—"],
    ["Publisher", book.publisher || "—"],
    ["Published", book.published_date || "—"],
    ["ISBN", book.isbn || "—"],
    ["Added by", book.owner_detail?.display_name ?? "—"],
    ["Added", renderFormattedDate(book.created_at) ?? "—"],
  ];

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 p-4 sm:p-6">
      {book.status === EBookStatus.FAILED && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-md border border-danger-subtle bg-danger-subtle p-3"
        >
          <p className="flex-1 text-13 text-danger-primary">
            This book could not be processed: {book.failure_reason || "unknown error"}
          </p>
          {book.permissions.can_manage && (
            <Button
              variant="secondary"
              size="sm"
              stretch="auto"
              label="Process again"
              onClick={() =>
                void reprocessBook(workspaceSlug, book.id).catch((err) =>
                  setToast({
                    type: "error",
                    title: "Error!",
                    message: libraryErrorMessage(err, "The book could not be processed."),
                  })
                )
              }
            />
          )}
        </div>
      )}
      {processing && (
        <p role="status" className="rounded-md border border-subtle bg-layer-2 p-3 text-13 text-secondary">
          {STATUS_LABELS[book.status]}: the book will be ready in a moment.
        </p>
      )}
      <div className="flex flex-col gap-6 sm:flex-row">
        <div className="w-40 shrink-0 self-center sm:w-56 sm:self-start">
          <BookCover book={book} variant="full" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <h1 className="text-20 leading-tight font-semibold break-words text-primary">{bookTitle(book)}</h1>
              <p className="mt-1 text-14 text-secondary">{bookAuthors(book)}</p>
            </div>
            <BookActionsMenu
              workspaceSlug={workspaceSlug}
              book={book}
              onDeleted={() => router.push(`/${workspaceSlug}/library`)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-12 text-tertiary">
            {book.visibility === EBookVisibility.WORKSPACE ? (
              <span className="flex items-center gap-1">
                <GlobeOutline className="size-3.5" /> Shared with the workspace
              </span>
            ) : (
              <span className="flex items-center gap-1">
                <LockOutline className="size-3.5" /> Only you can see this book
              </span>
            )}
            {book.archived_at && <span>· Archived</span>}
          </div>
          <div className="flex flex-wrap gap-2">
            {book.format === "epub" && book.status === EBookStatus.READY && (
              <Link
                href={`/${workspaceSlug}/library/books/${book.id}/read`}
                className="inline-flex h-8 items-center rounded-md bg-accent-primary px-3 text-13 font-medium text-on-color hover:bg-accent-primary/90"
              >
                {book.my_reading?.status === EBookReadingStatus.READING
                  ? `Continue reading · ${Math.round(book.my_reading.progress)}%`
                  : book.my_reading?.status === EBookReadingStatus.COMPLETED
                    ? "Read again"
                    : "Read"}
              </Link>
            )}
            {book.permissions.can_download && book.status !== EBookStatus.UPLOADING && (
              <Button
                variant={book.format === "epub" && book.status === EBookStatus.READY ? "secondary" : "primary"}
                size="md"
                stretch="auto"
                label="Download"
                onClick={() =>
                  void downloadBook(workspaceSlug, book.id).catch((err) =>
                    setToast({
                      type: "error",
                      title: "Error!",
                      message: libraryErrorMessage(err, "The download failed."),
                    })
                  )
                }
              />
            )}
            {book.permissions.can_edit && (
              <Button
                variant="secondary"
                size="md"
                stretch="auto"
                label="Edit details"
                onClick={() => setIsEditOpen(true)}
              />
            )}
          </div>
          {book.tags.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label="Tags">
              {book.tags.map((tag) => (
                <li key={tag}>
                  <button
                    type="button"
                    className="rounded-full border border-subtle px-2 py-0.5 text-12 text-secondary hover:bg-layer-transparent-hover"
                    onClick={() => {
                      setFilters({ tag, collection: null, archived: false, visibility: null, search: "" });
                      router.push(`/${workspaceSlug}/library`);
                    }}
                  >
                    {tag}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {book.description && (
            <p className="text-13 leading-relaxed whitespace-pre-line text-secondary">{book.description}</p>
          )}
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
            {facts.map(([label, value]) => (
              <Fact key={label} label={label}>
                {value}
              </Fact>
            ))}
          </dl>
          {notes && notes.count > 0 && (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-12 text-secondary">
              <span>
                Your notes:{" "}
                {[
                  notes.counts.highlight && plural(notes.counts.highlight, "highlight"),
                  notes.counts.note && plural(notes.counts.note, "note"),
                  notes.counts.bookmark && plural(notes.counts.bookmark, "bookmark"),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              <Link
                href={`/${workspaceSlug}/library/notes?book=${book.id}`}
                className="text-accent-primary hover:underline"
              >
                See all
              </Link>
              <button
                type="button"
                className="text-accent-primary hover:underline"
                onClick={() => void notesService.exportAnnotations(workspaceSlug, book.id).catch(() => undefined)}
              >
                Export Markdown
              </button>
            </p>
          )}
          {book.subjects.length > 0 && <p className="text-12 text-tertiary">Subjects: {book.subjects.join(" · ")}</p>}
        </div>
      </div>
      {book.toc && book.toc.length > 0 && (
        <section aria-labelledby="book-toc" className="flex flex-col gap-3">
          <h2 id="book-toc" className="text-14 font-semibold text-primary">
            Contents
          </h2>
          <TocList entries={book.toc} />
        </section>
      )}
      {isEditOpen && (
        <BookEditModal workspaceSlug={workspaceSlug} book={book as TBook} isOpen onClose={() => setIsEditOpen(false)} />
      )}
    </div>
  );
});
