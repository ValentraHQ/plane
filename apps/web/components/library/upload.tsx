/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { DragEvent, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
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
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { LinearProgress } from "@makeplane/propel/components/linear-progress";
import { CloseOutline, UploadOutline } from "@makeplane/propel/icons";
import { EBookVisibility } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useInstance } from "@/hooks/store/use-instance";
import { useLibrary } from "@/hooks/store/use-library";
import type { TBookUpload } from "@/store/library.store";
// local imports
import { BOOK_ACCEPT, formatBytes, isBookFile } from "./utils";

const DEFAULT_LIMIT = 100 * 1024 * 1024;

type ModalProps = {
  workspaceSlug: string;
  isOpen: boolean;
  onClose: () => void;
  /** files dropped on the page before the dialog opened */
  initialFiles?: File[];
};

export const BookUploadModal = observer(function BookUploadModal(props: ModalProps) {
  const { workspaceSlug, isOpen, onClose, initialFiles } = props;
  const { uploadFiles } = useLibrary();
  const { config } = useInstance();
  const limit = config?.book_file_size_limit ?? DEFAULT_LIMIT;
  const [files, setFiles] = useState<File[]>([]);
  const [visibility, setVisibility] = useState<EBookVisibility>(EBookVisibility.PERSONAL);
  const [isDragging, setIsDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) setFiles(initialFiles ?? []);
  }, [initialFiles, isOpen]);

  const problem = (file: File) =>
    !isBookFile(file)
      ? "Only EPUB and PDF files can be added."
      : file.size > limit
        ? `Larger than the ${formatBytes(limit)} limit.`
        : file.size === 0
          ? "The file is empty."
          : null;
  const valid = files.filter((file) => !problem(file));

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    // the same file picked twice is listed once
    setFiles((current) => {
      const known = new Set(current.map(fileKey));
      return [...current, ...Array.from(list).filter((file) => !known.has(fileKey(file)))];
    });
  };

  const start = () => {
    void uploadFiles(workspaceSlug, valid, visibility);
    onClose();
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="md">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>Upload books</DialogTitle>
            </DialogHeading>
          </DialogHeader>
          <DialogBody>
            <div className="flex flex-col gap-4">
              <button
                type="button"
                onClick={() => input.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragging(true);
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setIsDragging(false);
                  addFiles(e.dataTransfer.files);
                }}
                className={cn(
                  "flex flex-col items-center gap-2 rounded-lg border-2 border-dashed border-subtle px-4 py-8 text-center hover:bg-layer-transparent-hover",
                  { "border-accent-strong bg-layer-transparent-hover": isDragging }
                )}
              >
                <UploadOutline className="size-6 text-tertiary" />
                <span className="text-13 font-medium text-primary">
                  Drop EPUB or PDF files here, or click to choose
                </span>
                <span className="text-12 text-tertiary">Up to {formatBytes(limit)} each</span>
              </button>
              <input
                ref={input}
                type="file"
                accept={BOOK_ACCEPT}
                multiple
                className="hidden"
                data-testid="book-file-input"
                onChange={(e) => {
                  addFiles(e.target.files);
                  e.target.value = "";
                }}
              />
              {files.length > 0 && (
                <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto" aria-label="Selected files">
                  {files.map((file) => (
                    <li key={fileKey(file)} className="flex items-center gap-2 text-13">
                      <span className={cn("truncate", problem(file) ? "text-danger-primary" : "text-primary")}>
                        {file.name}
                      </span>
                      <span className="shrink-0 text-12 text-tertiary">{formatBytes(file.size)}</span>
                      {problem(file) && <span className="shrink-0 text-12 text-danger-primary">{problem(file)}</span>}
                      <span className="ml-auto" />
                      <IconButton
                        variant="ghost"
                        size="sm"
                        aria-label={`Remove ${file.name}`}
                        icon={<Icon icon={CloseOutline} />}
                        onClick={() => setFiles((current) => current.filter((item) => item !== file))}
                      />
                    </li>
                  ))}
                </ul>
              )}
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-1.5 text-13 text-secondary">Who can read them</legend>
                {[
                  { value: EBookVisibility.PERSONAL, label: "Only me", hint: "Your personal library." },
                  { value: EBookVisibility.WORKSPACE, label: "Everyone in the workspace", hint: "The shared library." },
                ].map((option) => (
                  <label key={option.value} className="flex cursor-pointer items-start gap-2 text-13">
                    <input
                      type="radio"
                      name="book-visibility"
                      className="mt-0.5"
                      checked={visibility === option.value}
                      onChange={() => setVisibility(option.value)}
                    />
                    <span>
                      <span className="font-medium text-primary">{option.label}</span>{" "}
                      <span className="text-tertiary">— {option.hint}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            </div>
          </DialogBody>
        </DialogMain>
        <DialogActions>
          <Button stretch="auto" variant="secondary" size="md" label="Cancel" onClick={onClose} />
          <Button
            stretch="auto"
            variant="primary"
            size="md"
            label={valid.length > 1 ? `Upload ${valid.length} books` : "Upload"}
            disabled={valid.length === 0}
            onClick={start}
          />
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
});

const PHASE_TEXT: Record<TBookUpload["phase"], string> = {
  hashing: "Checking…",
  uploading: "Uploading…",
  processing: "Processing…",
  ready: "Ready",
  failed: "Failed",
  duplicate: "Already in the library",
};

/** Floating list of uploads in progress and their outcome. */
export const BookUploadPanel = observer(function BookUploadPanel({ workspaceSlug }: { workspaceSlug: string }) {
  const { uploads, dismissUpload, clearFinishedUploads } = useLibrary();
  if (uploads.length === 0) return null;
  const finished = uploads.filter((u) => ["ready", "failed", "duplicate"].includes(u.phase)).length;

  return (
    <section
      aria-label="Uploads"
      className="shadow-lg fixed right-4 bottom-4 z-20 flex w-[min(24rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-subtle bg-surface-1"
    >
      <header className="flex items-center justify-between border-b border-subtle px-3 py-2">
        <span className="text-13 font-medium text-primary">
          Uploads {finished}/{uploads.length}
        </span>
        {finished > 0 && (
          <Button variant="ghost" size="sm" stretch="auto" label="Clear finished" onClick={clearFinishedUploads} />
        )}
      </header>
      <ul className="flex max-h-72 flex-col overflow-y-auto">
        {uploads.map((upload) => (
          <li
            key={upload.id}
            className="flex flex-col gap-1 border-b border-subtle px-3 py-2 last:border-b-0"
            data-testid="book-upload"
          >
            <div className="flex items-center gap-2">
              <span className="truncate text-13 text-primary">{upload.name}</span>
              <span
                className={cn("ml-auto shrink-0 text-12", {
                  "text-danger-primary": upload.phase === "failed",
                  "text-success-primary": upload.phase === "ready",
                  "text-tertiary": !["failed", "ready"].includes(upload.phase),
                })}
              >
                {PHASE_TEXT[upload.phase]}
              </span>
              {["ready", "failed", "duplicate"].includes(upload.phase) && (
                <IconButton
                  variant="ghost"
                  size="sm"
                  aria-label={`Dismiss ${upload.name}`}
                  icon={<Icon icon={CloseOutline} />}
                  onClick={() => dismissUpload(upload.id)}
                />
              )}
            </div>
            {["hashing", "uploading", "processing"].includes(upload.phase) && (
              <LinearProgress
                value={Math.round(upload.progress * 100)}
                size="sm"
                variant="brand"
                indeterminate={upload.phase === "processing"}
                aria-label={`${PHASE_TEXT[upload.phase]} ${upload.name}`}
              />
            )}
            {upload.error && upload.phase !== "duplicate" && (
              <p className="text-12 text-danger-primary">{upload.error}</p>
            )}
            {upload.bookId && ["ready", "duplicate"].includes(upload.phase) && (
              <Link
                href={`/${workspaceSlug}/library/books/${upload.bookId}`}
                className="text-12 text-accent-primary hover:underline"
              >
                Open book
              </Link>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
});

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

const fileKey = (file: File) => `${file.name}:${file.size}:${file.lastModified}`;

/** Accept book files dropped anywhere on the wrapped area. */
export function BookDropZone({
  children,
  onFiles,
  disabled,
}: {
  children: ReactNode;
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const depth = useRef(0);

  return (
    <div
      className="relative h-full"
      onDragEnter={(e) => {
        if (disabled || !hasFiles(e)) return;
        depth.current += 1;
        setIsDragging(true);
      }}
      onDragOver={(e) => {
        if (!disabled && hasFiles(e)) e.preventDefault();
      }}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setIsDragging(false);
      }}
      onDrop={(e) => {
        if (disabled || !hasFiles(e)) return;
        e.preventDefault();
        depth.current = 0;
        setIsDragging(false);
        onFiles(Array.from(e.dataTransfer.files));
      }}
    >
      {children}
      {isDragging && (
        <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-lg border-2 border-dashed border-accent-strong bg-surface-1/80">
          <span className="flex items-center gap-2 text-14 font-medium text-primary">
            <UploadOutline className="size-5" /> Drop to upload books
          </span>
        </div>
      )}
    </div>
  );
}
