/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { InputField } from "@makeplane/propel/components/input-field";
import { TextAreaField } from "@makeplane/propel/components/text-area-field";
import type { TBook, TBookPassage, TWikiPageFromBookResponse, TWikiSpace, TWikiTreeNode } from "@plane/types";
import { EBookVisibility, EWikiSpaceRole } from "@plane/types";
// hooks
import { useInstance } from "@/hooks/store/use-instance";
// services
import { LibraryService } from "@/services/library.service";
import { WikiSpaceService } from "@/services/page/wiki-space.service";
import { libraryErrorMessage } from "@/store/library.store";
// local imports
import { bookTitle } from "./utils";

const libraryService = new LibraryService();
const spaceService = new WikiSpaceService();

type Props = {
  workspaceSlug: string;
  book: TBook;
  passages: TBookPassage[];
  chapterTitle: (index: number) => string;
  isOpen: boolean;
  onClose: () => void;
};

/** Cut a quote to `limit` characters at a word boundary. The start of a quote is still a passage
 *  of the book, so the server's check that quotes come from the book still holds. */
const shorten = (quote: string, limit: number) => {
  if (quote.length <= limit) return quote;
  const cut = quote.slice(0, limit);
  const space = cut.lastIndexOf(" ");
  return (space > limit * 0.6 ? cut.slice(0, space) : cut).trimEnd();
};

/** Flatten the space tree into options, children indented under their parents. */
const treeOptions = (nodes: TWikiTreeNode[]) => {
  const children = new Map<string | null, TWikiTreeNode[]>();
  for (const node of nodes) children.set(node.parent, [...(children.get(node.parent) ?? []), node]);
  const result: { id: string; label: string }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const node of children.get(parent) ?? []) {
      result.push({ id: node.id, label: `${"  ".repeat(depth)}${node.name || "Untitled"}` });
      if (depth < 8) walk(node.id, depth + 1);
    }
  };
  walk(null, 0);
  return result;
};

/**
 * Create a wiki page from passages and notes of a book. The page is private unless the reader
 * chooses to share it with the space, which needs an explicit confirmation; quotes are limited to
 * the instance's excerpt limits (and checked again by the server).
 */
