/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import {
  AddOutline,
  ArchiveOutline,
  BookClosedOutline,
  ChatOutline,
  EditOutline,
  GlobeOutline,
  LibraryOutline,
  LockOutline,
  MoreHorizontalOutline,
  DeleteOutline,
} from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import type { TBookCollection, TBookFilters } from "@plane/types";
import { EBookVisibility } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useLibrary } from "@/hooks/store/use-library";
import { libraryErrorMessage } from "@/store/library.store";
// local imports
import { BookCollectionFormModal } from "./collection-modals";

type Shelf = { key: string; label: string; icon: typeof LibraryOutline; filters: Partial<TBookFilters> };

const SHELVES: Shelf[] = [
  { key: "all", label: "All books", icon: LibraryOutline, filters: {} },
  { key: "personal", label: "Only me", icon: LockOutline, filters: { visibility: EBookVisibility.PERSONAL } },
  {
    key: "workspace",
    label: "Shared with workspace",
    icon: GlobeOutline,
    filters: { visibility: EBookVisibility.WORKSPACE },
  },
  { key: "archived", label: "Archived", icon: ArchiveOutline, filters: { archived: true } },
];

const SHELF_RESET: Partial<TBookFilters> = { visibility: null, archived: false, collection: null };

type Props = { workspaceSlug: string };

export const LibraryNav = observer(function LibraryNav({ workspaceSlug }: Props) {
  const { filters, setFilters, collectionIds, collections, deleteCollection } = useLibrary();
  const [editing, setEditing] = useState<TBookCollection | "new" | null>(null);
  const [deleting, setDeleting] = useState<TBookCollection | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const activeShelf = filters.collection
    ? null
    : filters.archived
      ? "archived"
      : filters.visibility === EBookVisibility.PERSONAL
        ? "personal"
        : filters.visibility === EBookVisibility.WORKSPACE
          ? "workspace"
          : "all";

  const item = (active: boolean) =>
    cn(
      "flex w-full shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-13 whitespace-nowrap text-secondary hover:bg-layer-transparent-hover md:whitespace-normal",
      { "bg-layer-transparent-active font-medium text-primary": active }
    );

  return (
    <nav aria-label="Library shelves" className="flex flex-col gap-4">
      <ul className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
        {SHELVES.map((shelf) => (
          <li key={shelf.key} className="shrink-0">
            <button
              type="button"
              className={item(activeShelf === shelf.key)}
              aria-current={activeShelf === shelf.key ? "page" : undefined}
              onClick={() => setFilters({ ...SHELF_RESET, ...shelf.filters })}
            >
              <shelf.icon className="size-4 shrink-0" />
              {shelf.label}
            </button>
          </li>
        ))}
      </ul>
      <Link href={`/${workspaceSlug}/library/notes`} className={item(false)}>
        <ChatOutline className="size-4 shrink-0" />
        Notes & highlights
      </Link>
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between px-2">
          <span className="text-11 font-semibold tracking-wide text-tertiary uppercase">Collections</span>
          <IconButton
            variant="ghost"
            size="sm"
            aria-label="New collection"
            icon={<Icon icon={AddOutline} />}
            onClick={() => setEditing("new")}
          />
        </div>
        {collectionIds.length === 0 && <p className="px-2 text-12 text-placeholder">Group books into collections.</p>}
        <ul className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
          {collectionIds.map((id) => {
            const collection = collections[id];
            if (!collection) return null;
            const active = filters.collection === id;
            return (
              <li key={id} className="group flex shrink-0 items-center">
                <button
                  type="button"
                  className={item(active)}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setFilters({ ...SHELF_RESET, collection: id })}
                >
                  <BookClosedOutline className="size-4 shrink-0" />
                  <span className="truncate">{collection.name}</span>
                  {collection.visibility === EBookVisibility.WORKSPACE && (
                    <GlobeOutline className="size-3 shrink-0 text-placeholder" aria-label="Shared" />
                  )}
                  <span className="ml-auto text-11 text-placeholder">{collection.book_count}</span>
                </button>
                {collection.permissions.can_edit && (
                  <span className="shrink-0 md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
                    <Menu>
                      <MenuTrigger
                        render={
                          <IconButton
                            variant="ghost"
                            size="sm"
                            aria-label={`Actions for ${collection.name}`}
                            icon={<Icon icon={MoreHorizontalOutline} />}
                          />
                        }
                      />
                      <MenuContent side="bottom" align="end">
                        <MenuItem
                          label="Edit"
                          icon={<Icon icon={EditOutline} />}
                          onClick={() => setEditing(collection)}
                        />
                        <MenuItem
                          label="Delete"
                          icon={<Icon icon={DeleteOutline} />}
                          onClick={() => setDeleting(collection)}
                        />
                      </MenuContent>
                    </Menu>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </div>
      <BookCollectionFormModal
        workspaceSlug={workspaceSlug}
        isOpen={editing !== null}
        collection={editing && editing !== "new" ? editing : undefined}
        onClose={() => setEditing(null)}
        onSaved={(collection) => setFilters({ ...SHELF_RESET, collection: collection.id })}
      />
      <ConfirmDialog
        isOpen={!!deleting}
        handleClose={() => setDeleting(null)}
        handleSubmit={async () => {
          if (!deleting) return;
          setIsDeleting(true);
          try {
            await deleteCollection(workspaceSlug, deleting.id);
            setDeleting(null);
          } catch (error) {
            setToast({
              type: "error",
              title: "Error!",
              message: libraryErrorMessage(error, "The collection could not be deleted."),
            });
          } finally {
            setIsDeleting(false);
          }
        }}
        isSubmitting={isDeleting}
        title="Delete collection"
        content={
          <>
            Delete the collection <span className="font-medium text-primary">{deleting?.name}</span>? The books stay in
            the library.
          </>
        }
      />
    </nav>
  );
});
