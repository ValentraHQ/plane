/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { setToast } from "@plane/blocks/toast";
import type { TBook, TBookLink, TBookLinkTarget, TBookLinkTargetType } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useInstance } from "@/hooks/store/use-instance";
// services
import { LibraryService } from "@/services/library.service";
import { DEFAULT_BOOK_FILTERS, libraryErrorMessage } from "@/store/library.store";
// local imports
import { BookCover } from "./book-cover";
import { bookAuthors, bookTitle } from "./utils";

const service = new LibraryService();

const TYPE_LABELS: Record<TBookLinkTargetType, string> = { issue: "Work item", project: "Project", page: "Page" };
const GROUP_LABELS: Record<TBookLinkTargetType, string> = { page: "Pages", issue: "Work items", project: "Projects" };

export const targetHref = (slug: string, type: TBookLinkTargetType, target: TBookLinkTarget) => {
  if (type === "issue") return `/${slug}/browse/${target.project_identifier}-${target.sequence_id}/`;
  if (type === "project") return `/${slug}/projects/${target.id}/issues`;
  return target.space_id ? `/${slug}/wiki/${target.id}` : `/${slug}/projects/${target.project_id}/pages/${target.id}`;
};

const targetLabel = (type: TBookLinkTargetType, target: TBookLinkTarget) =>
  type === "issue" ? `${target.project_identifier}-${target.sequence_id} ${target.name}` : target.name;

/** Debounced search results for a picker. */
function useSearch<T>(enabled: boolean, query: string, search: (query: string) => Promise<T[]>, deps: unknown[]) {
  const [results, setResults] = useState<T[] | undefined>();
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      search(query)
        .then((found) => !cancelled && setResults(found))
        .catch(() => !cancelled && setResults([]));
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `search` is rebuilt every render
  }, [enabled, query, ...deps]);
  return results;
}

function PickerDialog(props: {
  title: string;
  isOpen: boolean;
  onClose: () => void;
  query: string;
  onQuery: (query: string) => void;
  placeholder: string;
  children: React.ReactNode;
  filters?: React.ReactNode;
}) {
  const { title, isOpen, onClose, query, onQuery, placeholder, children, filters } = props;
  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="md">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>{title}</DialogTitle>
            </DialogHeading>
          </DialogHeader>
          <DialogBody>
            <div className="flex flex-col gap-3">
              {filters}
              <input
                type="search"
                aria-label="Search"
                value={query}
                onChange={(e) => onQuery(e.target.value)}
                placeholder={placeholder}
                className="h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-primary placeholder:text-placeholder"
              />
              {children}
            </div>
          </DialogBody>
        </DialogMain>
      </DialogContent>
    </Dialog>
  );
}

// --- on the book page ---

function LinkTargetPicker(props: {
  workspaceSlug: string;
  isOpen: boolean;
  onClose: () => void;
  onPick: (type: TBookLinkTargetType, target: TBookLinkTarget) => void;
}) {
  const { workspaceSlug, isOpen, onClose, onPick } = props;
  const [type, setType] = useState<TBookLinkTargetType>("issue");
  const [query, setQuery] = useState("");
  const results = useSearch(isOpen, query, (q) => service.searchLinkTargets(workspaceSlug, type, q), [
    type,
    workspaceSlug,
  ]);
  return (
    <PickerDialog
      title="Link this book"
      isOpen={isOpen}
      onClose={onClose}
      query={query}
      onQuery={setQuery}
      placeholder={type === "issue" ? "Search work items, or type an ID like WEB-12" : "Search by name"}
      filters={
        <div role="group" aria-label="Link to" className="flex gap-1">
          {(["issue", "project", "page"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={type === value}
              onClick={() => setType(value)}
              className={cn("rounded-md px-2 py-1 text-12 text-secondary hover:bg-layer-transparent-hover", {
                "bg-layer-transparent-active font-medium text-primary": type === value,
              })}
            >
              {TYPE_LABELS[value]}
            </button>
          ))}
        </div>
      }
    >
      <ul className="flex max-h-72 flex-col overflow-y-auto" aria-label="Results">
        {results?.length === 0 && <li className="p-2 text-13 text-tertiary">Nothing found.</li>}
        {results?.map((target) => (
          <li key={target.id}>
            <button
              type="button"
              onClick={() => onPick(type, target)}
              className="w-full truncate rounded-md p-2 text-left text-13 text-primary hover:bg-layer-transparent-hover"
            >
              {targetLabel(type, target)}
            </button>
          </li>
        ))}
      </ul>
    </PickerDialog>
  );
}

