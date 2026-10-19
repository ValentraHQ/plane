/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { AxiosRequestConfig } from "axios";
import { sha256 } from "@noble/hashes/sha2";
import { bytesToHex } from "@noble/hashes/utils";
import type {
  TBook,
  TBookAnnotation,
  TBookAnnotationCreate,
  TBookAnnotationListResponse,
  TBookAnnotationUpdate,
  TBookChapterContent,
  TBookLink,
  TBookLinkTarget,
  TBookLinkTargetType,
  TBookChapterSummary,
  TBookReadingState,
  TBookReadingStatePayload,
  TBookSearchResponse,
  TReaderPreferences,
  TBookCollection,
  TBookFilters,
  TBookListResponse,
  TBookTag,
  TBookUpdatePayload,
  TBookUploadReservation,
  TLibrarySearchParams,
  TLibrarySearchResponse,
  TWikiPageFromBook,
  TWikiPageFromBookResponse,
  EBookVisibility,
} from "@plane/types";
import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";
import { FileUploadService } from "@/services/file-upload.service";

const HASH_CHUNK = 4 * 1024 * 1024;

/**
 * SHA-256 of a file, for duplicate detection (the server checks it against the stored file).
 * Web Crypto is only available on secure origins (https, localhost); plain-http installs fall back
 * to an incremental implementation that also never holds the whole file in memory.
 */
export async function hashFile(file: File, onProgress?: (fraction: number) => void): Promise<string> {
  if (globalThis.crypto?.subtle) {
    const digest = await globalThis.crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    onProgress?.(1);
    return bytesToHex(new Uint8Array(digest));
  }
  const hasher = sha256.create();
  for (let offset = 0; offset < file.size; offset += HASH_CHUNK) {
    // oxlint-disable-next-line no-await-in-loop -- chunks must be hashed in order
    hasher.update(new Uint8Array(await file.slice(offset, offset + HASH_CHUNK).arrayBuffer()));
    onProgress?.(Math.min(1, (offset + HASH_CHUNK) / file.size));
  }
  return bytesToHex(hasher.digest());
}

const rethrow = (error: { response?: { data?: unknown } }) => {
  throw error?.response?.data;
};

export class LibraryService extends APIService {
  private fileUploadService = new FileUploadService();

  constructor() {
    super(API_BASE_URL);
  }

  private base(slug: string) {
    return `/api/workspaces/${slug}/library`;
  }

