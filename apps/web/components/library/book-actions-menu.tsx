/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import {
  ArchiveOutline,
  DownloadOutline,
  EditOutline,
  GlobeOutline,
  LibraryOutline,
  LockOutline,
  MoreHorizontalOutline,
  RefreshOutline,
  RestoreOutline,
  DeleteOutline,
} from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import type { TBook } from "@plane/types";
import { EBookStatus, EBookVisibility } from "@plane/types";
// hooks
import { useLibrary } from "@/hooks/store/use-library";
import { useUser } from "@/hooks/store/user";
import { libraryErrorMessage } from "@/store/library.store";
// local imports
import { BookEditModal } from "./book-edit-modal";
import { AddToCollectionModal } from "./collection-modals";
import { bookTitle } from "./utils";

type Props = {
  workspaceSlug: string;
  book: TBook;
  /** called after the book was deleted (e.g. to leave its detail page) */
  onDeleted?: () => void;
};

export const BookActionsMenu = observer(function BookActionsMenu(props: Props) {
  const { workspaceSlug, book, onDeleted } = props;
  const { updateBook, deleteBook, reprocessBook, downloadBook } = useLibrary();
  const { data: currentUser } = useUser();
  const [modal, setModal] = useState<"edit" | "collections" | "delete" | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const { permissions } = book;
  const isOwner = currentUser?.id === book.owner;
  const isUploaded = book.status !== EBookStatus.UPLOADING;

  const run = async (action: () => Promise<unknown>, success: string, failure: string) => {
    try {
      await action();
      setToast({ type: "success", title: "Done", message: success });
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: libraryErrorMessage(error, failure) });
    }
  };

  const shareTarget =
    book.visibility === EBookVisibility.PERSONAL ? EBookVisibility.WORKSPACE : EBookVisibility.PERSONAL;

  return (
    <>
      <Menu>
        <MenuTrigger
          render={
            <IconButton
              variant="ghost"
              size="sm"
              aria-label={`Actions for ${bookTitle(book)}`}
              icon={<Icon icon={MoreHorizontalOutline} />}
            />
          }
        />
        <MenuContent side="bottom" align="end">
          {permissions.can_download && isUploaded && (
            <MenuItem
              label="Download"
              icon={<Icon icon={DownloadOutline} />}
              onClick={() =>
                void downloadBook(workspaceSlug, book.id).catch((error) =>
                  setToast({
                    type: "error",
                    title: "Error!",
                    message: libraryErrorMessage(error, "The download failed."),
                  })
                )
              }
            />
          )}
          {permissions.can_edit && (
            <MenuItem label="Edit details" icon={<Icon icon={EditOutline} />} onClick={() => setModal("edit")} />
          )}
          <MenuItem
            label="Collections…"
            icon={<Icon icon={LibraryOutline} />}
            onClick={() => setModal("collections")}
          />
          {isOwner && (
            <MenuItem
              label={shareTarget === EBookVisibility.WORKSPACE ? "Share with workspace" : "Make personal"}
              icon={<Icon icon={shareTarget === EBookVisibility.WORKSPACE ? GlobeOutline : LockOutline} />}
              onClick={() =>
                void run(
                  () => updateBook(workspaceSlug, book.id, { visibility: shareTarget }),
                  shareTarget === EBookVisibility.WORKSPACE
                    ? "Everyone in the workspace can now read this book."
                    : "Only you can see this book now.",
                  "The book could not be changed."
                )
              }
            />
          )}
          {permissions.can_manage && (
            <MenuItem
              label={book.archived_at ? "Restore from archive" : "Archive"}
              icon={<Icon icon={book.archived_at ? RestoreOutline : ArchiveOutline} />}
              onClick={() =>
                void run(
                  () => updateBook(workspaceSlug, book.id, { archived: !book.archived_at }),
                  book.archived_at ? "The book is back in the library." : "The book was archived.",
                  "The book could not be changed."
                )
              }
            />
          )}
          {permissions.can_manage && (book.status === EBookStatus.FAILED || book.status === EBookStatus.READY) && (
            <MenuItem
              label="Process again"
              icon={<Icon icon={RefreshOutline} />}
              onClick={() =>
                void run(
                  () => reprocessBook(workspaceSlug, book.id),
                  "The book is being processed again.",
                  "The book could not be processed."
                )
              }
            />
          )}
          {permissions.can_manage && (
            <MenuItem label="Delete" icon={<Icon icon={DeleteOutline} />} onClick={() => setModal("delete")} />
          )}
        </MenuContent>
      </Menu>
      {modal === "edit" && (
        <BookEditModal workspaceSlug={workspaceSlug} book={book} isOpen onClose={() => setModal(null)} />
      )}
      {modal === "collections" && (
        <AddToCollectionModal workspaceSlug={workspaceSlug} book={book} isOpen onClose={() => setModal(null)} />
      )}
      <ConfirmDialog
        isOpen={modal === "delete"}
        handleClose={() => setModal(null)}
        handleSubmit={async () => {
          setIsDeleting(true);
          try {
            await deleteBook(workspaceSlug, book.id);
            setToast({ type: "success", title: "Deleted", message: "The book was removed from the library." });
            setModal(null);
            onDeleted?.();
          } catch (error) {
            setToast({
              type: "error",
              title: "Error!",
              message: libraryErrorMessage(error, "The book could not be deleted."),
            });
          } finally {
            setIsDeleting(false);
          }
        }}
        isSubmitting={isDeleting}
        title="Delete book"
        content={
          <>
            Delete <span className="font-medium break-words text-primary">{bookTitle(book)}</span>? The file and
            everything processed from it are removed for everyone. This cannot be undone.
          </>
        }
      />
    </>
  );
});