/** Pages made from the book, and the pages, projects and work items it is linked to. */
export const BookLinks = observer(function BookLinks({ workspaceSlug, book }: { workspaceSlug: string; book: TBook }) {
  const { data: links, mutate } = useSWR(`BOOK_LINKS_${book.id}`, () => service.listBookLinks(workspaceSlug, book.id));
  const [isPicking, setIsPicking] = useState(false);

  const add = async (type: TBookLinkTargetType, target: TBookLinkTarget) => {
    setIsPicking(false);
    try {
      await service.createBookLink(workspaceSlug, book.id, type, target.id);
      await mutate();
    } catch (error) {
      setToast({ type: "error", title: "Not linked", message: libraryErrorMessage(error, "The link failed.") });
    }
  };
  const remove = async (link: TBookLink) => {
    try {
      await service.deleteBookLink(workspaceSlug, link.id);
      await mutate();
    } catch (error) {
      setToast({ type: "error", title: "Not removed", message: libraryErrorMessage(error, "The link stays.") });
    }
  };

  const groups = (["page", "issue", "project"] as const)
    .map((type) => ({ type, items: (links ?? []).filter((l) => l.target_type === type) }))
    .filter((g) => g.items.length > 0);

  return (
    <section aria-labelledby="book-links" className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 id="book-links" className="text-14 font-semibold text-primary">
          Linked
        </h2>
        <Button stretch="auto" variant="secondary" size="sm" label="Link…" onClick={() => setIsPicking(true)} />
      </div>
      {links && links.length === 0 && (
        <p className="text-13 text-tertiary">
          Link this book to work items, projects or pages, or create a wiki page from its passages in the reader.
        </p>
      )}
      {groups.map(({ type, items }) => (
        <div key={type} className="flex flex-col gap-1">
          <h3 className="text-11 font-semibold tracking-wide text-tertiary uppercase">{GROUP_LABELS[type]}</h3>
          <ul className="flex flex-col gap-1" aria-label={GROUP_LABELS[type]}>
            {items.map((link) => (
              <li key={link.id} className="group flex items-center gap-2 text-13">
                <Link
                  href={targetHref(workspaceSlug, type, link.target)}
                  className="truncate text-primary hover:underline"
                >
                  {targetLabel(type, link.target)}
                </Link>
                {link.origin === "created" && (
                  <span className="shrink-0 text-11 text-tertiary">
                    created from the book
                    {link.chapter !== null && (
                      <>
                        {" · "}
                        <Link
                          href={`/${workspaceSlug}/library/books/${book.id}/read?chapter=${link.chapter}&offset=${link.start_offset ?? 0}`}
                          className="text-accent-primary hover:underline"
                        >
                          passage
                        </Link>
                      </>
                    )}
                  </span>
                )}
                {link.permissions.can_delete && (
                  <button
                    type="button"
                    aria-label={`Remove link to ${targetLabel(type, link.target)}`}
                    onClick={() => void remove(link)}
                    className="ml-auto shrink-0 rounded-md px-1.5 text-12 text-tertiary hover:bg-layer-transparent-hover hover:text-danger-primary"
                  >
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <LinkTargetPicker
        workspaceSlug={workspaceSlug}
        isOpen={isPicking}
        onClose={() => setIsPicking(false)}
        onPick={(type, target) => void add(type, target)}
      />
    </section>
  );
});

// --- on a work item ---

/** Books linked to a work item, for people who can see them; hidden when the library is off. */
export const WorkItemBooks = observer(function WorkItemBooks(props: {
  workspaceSlug: string;
  issueId: string;
  disabled: boolean;
}) {
  const { workspaceSlug, issueId, disabled } = props;
  const { config } = useInstance();
  const enabled = !!config?.is_library_enabled;
  const {
    data: links,
    error,
    mutate,
  } = useSWR(enabled ? `WORK_ITEM_BOOKS_${issueId}` : null, () =>
    service.listLinkedBooks(workspaceSlug, "issue", issueId)
  );
  const [isPicking, setIsPicking] = useState(false);
  const [query, setQuery] = useState("");
  const books = useSearch<TBook>(
    isPicking,
    query,
    (q) =>
      service
        .listBooks(workspaceSlug, { ...DEFAULT_BOOK_FILTERS, search: q, order_by: "title" }, 0, 20)
        .then((r) => r.results),
    [workspaceSlug]
  );

  // guests have no library: nothing to show
  if (!enabled || error || !links) return null;
  if (links.length === 0 && disabled) return null;

  const link = async (book: TBook) => {
    setIsPicking(false);
    try {
      await service.createBookLink(workspaceSlug, book.id, "issue", issueId);
      await mutate();
    } catch (err) {
      setToast({ type: "error", title: "Not linked", message: libraryErrorMessage(err, "The link failed.") });
    }
  };
  const unlink = async (item: TBookLink) => {
    try {
      await service.deleteBookLink(workspaceSlug, item.id);
      await mutate();
    } catch (err) {
      setToast({ type: "error", title: "Not removed", message: libraryErrorMessage(err, "The link stays.") });
    }
  };

  return (
    <section aria-label="Books" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-14 font-medium text-primary">Books</h3>
        {!disabled && (
          <Button stretch="auto" variant="ghost" size="sm" label="Link a book" onClick={() => setIsPicking(true)} />
        )}
      </div>
      {links.length > 0 && (
        <ul className="flex flex-col gap-1" aria-label="Linked books">
          {links.map((item) =>
            item.book_detail ? (
              <li key={item.id} className="flex items-center gap-3 rounded-md p-1.5 hover:bg-layer-transparent-hover">
                <Link
                  href={`/${workspaceSlug}/library/books/${item.book}`}
                  className="flex min-w-0 flex-1 items-center gap-3"
                >
                  <div className="w-8 shrink-0">
                    <BookCover book={item.book_detail} />
                  </div>
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-13 text-primary">{bookTitle(item.book_detail)}</span>
                    <span className="truncate text-11 text-tertiary">{bookAuthors(item.book_detail)}</span>
                  </span>
                </Link>
                {item.permissions.can_delete && !disabled && (
                  <button
                    type="button"
                    aria-label={`Unlink ${bookTitle(item.book_detail)}`}
                    onClick={() => void unlink(item)}
                    className="shrink-0 rounded-md px-1.5 text-12 text-tertiary hover:text-danger-primary"
                  >
                    Unlink
                  </button>
                )}
              </li>
            ) : null
          )}
        </ul>
      )}
      <PickerDialog
        title="Link a book"
        isOpen={isPicking}
        onClose={() => setIsPicking(false)}
        query={query}
        onQuery={setQuery}
        placeholder="Search by title, author or tag"
      >
        <ul className="flex max-h-72 flex-col overflow-y-auto" aria-label="Results">
          {books?.length === 0 && <li className="p-2 text-13 text-tertiary">No books found.</li>}
          {books?.map((book) => (
            <li key={book.id}>
              <button
                type="button"
                onClick={() => void link(book)}
                className="flex w-full flex-col rounded-md p-2 text-left hover:bg-layer-transparent-hover"
              >
                <span className="truncate text-13 text-primary">{bookTitle(book)}</span>
                <span className="truncate text-11 text-tertiary">{bookAuthors(book)}</span>
              </button>
            </li>
          ))}
        </ul>
      </PickerDialog>
    </section>
  );
});
