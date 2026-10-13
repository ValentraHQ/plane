/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { set, sortBy, unset } from "lodash-es";
import { action, computed, makeObservable, observable, runInAction } from "mobx";
import type {
  TBook,
  TBookChapterSummary,
  TBookCollection,
  TBookFilters,
  TBookTag,
  TBookUpdatePayload,
} from "@plane/types";
import { EBookReadingStatus, EBookStatus, EBookVisibility } from "@plane/types";
import { LibraryService, hashFile } from "@/services/library.service";
import type { CoreRootStore } from "./root.store";

const PAGE_SIZE = 48;
const POLL_INTERVAL = 2000;
const POLL_TIMEOUT = 15 * 60 * 1000;

export type TBookUploadPhase = "hashing" | "uploading" | "processing" | "ready" | "failed" | "duplicate";

export type TBookUpload = {
  id: string;
  name: string;
  size: number;
  phase: TBookUploadPhase;
  /** 0..1 within the current phase */
  progress: number;
  bookId?: string;
  error?: string;
};

export const DEFAULT_BOOK_FILTERS: TBookFilters = {
  search: "",
  visibility: null,
  format: null,
  tag: null,
  collection: null,
  archived: false,
  reading: null,
  order_by: "-created_at",
};

type TApiError = { error?: string; book_id?: string; [field: string]: unknown } | undefined;

export const libraryErrorMessage = (error: unknown, fallback: string) => {
  const body = error as TApiError;
  if (body?.error) return body.error;
  const firstField = body && Object.values(body).find((value) => Array.isArray(value));
  return firstField ? String((firstField as string[])[0]) : fallback;
};

export interface ILibraryStore {
  books: Record<string, TBook>;
  listIds: string[];
  count: number;
  isLoading: boolean;
  isLoadingMore: boolean;
  loadError: string | undefined;
  filters: TBookFilters;
  tags: TBookTag[];
  collections: Record<string, TBookCollection>;
  chapters: Record<string, TBookChapterSummary[]>;
  uploads: TBookUpload[];
  /** books the user is in the middle of, most recent first */
  continueReading: TBook[];
  fetchContinueReading: (slug: string) => Promise<void>;
  setReadingStatus: (slug: string, bookId: string, status: EBookReadingStatus) => Promise<void>;
  /** the upload dialog (opened from the header, the empty state or by dropping files) */
  uploadDialog: { isOpen: boolean; files: File[] };
  openUploadDialog: (files?: File[]) => void;
  closeUploadDialog: () => void;
  // computed
  hasMore: boolean;
  collectionIds: string[];
  isUploading: boolean;
  // helpers
  getBookById: (bookId: string | undefined) => TBook | undefined;
  // actions
  setFilters: (filters: Partial<TBookFilters>) => void;
  resetFilters: () => void;
  fetchBooks: (slug: string) => Promise<void>;
  fetchMoreBooks: (slug: string) => Promise<void>;
  fetchBook: (slug: string, bookId: string) => Promise<TBook>;
  fetchChapters: (slug: string, bookId: string) => Promise<TBookChapterSummary[]>;
  updateBook: (slug: string, bookId: string, payload: TBookUpdatePayload) => Promise<TBook>;
  deleteBook: (slug: string, bookId: string) => Promise<void>;
  reprocessBook: (slug: string, bookId: string) => Promise<void>;
  downloadBook: (slug: string, bookId: string) => Promise<void>;
  uploadFiles: (slug: string, files: File[], visibility: EBookVisibility) => Promise<void>;
  dismissUpload: (uploadId: string) => void;
  clearFinishedUploads: () => void;
  fetchTags: (slug: string) => Promise<void>;
  fetchCollections: (slug: string) => Promise<void>;
  createCollection: (slug: string, data: Partial<TBookCollection>) => Promise<TBookCollection>;
  updateCollection: (slug: string, collectionId: string, data: Partial<TBookCollection>) => Promise<TBookCollection>;
  deleteCollection: (slug: string, collectionId: string) => Promise<void>;
  addToCollection: (slug: string, collectionId: string, bookIds: string[]) => Promise<number>;
  removeFromCollection: (slug: string, collectionId: string, bookId: string) => Promise<void>;
}