  async listBooks(slug: string, filters: TBookFilters, offset = 0, limit = 48): Promise<TBookListResponse> {
    const params: Record<string, string | number> = { offset, limit, order_by: filters.order_by };
    if (filters.search) params.search = filters.search;
    if (filters.visibility !== null) params.visibility = filters.visibility;
    if (filters.format) params.file_format = filters.format;
    if (filters.tag) params.tag = filters.tag;
    if (filters.collection) params.collection = filters.collection;
    if (filters.archived) params.archived = "true";
    if (filters.reading) params.reading = filters.reading;
    return this.get(`${this.base(slug)}/books/`, { params })
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async getBook(slug: string, bookId: string): Promise<TBook> {
    return this.get(`${this.base(slug)}/books/${bookId}/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async updateBook(slug: string, bookId: string, payload: TBookUpdatePayload): Promise<TBook> {
    return this.patch(`${this.base(slug)}/books/${bookId}/`, payload)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async deleteBook(slug: string, bookId: string): Promise<void> {
    return this.delete(`${this.base(slug)}/books/${bookId}/`)
      .then(() => undefined)
      .catch(rethrow);
  }

  async reprocessBook(slug: string, bookId: string): Promise<TBook> {
    return this.post(`${this.base(slug)}/books/${bookId}/reprocess/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async getDownloadUrl(slug: string, bookId: string): Promise<{ url: string; expires_in: number }> {
    return this.get(`${this.base(slug)}/books/${bookId}/download/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async listChapters(slug: string, bookId: string): Promise<TBookChapterSummary[]> {
    return this.get(`${this.base(slug)}/books/${bookId}/chapters/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  /**
   * Reserve an upload, send the file straight to storage with the signed form, then confirm it.
   * Throws the API's error body; a duplicate comes back as { error, book_id }.
   */
  async uploadBook(
    slug: string,
    file: File,
    sha256Hex: string,
    visibility: EBookVisibility,
    onUploadProgress?: AxiosRequestConfig["onUploadProgress"]
  ): Promise<TBook> {
    const reservation: TBookUploadReservation = await this.post(`${this.base(slug)}/books/`, {
      name: file.name,
      size: file.size,
      sha256: sha256Hex,
      visibility,
    })
      .then((response) => response?.data)
      .catch(rethrow);
    const form = new FormData();
    Object.entries(reservation.upload_data.fields).forEach(([key, value]) => form.append(key, value));
    form.append("file", file);
    await this.fileUploadService.uploadFile(reservation.upload_data.url, form, onUploadProgress);
    return this.post(`${this.base(slug)}/books/${reservation.book.id}/upload-complete/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async getChapter(slug: string, bookId: string, index: number): Promise<TBookChapterContent> {
    return this.get(`${this.base(slug)}/books/${bookId}/chapters/${index}/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async getReadingState(slug: string, bookId: string): Promise<TBookReadingState> {
    return this.get(`${this.base(slug)}/books/${bookId}/reading-state/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async saveReadingState(slug: string, bookId: string, payload: TBookReadingStatePayload): Promise<TBookReadingState> {
    return this.put(`${this.base(slug)}/books/${bookId}/reading-state/`, payload)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  /** Save the position while the page is being hidden or closed (the request outlives the page). */
  saveReadingStateOnExit(slug: string, bookId: string, payload: TBookReadingStatePayload) {
    const csrf = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] ?? "";
    void fetch(`${this.baseURL ?? ""}${this.base(slug)}/books/${bookId}/reading-state/`, {
      method: "PUT",
      keepalive: true,
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent(csrf) },
      body: JSON.stringify(payload),
    }).catch(() => undefined);
  }

  async getContinueReading(slug: string): Promise<TBook[]> {
    return this.get(`${this.base(slug)}/continue-reading/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async getReaderPreferences(slug: string): Promise<TReaderPreferences> {
    return this.get(`${this.base(slug)}/reader-preferences/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async saveReaderPreferences(slug: string, preferences: Partial<TReaderPreferences>): Promise<TReaderPreferences> {
    return this.put(`${this.base(slug)}/reader-preferences/`, preferences)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async searchBook(slug: string, bookId: string, query: string): Promise<TBookSearchResponse> {
    return this.get(`${this.base(slug)}/books/${bookId}/search/`, { params: { q: query } })
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async listBookAnnotations(slug: string, bookId: string): Promise<TBookAnnotation[]> {
    return this.get(`${this.base(slug)}/books/${bookId}/annotations/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async createAnnotation(slug: string, bookId: string, data: TBookAnnotationCreate): Promise<TBookAnnotation> {
    return this.post(`${this.base(slug)}/books/${bookId}/annotations/`, data)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async updateAnnotation(slug: string, annotationId: string, data: TBookAnnotationUpdate): Promise<TBookAnnotation> {
    return this.patch(`${this.base(slug)}/annotations/${annotationId}/`, data)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async deleteAnnotation(slug: string, annotationId: string): Promise<void> {
    return this.delete(`${this.base(slug)}/annotations/${annotationId}/`)
      .then(() => undefined)
      .catch(rethrow);
  }

  async listMyAnnotations(
    slug: string,
    params: { book?: string; kind?: string; search?: string; limit?: number; offset?: number } = {}
  ): Promise<TBookAnnotationListResponse> {
    return this.get(`${this.base(slug)}/annotations/`, { params })
      .then((response) => response?.data)
      .catch(rethrow);
  }

  /** Download the user's own annotations as Markdown (one book, or all books). */
  async exportAnnotations(slug: string, bookId?: string) {
    const response = await this.get(`${this.base(slug)}/annotations/export/`, {
      params: bookId ? { book: bookId } : {},
      responseType: "blob",
    }).catch(rethrow);
    const disposition: string = response?.headers?.["content-disposition"] ?? "";
    const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename="([^"]+)"/);
    const name = match ? decodeURIComponent(match[1] ?? match[2]) : "notes-and-highlights.md";
    const href = URL.createObjectURL(response.data as Blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(href);
  }

  // --- search across the library ---

  async searchLibrary(slug: string, query: TLibrarySearchParams): Promise<TLibrarySearchResponse> {
    const params: Record<string, string | number> = { q: query.q, limit: query.limit ?? 20, offset: query.offset ?? 0 };
    if (query.content === false) params.content = "false";
    if (query.file_format) params.file_format = query.file_format;
    if (query.visibility !== null && query.visibility !== undefined) params.visibility = query.visibility;
    return this.get(`${this.base(slug)}/search/`, { params })
      .then((response) => response?.data)
      .catch(rethrow);
  }

  // --- wiki pages and links ---

  async createWikiPage(slug: string, bookId: string, data: TWikiPageFromBook): Promise<TWikiPageFromBookResponse> {
    return this.post(`${this.base(slug)}/books/${bookId}/wiki-pages/`, data)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async listBookLinks(slug: string, bookId: string): Promise<TBookLink[]> {
    return this.get(`${this.base(slug)}/books/${bookId}/links/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async createBookLink(
    slug: string,
    bookId: string,
    targetType: TBookLinkTargetType,
    targetId: string
  ): Promise<TBookLink> {
    return this.post(`${this.base(slug)}/books/${bookId}/links/`, { target_type: targetType, target_id: targetId })
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async deleteBookLink(slug: string, linkId: string): Promise<void> {
    await this.delete(`${this.base(slug)}/links/${linkId}/`).catch(rethrow);
  }

  /** Books linked to a page, project or work item (that the user can see). */
  async listLinkedBooks(slug: string, targetType: TBookLinkTargetType, targetId: string): Promise<TBookLink[]> {
    return this.get(`${this.base(slug)}/links/`, { params: { target_type: targetType, target_id: targetId } })
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async searchLinkTargets(slug: string, targetType: TBookLinkTargetType, search: string): Promise<TBookLinkTarget[]> {
    return this.get(`${this.base(slug)}/link-targets/`, { params: { target_type: targetType, search } })
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async listTags(slug: string): Promise<TBookTag[]> {
    return this.get(`${this.base(slug)}/tags/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async listCollections(slug: string): Promise<TBookCollection[]> {
    return this.get(`${this.base(slug)}/collections/`)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async createCollection(slug: string, data: Partial<TBookCollection>): Promise<TBookCollection> {
    return this.post(`${this.base(slug)}/collections/`, data)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async updateCollection(slug: string, collectionId: string, data: Partial<TBookCollection>): Promise<TBookCollection> {
    return this.patch(`${this.base(slug)}/collections/${collectionId}/`, data)
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async deleteCollection(slug: string, collectionId: string): Promise<void> {
    return this.delete(`${this.base(slug)}/collections/${collectionId}/`)
      .then(() => undefined)
      .catch(rethrow);
  }

  async addBooksToCollection(slug: string, collectionId: string, bookIds: string[]): Promise<{ added: number }> {
    return this.post(`${this.base(slug)}/collections/${collectionId}/books/`, { book_ids: bookIds })
      .then((response) => response?.data)
      .catch(rethrow);
  }

  async removeBookFromCollection(slug: string, collectionId: string, bookId: string): Promise<void> {
    return this.delete(`${this.base(slug)}/collections/${collectionId}/books/${bookId}/`)
      .then(() => undefined)
      .catch(rethrow);
  }
}