export const WikiPageFromBookModal = observer(function WikiPageFromBookModal(props: Props) {
  const { workspaceSlug, book, passages, chapterTitle, isOpen, onClose } = props;
  const { config } = useInstance();
  const limit = config?.book_excerpt_limit ?? 1500;
  const pageLimit = config?.book_excerpt_page_limit ?? 10000;
  const [spaces, setSpaces] = useState<TWikiSpace[] | undefined>();
  const [spaceId, setSpaceId] = useState("");
  const [tree, setTree] = useState<TWikiTreeNode[]>([]);
  const [parentId, setParentId] = useState("");
  const [title, setTitle] = useState("");
  const [intro, setIntro] = useState("");
  const [included, setIncluded] = useState<boolean[]>([]);
  const [share, setShare] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [created, setCreated] = useState<TWikiPageFromBookResponse | undefined>();

  useEffect(() => {
    if (!isOpen) return;
    setTitle(`Notes on ${bookTitle(book)}`);
    setIntro("");
    setIncluded(passages.map(() => true));
    setShare(false);
    setConfirmed(false);
    setError(undefined);
    setCreated(undefined);
    setParentId("");
    spaceService
      .fetchAll(workspaceSlug)
      .then((all) => {
        const writable = all.filter((s) => (s.my_role ?? 0) >= EWikiSpaceRole.EDITOR);
        setSpaces(writable);
        setSpaceId((writable.find((s) => s.is_default) ?? writable[0])?.id ?? "");
        return writable;
      })
      .catch(() => setSpaces([]));
  }, [isOpen, workspaceSlug, book, passages]);

  useEffect(() => {
    setParentId("");
    setTree([]);
    if (!isOpen || !spaceId) return;
    spaceService
      .fetchTree(workspaceSlug, spaceId)
      .then(setTree)
      .catch(() => setTree([]));
  }, [isOpen, workspaceSlug, spaceId]);

  const prepared = useMemo(
    () => passages.map((p) => ({ ...p, quote: shorten(p.quote.trim(), limit) })),
    [passages, limit]
  );
  const chosen = prepared.filter((_, index) => included[index]);
  const shortened = passages.filter((p, index) => included[index] && p.quote.trim().length > limit).length;
  const quoted = chosen.reduce((total, p) => total + p.quote.length, 0);
  const tooMuch = quoted > pageLimit;
  const space = spaces?.find((s) => s.id === spaceId);
  const parents = useMemo(() => treeOptions(tree), [tree]);
  const canSubmit = !!spaceId && chosen.length > 0 && !tooMuch && (!share || confirmed) && !isSubmitting;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setIsSubmitting(true);
    setError(undefined);
    try {
      const response = await libraryService.createWikiPage(workspaceSlug, book.id, {
        space: spaceId,
        parent: parentId || null,
        title: title.trim(),
        intro,
        passages: chosen,
        share,
        confirm_excerpts: share && confirmed,
      });
      setCreated(response);
    } catch (err) {
      setError(libraryErrorMessage(err, "The page could not be created."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="lg">
        {created ? (
          <>
            <DialogMain>
              <DialogHeader>
                <DialogHeading>
                  <DialogTitle>Wiki page created</DialogTitle>
                </DialogHeading>
              </DialogHeader>
              <DialogBody>
                <p className="text-13 text-secondary" role="status">
                  “{created.page.name}” is in {space?.name ?? "the wiki"}
                  {share ? ", shared with everyone in the space." : ". Only you can see it."} It links back to the
                  passages in the book.
                </p>
              </DialogBody>
            </DialogMain>
            <DialogActions>
              <Button stretch="auto" variant="secondary" size="md" label="Close" onClick={onClose} type="button" />
              <Link
                href={`/${workspaceSlug}/wiki/${created.page.id}`}
                className="inline-flex h-8 items-center rounded-md bg-accent-primary px-3 text-13 font-medium text-on-color"
              >
                Open page
              </Link>
            </DialogActions>
          </>
        ) : (
          <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
            <DialogMain>
              <DialogHeader>
                <DialogHeading>
                  <DialogTitle>Create wiki page</DialogTitle>
                </DialogHeading>
              </DialogHeader>
              <DialogBody>
                <div className="flex flex-col gap-4">
                  <InputField
                    id="wiki-page-title"
                    label="Title"
                    size="md"
                    orientation="vertical"
                    value={title}
                    maxLength={255}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <label className="flex flex-col gap-1 text-13 text-secondary">
                      <span className="font-medium">Space</span>
                      <select
                        aria-label="Space"
                        value={spaceId}
                        onChange={(e) => setSpaceId(e.target.value)}
                        disabled={!spaces?.length}
                        className="h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-primary"
                      >
                        {spaces === undefined && <option value="">Loading…</option>}
                        {spaces?.length === 0 && <option value="">No space you can write in</option>}
                        {spaces?.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-13 text-secondary">
                      <span className="font-medium">Under</span>
                      <select
                        aria-label="Under"
                        value={parentId}
                        onChange={(e) => setParentId(e.target.value)}
                        className="h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-primary"
                      >
                        <option value="">Top of the space</option>
                        {parents.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <TextAreaField
                    id="wiki-page-intro"
                    label="Introduction"
                    size="lg"
                    resize="vertical"
                    autoResize
                    maxRows={6}
                    placeholder="Optional: why these passages matter"
                    value={intro}
                    maxLength={10000}
                    onChange={(e) => setIntro(e.target.value)}
                  />
                  <fieldset className="flex flex-col gap-2">
                    <legend className="mb-1 text-13 font-medium text-secondary">
                      {passages.length === 1 ? "Passage" : `Passages (${chosen.length} of ${passages.length})`}
                    </legend>
                    <ul className="flex max-h-56 flex-col gap-2 overflow-y-auto" aria-label="Passages">
                      {prepared.map((p, index) => (
                        <li
                          key={`${p.chapter}:${p.start_offset}:${p.quote.slice(0, 24)}:${p.note.slice(0, 24)}`}
                          className="flex gap-2 rounded-md border border-subtle p-2"
                        >
                          {passages.length > 1 && (
                            <input
                              type="checkbox"
                              aria-label={`Include passage ${index + 1}`}
                              checked={!!included[index]}
                              onChange={(e) =>
                                setIncluded((current) => current.map((v, i) => (i === index ? e.target.checked : v)))
                              }
                              className="mt-1"
                            />
                          )}
                          <span className="flex min-w-0 flex-col gap-0.5">
                            <span className="text-11 text-tertiary">{chapterTitle(p.chapter)}</span>
                            {p.quote && <span className="line-clamp-3 text-12 text-secondary italic">“{p.quote}”</span>}
                            {p.note && <span className="line-clamp-2 text-12 text-primary">{p.note}</span>}
                          </span>
                        </li>
                      ))}
                    </ul>
                    <p className={tooMuch ? "text-12 text-danger-primary" : "text-12 text-tertiary"}>
                      {quoted.toLocaleString()} of at most {pageLimit.toLocaleString()} quoted characters
                      {tooMuch && ". Leave some passages out, or make more than one page."}
                      {shortened > 0 &&
                        ` · ${shortened === 1 ? "1 quote was" : `${shortened} quotes were`} shortened to ${limit.toLocaleString()} characters`}
                    </p>
                  </fieldset>
                  <fieldset className="flex flex-col gap-2">
                    <legend className="mb-1 text-13 font-medium text-secondary">Who can see the page</legend>
                    <label className="flex items-center gap-2 text-13 text-primary">
                      <input type="radio" name="wiki-page-share" checked={!share} onChange={() => setShare(false)} />
                      Only me (a private page)
                    </label>
                    <label className="flex items-center gap-2 text-13 text-primary">
                      <input type="radio" name="wiki-page-share" checked={share} onChange={() => setShare(true)} />
                      Everyone in {space?.name ?? "the space"}
                    </label>
                    {share && (
                      <div className="flex flex-col gap-2 rounded-md border border-warning-subtle bg-warning-subtle p-3 text-12 text-secondary">
                        <p>
                          This page will quote {quoted.toLocaleString()} characters of “{bookTitle(book)}”. Books are
                          usually protected by copyright: only share excerpts you are allowed to share.
                        </p>
                        {book.visibility === EBookVisibility.PERSONAL && (
                          <p>
                            The book is in your personal library, so others will see the excerpts but cannot open the
                            book.
                          </p>
                        )}
                        <label className="flex items-start gap-2 text-primary">
                          <input
                            type="checkbox"
                            checked={confirmed}
                            onChange={(e) => setConfirmed(e.target.checked)}
                            className="mt-0.5"
                          />
                          I may share these excerpts with everyone in {space?.name ?? "the space"}
                        </label>
                      </div>
                    )}
                  </fieldset>
                  {error && (
                    <p role="alert" className="text-13 text-danger-primary">
                      {error}
                    </p>
                  )}
                </div>
              </DialogBody>
            </DialogMain>
            <DialogActions>
              <Button stretch="auto" variant="secondary" size="md" label="Cancel" onClick={onClose} type="button" />
              <Button
                stretch="auto"
                variant="primary"
                size="md"
                type="submit"
                label={isSubmitting ? "Creating…" : "Create page"}
                disabled={!canSubmit}
              />
            </DialogActions>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
});