const service = new LibraryService();

/** Library books, the current filtered list, tags, collections and the upload queue. */
export class LibraryStore implements ILibraryStore {
  books: Record<string, TBook> = {};
  listIds: string[] = [];
  count = 0;
  isLoading = false;
  isLoadingMore = false;
  loadError: string | undefined = undefined;
  filters: TBookFilters = { ...DEFAULT_BOOK_FILTERS };
  tags: TBookTag[] = [];
  collections: Record<string, TBookCollection> = {};
  chapters: Record<string, TBookChapterSummary[]> = {};
  uploads: TBookUpload[] = [];
  uploadDialog: { isOpen: boolean; files: File[] } = { isOpen: false, files: [] };
  continueReading: TBook[] = [];
  // a newer list request makes older responses irrelevant
  private listRequest = 0;
  private uploadCounter = 0;

  constructor(private store: CoreRootStore) {
    makeObservable(this, {
      books: observable,
      listIds: observable,
      count: observable.ref,
      isLoading: observable.ref,
      isLoadingMore: observable.ref,
      loadError: observable.ref,
      filters: observable,
      tags: observable.ref,
      collections: observable,
      chapters: observable,
      uploads: observable,
      uploadDialog: observable.ref,
      continueReading: observable.ref,
      fetchContinueReading: action,
      setReadingStatus: action,
      openUploadDialog: action,
      closeUploadDialog: action,
      hasMore: computed,
      collectionIds: computed,
      isUploading: computed,
      setFilters: action,
      resetFilters: action,
      fetchBooks: action,
      fetchMoreBooks: action,
      fetchBook: action,
      updateBook: action,
      deleteBook: action,
      reprocessBook: action,
      uploadFiles: action,
      dismissUpload: action,
      clearFinishedUploads: action,
      fetchTags: action,
      fetchCollections: action,
      createCollection: action,
      updateCollection: action,
      deleteCollection: action,
      addToCollection: action,
      removeFromCollection: action,
    });
  }

  get hasMore() {
    return this.listIds.length < this.count;
  }

  get collectionIds() {
    return sortBy(Object.values(this.collections), [(c) => c.visibility, (c) => c.name.toLowerCase()]).map((c) => c.id);
  }

  get isUploading() {
    return this.uploads.some((upload) => ["hashing", "uploading"].includes(upload.phase));
  }

  getBookById = (bookId: string | undefined) => (bookId ? this.books[bookId] : undefined);

  private upsert(book: TBook) {
    set(this.books, [book.id], { ...this.books[book.id], ...book });
  }

  fetchContinueReading = async (slug: string) => {
    const books = await service.getContinueReading(slug);
    runInAction(() => {
      books.forEach((book) => this.upsert(book));
      this.continueReading = books;
    });
  };

  setReadingStatus = async (slug: string, bookId: string, status: EBookReadingStatus) => {
    const state = await service.saveReadingState(slug, bookId, { status });
    runInAction(() => {
      const book = this.books[bookId];
      if (book)
        book.my_reading = { progress: state.progress, status: state.status, last_opened_at: state.last_opened_at };
    });
    void this.fetchContinueReading(slug);
  };

  openUploadDialog = (files: File[] = []) => {
    this.uploadDialog = { isOpen: true, files };
  };

  closeUploadDialog = () => {
    this.uploadDialog = { isOpen: false, files: [] };
  };

  setFilters = (filters: Partial<TBookFilters>) => {
    this.filters = { ...this.filters, ...filters };
  };

  resetFilters = () => {
    this.filters = { ...DEFAULT_BOOK_FILTERS };
  };

