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
  /** the requesting user's own reading of the book */
  my_reading: { progress: number; status: number; last_opened_at: string | null };
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
  /** whether the book's text can be found by library search */
  search_content: boolean;
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
    | "title"
    | "authors"
    | "publisher"
    | "language"
    | "isbn"
    | "published_date"
    | "description"
    | "tags"
    | "visibility"
    | "search_content"
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
  /** the requesting user's own reading status */
  reading: "unread" | "reading" | "completed" | null;
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

export enum EBookReadingStatus {
  UNREAD = 0,
  READING = 1,
  COMPLETED = 2,
}

/** Where a reader is: a character offset into the chapter's text, with a little of the text for checking. */
export type TBookPosition = { chapter: number; offset: number; quote?: string };

export type TBookReadingState = {
  position: TBookPosition | Record<string, never>;
  progress: number;
  status: EBookReadingStatus;
  last_opened_at: string | null;
  completed_at?: string | null;
};

export type TBookReadingStatePayload = Partial<{
  position: TBookPosition;
  progress: number;
  status: EBookReadingStatus;
  opened: boolean;
}>;

export type TReaderPreferences = {
  font_family: "publisher" | "serif" | "sans" | "mono" | "dyslexic";
  font_size: number;
  line_height: number;
  margin: "narrow" | "normal" | "wide";
  theme: "light" | "dark" | "sepia" | "system";
  layout: "paginated" | "scroll";
};

export type TBookChapterContent = {
  index: number;
  title: string;
  html: string;
  css: string;
  previous: number | null;
  next: number | null;
  /** seconds until the image links in html/css expire */
  expires_in: number;
};

export type TBookSearchResult = {
  chapter: number;
  chapter_title: string;
  /** which occurrence of the text in that chapter (0-based) */
  occurrence: number;
  before: string;
  match: string;
  after: string;
};

export type TBookSearchResponse = { query: string; results: TBookSearchResult[]; truncated: boolean };

export type TBookAnnotationKind = "highlight" | "note" | "bookmark";
export type TBookAnnotationColor = "yellow" | "green" | "blue" | "pink" | "purple";

export enum EBookAnnotationVisibility {
  PRIVATE = 0,
  SHARED = 1,
}

/** A highlight, note or bookmark, anchored like a reading position (chapter + character offsets + quote). */
export type TBookAnnotation = {
  id: string;
  book: string;
  book_title: string;
  user: string;
  user_detail: { id: string; display_name: string };
  kind: TBookAnnotationKind;
  color: TBookAnnotationColor | "";
  chapter: number;
  chapter_title: string;
  start_offset: number;
  end_offset: number;
  quote: string;
  prefix: string;
  suffix: string;
  note: string;
  visibility: EBookAnnotationVisibility;
  permissions: { can_edit: boolean; can_delete: boolean };
  created_at: string;
  updated_at: string;
};

export type TBookAnnotationCreate = Pick<TBookAnnotation, "kind" | "chapter" | "start_offset" | "end_offset"> &
  Partial<Pick<TBookAnnotation, "color" | "quote" | "prefix" | "suffix" | "note" | "visibility">>;

export type TBookAnnotationUpdate = Partial<Pick<TBookAnnotation, "color" | "note" | "visibility">>;

export type TBookAnnotationListResponse = {
  count: number;
  counts: Partial<Record<TBookAnnotationKind, number>>;
  results: TBookAnnotation[];
};

// --- wiki pages from books, and links ---

export type TBookLinkTargetType = "page" | "project" | "issue";

export type TBookLinkTarget = {
  id: string;
  name: string;
  /** pages: a wiki page has a space, a project page a project */
  space_id?: string | null;
  project_id?: string | null;
  /** projects */
  identifier?: string;
  /** work items */
  project_identifier?: string;
  sequence_id?: number;
};

export type TBookLink = {
  id: string;
  book: string;
  target_type: TBookLinkTargetType;
  target: TBookLinkTarget;
  /** "created": a page made from the book; "linked": added by hand */
  origin: "created" | "linked";
  chapter: number | null;
  start_offset: number | null;
  created_by: string | null;
  created_at: string;
  permissions: { can_delete: boolean };
  /** only on the linked-books list of a target */
  book_detail?: TBook;
};

export type TBookPassage = {
  chapter: number;
  start_offset: number;
  quote: string;
  note: string;
};

export type TWikiPageFromBook = {
  space: string;
  parent?: string | null;
  title?: string;
  intro?: string;
  passages: TBookPassage[];
  share: boolean;
  confirm_excerpts: boolean;
};

export type TWikiPageFromBookResponse = {
  page: { id: string; name: string; space: string; access: number };
  link: TBookLink;
};

// --- search across the library ---

export type TLibrarySearchPassage = {
  chapter: number;
  chapter_title: string;
  /** the matched text, and which occurrence of it in the chapter (for the reader) */
  match: string;
  occurrence: number;
  before: string;
  after: string;
};

export type TLibrarySearchResult = {
  book: TBook;
  matched_details: boolean;
  matched_text: boolean;
  /** chapters whose text matches (among the best-ranked candidates) */
  chapter_matches: number;
  passages: TLibrarySearchPassage[];
};

export type TLibrarySearchResponse = {
  query: string;
  count: number;
  limit: number;
  offset: number;
  results: TLibrarySearchResult[];
  /** false when full-text search is off for the instance or was not asked for */
  content_searched: boolean;
};

export type TLibrarySearchParams = {
  q: string;
  content?: boolean;
  file_format?: TBookFormat | null;
  visibility?: EBookVisibility | null;
  offset?: number;
  limit?: number;
};
