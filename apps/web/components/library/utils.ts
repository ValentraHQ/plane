/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TBook } from "@plane/types";
import { EBookStatus, EBookVisibility } from "@plane/types";

export const BOOK_ACCEPT = ".epub,.pdf,application/epub+zip,application/pdf";

export const isBookFile = (file: File) => /\.(epub|pdf)$/i.test(file.name);

export const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export const bookTitle = (book: Pick<TBook, "title" | "original_filename">) =>
  book.title || book.original_filename || "Untitled book";

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export const bookAuthors = (book: Pick<TBook, "authors">) =>
  book.authors.length ? book.authors.join(", ") : "Unknown author";

export const VISIBILITY_LABELS: Record<EBookVisibility, string> = {
  [EBookVisibility.PERSONAL]: "Only me",
  [EBookVisibility.WORKSPACE]: "Workspace",
};

export const STATUS_LABELS: Record<EBookStatus, string> = {
  [EBookStatus.UPLOADING]: "Uploading",
  [EBookStatus.PROCESSING]: "Processing",
  [EBookStatus.READY]: "Ready",
  [EBookStatus.FAILED]: "Failed",
};

/** A stable, readable colour pair for books without a cover image. */
export const placeholderColors = (seed: string) => {
  let hash = 0;
  for (const char of seed) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  const hue = Math.abs(hash) % 360;
  return { background: `hsl(${hue} 45% 32%)`, accent: `hsl(${(hue + 40) % 360} 55% 62%)` };
};