  fetchBooks = async (slug: string) => {
    const request = ++this.listRequest;
    this.isLoading = true;
    this.loadError = undefined;
    try {
      const response = await service.listBooks(slug, this.filters, 0, PAGE_SIZE);
      if (request !== this.listRequest) return;
      runInAction(() => {
        response.results.forEach((book) => this.upsert(book));
        this.listIds = response.results.map((book) => book.id);
        this.count = response.count;
      });
    } catch (error) {
      if (request !== this.listRequest) return;
      runInAction(() => {
        this.listIds = [];
        this.count = 0;
        this.loadError = libraryErrorMessage(error, "The library could not be loaded.");
      });
    } finally {
      if (request === this.listRequest) runInAction(() => (this.isLoading = false));
    }
  };

  fetchMoreBooks = async (slug: string) => {
    if (this.isLoadingMore || !this.hasMore) return;
    const request = this.listRequest;
    this.isLoadingMore = true;
    try {
      const response = await service.listBooks(slug, this.filters, this.listIds.length, PAGE_SIZE);
      if (request !== this.listRequest) return;
      runInAction(() => {
        response.results.forEach((book) => this.upsert(book));
        const known = new Set(this.listIds);
        this.listIds.push(...response.results.map((book) => book.id).filter((id) => !known.has(id)));
        this.count = response.count;
      });
    } finally {
      runInAction(() => (this.isLoadingMore = false));
    }
  };

  fetchBook = async (slug: string, bookId: string) => {
    const book = await service.getBook(slug, bookId);
    runInAction(() => this.upsert(book));
    return book;
  };

  fetchChapters = async (slug: string, bookId: string) => {
    const chapters = await service.listChapters(slug, bookId);
    runInAction(() => set(this.chapters, [bookId], chapters));
    return chapters;
  };

  updateBook = async (slug: string, bookId: string, payload: TBookUpdatePayload) => {
    const book = await service.updateBook(slug, bookId, payload);
    runInAction(() => {
      this.upsert(book);
      // leave lists the book no longer belongs to
      const filters = this.filters;
      const leaves =
        ("archived" in payload && !!book.archived_at !== filters.archived) ||
        (filters.visibility !== null && book.visibility !== filters.visibility);
      if (leaves) this.dropFromList(bookId);
    });
    if ("tags" in payload) void this.fetchTags(slug);
    if ("visibility" in payload) void this.fetchCollections(slug);
    return book;
  };

  private dropFromList(bookId: string) {
    const index = this.listIds.indexOf(bookId);
    if (index >= 0) {
      this.listIds.splice(index, 1);
      this.count = Math.max(0, this.count - 1);
    }
  }

  deleteBook = async (slug: string, bookId: string) => {
    await service.deleteBook(slug, bookId);
    runInAction(() => {
      this.dropFromList(bookId);
      unset(this.books, [bookId]);
    });
    void this.fetchTags(slug);
    void this.fetchCollections(slug);
  };

  reprocessBook = async (slug: string, bookId: string) => {
    const book = await service.reprocessBook(slug, bookId);
    runInAction(() => this.upsert(book));
    void this.pollUntilProcessed(slug, bookId);
  };

