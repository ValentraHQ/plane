/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { observer } from "mobx-react";
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
import { GlobeOutline, LockOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import type { TBook, TBookCollection } from "@plane/types";
import { EBookVisibility } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useLibrary } from "@/hooks/store/use-library";
import { useUser } from "@/hooks/store/user";
import { libraryErrorMessage } from "@/store/library.store";

const VISIBILITY_OPTIONS = [
  {
    value: EBookVisibility.PERSONAL,
    label: "Only me",
    description: "A private shelf. It can hold your personal books and workspace books.",
  },
  {
    value: EBookVisibility.WORKSPACE,
    label: "Workspace",
    description: "Every workspace member can see it. It holds workspace books only.",
  },
];

type FormProps = {
  workspaceSlug: string;
  isOpen: boolean;
  onClose: () => void;
  collection?: TBookCollection;
  onSaved?: (collection: TBookCollection) => void;
};

export const BookCollectionFormModal = observer(function BookCollectionFormModal(props: FormProps) {
  const { workspaceSlug, isOpen, onClose, collection, onSaved } = props;
  const { createCollection, updateCollection } = useLibrary();
  const { data: currentUser } = useUser();
  const currentUserId = currentUser?.id;
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<EBookVisibility>(EBookVisibility.PERSONAL);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setName(collection?.name ?? "");
    setDescription(collection?.description ?? "");
    setVisibility(collection?.visibility ?? EBookVisibility.PERSONAL);
  }, [collection, isOpen]);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      const data = { name, description, visibility };
      const saved = collection
        ? await updateCollection(workspaceSlug, collection.id, data)
        : await createCollection(workspaceSlug, data);
      onSaved?.(saved);
      onClose();
    } catch (error) {
      setToast({
        type: "error",
        title: "Error!",
        message: libraryErrorMessage(error, "The collection could not be saved."),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="md">
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <DialogMain>
            <DialogHeader>
              <DialogHeading>
                <DialogTitle>{collection ? "Collection settings" : "New collection"}</DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody>
              <div className="flex flex-col gap-4">
                <InputField
                  id="collection-name"
                  label="Name"
                  size="md"
                  orientation="vertical"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Regulations"
                  required
                />
                <InputField
                  id="collection-description"
                  label="Description"
                  size="md"
                  orientation="vertical"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
                <fieldset className="flex flex-col gap-2">
                  <legend className="mb-1.5 text-13 text-secondary">Who can see it</legend>
                  {VISIBILITY_OPTIONS.map((option) => (
                    <label
                      key={option.value}
                      htmlFor={`collection-visibility-${option.value}`}
                      aria-label={`${option.label}: ${option.description}`}
                      className={cn(
                        "flex cursor-pointer items-start gap-2 rounded-md border border-subtle p-2.5 hover:bg-layer-transparent-hover",
                        { "border-accent-strong": visibility === option.value }
                      )}
                    >
                      <input
                        id={`collection-visibility-${option.value}`}
                        type="radio"
                        name="collection-visibility"
                        className="mt-0.5"
                        checked={visibility === option.value}
                        onChange={() => setVisibility(option.value)}
                        // only the owner decides who can see an existing collection
                        disabled={!!collection && collection.owner !== currentUserId}
                      />
                      <span className="flex flex-col">
                        <span className="text-13 font-medium text-primary">{option.label}</span>
                        <span className="text-12 text-tertiary">{option.description}</span>
                      </span>
                    </label>
                  ))}
                </fieldset>
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
              label={isSubmitting ? "Saving…" : collection ? "Save" : "Create"}
              disabled={isSubmitting || !name.trim()}
            />
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
});

type AddProps = {
  workspaceSlug: string;
  book: TBook;
  isOpen: boolean;
  onClose: () => void;
};

/** Put a book on (or take it off) collections the user can change. */
export const AddToCollectionModal = observer(function AddToCollectionModal(props: AddProps) {
  const { workspaceSlug, book, isOpen, onClose } = props;
  const { collectionIds, collections, fetchCollections, fetchBook, addToCollection, removeFromCollection } =
    useLibrary();
  const [memberOf, setMemberOf] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    void fetchCollections(workspaceSlug);
    // collection membership comes with the book detail
    fetchBook(workspaceSlug, book.id)
      .then((detail) => setMemberOf(new Set(detail.collection_ids ?? [])))
      .catch(() => undefined);
  }, [book.id, fetchBook, fetchCollections, isOpen, workspaceSlug]);

  const editable = collectionIds.map((id) => collections[id]).filter((c) => c?.permissions.can_edit);

  const toggle = async (collection: TBookCollection) => {
    setBusy(collection.id);
    try {
      if (memberOf.has(collection.id)) {
        await removeFromCollection(workspaceSlug, collection.id, book.id);
        setMemberOf((current) => new Set([...current].filter((id) => id !== collection.id)));
      } else {
        await addToCollection(workspaceSlug, collection.id, [book.id]);
        setMemberOf((current) => new Set([...current, collection.id]));
      }
    } catch (error) {
      setToast({
        type: "error",
        title: "Error!",
        message: libraryErrorMessage(error, "The collection could not be changed."),
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Dialog open={isOpen && !isCreateOpen} onOpenChange={(open) => !open && onClose()}>
        <DialogContent size="sm">
          <DialogMain>
            <DialogHeader>
              <DialogHeading>
                <DialogTitle>Collections</DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody>
              {editable.length === 0 ? (
                <p className="text-13 text-tertiary">You have no collections yet.</p>
              ) : (
                <ul className="flex flex-col gap-1" aria-label="Collections">
                  {editable.map((collection) => {
                    const shared = collection.visibility === EBookVisibility.WORKSPACE;
                    const blocked = shared && book.visibility === EBookVisibility.PERSONAL;
                    return (
                      <li key={collection.id}>
                        <label
                          className={cn(
                            "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-layer-transparent-hover",
                            { "cursor-not-allowed opacity-60": blocked }
                          )}
                          title={blocked ? "Share the book with the workspace to add it to a shared collection." : ""}
                        >
                          <input
                            type="checkbox"
                            checked={memberOf.has(collection.id)}
                            disabled={blocked || busy === collection.id}
                            onChange={() => void toggle(collection)}
                          />
                          {shared ? (
                            <GlobeOutline className="size-3.5 text-tertiary" aria-label="Shared with the workspace" />
                          ) : (
                            <LockOutline className="size-3.5 text-tertiary" aria-label="Only you" />
                          )}
                          <span className="truncate text-13 text-primary">{collection.name}</span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
            </DialogBody>
          </DialogMain>
          <DialogActions>
            <Button
              stretch="auto"
              variant="secondary"
              size="md"
              label="New collection"
              onClick={() => setIsCreateOpen(true)}
            />
            <Button stretch="auto" variant="primary" size="md" label="Done" onClick={onClose} />
          </DialogActions>
        </DialogContent>
      </Dialog>
      <BookCollectionFormModal
        workspaceSlug={workspaceSlug}
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onSaved={(collection) => void toggle(collection)}
      />
    </>
  );
});
