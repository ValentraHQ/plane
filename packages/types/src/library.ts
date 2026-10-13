/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** Who can see a book or collection (matches the API's Book.VISIBILITY_*). */
export enum EBookVisibility {
  PERSONAL = 0,
  WORKSPACE = 1,
}

export enum EBookStatus {
  UPLOADING = 0,
  PROCESSING = 1,
  READY = 2,
  FAILED = 3,
}

export type TBookFormat = "epub" | "pdf";

export type TBookPermissions = {
  can_view: boolean;
  can_download: boolean;
  can_edit: boolean;
  can_manage: boolean;
};

export type TBookTocEntry = {
  title: string;
  chapter: number | null;
  fragment: string;
  children: TBookTocEntry[];
};

export type TBook = {
  id: string;
  workspace: string;
  owner: string;
  owner_detail: { id: string; display_name: string; avatar_url: string | null };
  visibility: EBookVisibility;
  format: TBookFormat;
  original_filename: string;
  file_size: number;
  file_hash: string;
  status: EBookStatus;
  status_label: string;
  failure_reason: string;
  processed_at: string | null;
  title: string;
  authors: string[];
  publisher: string;
  language: string;
  isbn: string;
  published_date: string;
  description: string;
  subjects: string[];
  identifiers: { scheme: string; value: string }[];
  edited_fields: string[];
  tags: string[];
  chapter_count: number;
  character_count: number;
  page_count: number | null;
  archived_at: string | null;
  permissions: TBookPermissions;
  /** short-lived signed links */
  cover_url: string | null;
  cover_thumbnail_url: string | null;
  created_at: string;
  updated_at: string;
  /** detail only */
  toc?: TBookTocEntry[];
  collection_ids?: string[];
};

export type TBookUpdatePayload = Partial<
  Pick<
    TBook,
    "title" | "authors" | "publisher" | "language" | "isbn" | "published_date" | "description" | "tags" | "visibility"
  >
> & { archived?: boolean };

export type TBookListResponse = {
  count: number;
  limit: number;
  offset: number;
  results: TBook[];
};

export type TBookOrderBy = "-created_at" | "created_at" | "title" | "-title" | "-updated_at" | "updated_at";

export type TBookFilters = {
  search: string;
  visibility: EBookVisibility | null;
  format: TBookFormat | null;
  tag: string | null;
  collection: string | null;
  archived: boolean;
  order_by: TBookOrderBy;
};

export type TBookChapterSummary = {
  id: string;
  index: number;
  title: string;
  href: string;
  linear: boolean;
  character_count: number;
};

export type TBookTag = { name: string; count: number };

export type TBookCollection = {
  id: string;
  workspace: string;
  owner: string;
  name: string;
  description: string;
  visibility: EBookVisibility;
  sort_order: number;
  book_count: number;
  permissions: { can_view: boolean; can_edit: boolean };
  created_at: string;
  updated_at: string;
};

export type TBookUploadReservation = {
  book: TBook;
  upload_data: { url: string; fields: Record<string, string> };
};