  downloadBook = async (slug: string, bookId: string) => {
    const { url } = await service.getDownloadUrl(slug, bookId);
    // the signed link answers with Content-Disposition: attachment
    const link = document.createElement("a");
    link.href = url;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  private patchUpload(id: string, patch: Partial<TBookUpload>) {
    const upload = this.uploads.find((item) => item.id === id);
    if (upload) Object.assign(upload, patch);
  }

  uploadFiles = async (slug: string, files: File[], visibility: EBookVisibility) => {
    const entries = files.map((file) => ({
      file,
      upload: {
        id: `upload-${++this.uploadCounter}`,
        name: file.name,
        size: file.size,
        phase: "hashing" as TBookUploadPhase,
        progress: 0,
      },
    }));
    this.uploads.push(...entries.map((entry) => entry.upload));
    // one file at a time: keeps memory and bandwidth predictable for large books
    await entries.reduce<Promise<void>>(
      (previous, { file, upload }) => previous.then(() => this.uploadOne(slug, file, upload.id, visibility)),
      Promise.resolve()
    );
  };

  private async uploadOne(slug: string, file: File, uploadId: string, visibility: EBookVisibility) {
    try {
      const hash = await hashFile(file, (progress) => runInAction(() => this.patchUpload(uploadId, { progress })));
      runInAction(() => this.patchUpload(uploadId, { phase: "uploading", progress: 0 }));
      const book = await service.uploadBook(slug, file, hash, visibility, (event) =>
        runInAction(() => this.patchUpload(uploadId, { progress: event.total ? event.loaded / event.total : 0 }))
      );
      runInAction(() => {
        this.patchUpload(uploadId, { phase: "processing", progress: 0, bookId: book.id });
        this.upsert(book);
      });
      void this.fetchBooks(slug);
      void this.pollUntilProcessed(slug, book.id, uploadId);
    } catch (error) {
      const body = error as TApiError;
      runInAction(() =>
        this.patchUpload(uploadId, {
          phase: body?.book_id ? "duplicate" : "failed",
          bookId: body?.book_id,
          error: libraryErrorMessage(error, "The upload failed."),
        })
      );
    }
  }

  /** Check the book every few seconds until the worker has processed it (or give up after a while). */
  private async pollUntilProcessed(
    slug: string,
    bookId: string,
    uploadId?: string,
    started = Date.now()
  ): Promise<void> {
    if (Date.now() - started > POLL_TIMEOUT) return;
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL));
    let book: TBook;
    try {
      book = await this.fetchBook(slug, bookId);
    } catch {
      return;
    }
    if (book.status !== EBookStatus.READY && book.status !== EBookStatus.FAILED) {
      return this.pollUntilProcessed(slug, bookId, uploadId, started);
    }
    runInAction(() => {
      if (uploadId)
        this.patchUpload(uploadId, {
          phase: book.status === EBookStatus.READY ? "ready" : "failed",
          error: book.failure_reason || undefined,
          progress: 1,
        });
    });
    void this.fetchTags(slug);
  }

  dismissUpload = (uploadId: string) => {
    this.uploads = this.uploads.filter((upload) => upload.id !== uploadId);
  };

  clearFinishedUploads = () => {
    this.uploads = this.uploads.filter((upload) => ["hashing", "uploading", "processing"].includes(upload.phase));
  };

  fetchTags = async (slug: string) => {
    const tags = await service.listTags(slug);
    runInAction(() => (this.tags = tags));
  };

  fetchCollections = async (slug: string) => {
    const collections = await service.listCollections(slug);
    runInAction(() => {
      this.collections = Object.fromEntries(collections.map((collection) => [collection.id, collection]));
    });
  };

  createCollection = async (slug: string, data: Partial<TBookCollection>) => {
    const collection = await service.createCollection(slug, data);
    runInAction(() => set(this.collections, [collection.id], collection));
    return collection;
  };

  updateCollection = async (slug: string, collectionId: string, data: Partial<TBookCollection>) => {
    const collection = await service.updateCollection(slug, collectionId, data);
    runInAction(() => set(this.collections, [collection.id], collection));
    return collection;
  };

  deleteCollection = async (slug: string, collectionId: string) => {
    await service.deleteCollection(slug, collectionId);
    runInAction(() => {
      unset(this.collections, [collectionId]);
      if (this.filters.collection === collectionId) this.filters = { ...this.filters, collection: null };
    });
  };

  addToCollection = async (slug: string, collectionId: string, bookIds: string[]) => {
    const { added } = await service.addBooksToCollection(slug, collectionId, bookIds);
    await this.fetchCollections(slug);
    return added;
  };

  removeFromCollection = async (slug: string, collectionId: string, bookId: string) => {
    await service.removeBookFromCollection(slug, collectionId, bookId);
    runInAction(() => {
      if (this.filters.collection === collectionId) this.dropFromList(bookId);
      const book = this.books[bookId];
      if (book?.collection_ids) book.collection_ids = book.collection_ids.filter((id) => id !== collectionId);
    });
    await this.fetchCollections(slug);
  };
}
