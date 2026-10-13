/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// types
import { API_BASE_URL } from "@plane/constants";
import type {
  TDocumentPayload,
  TPage,
  TPageRestrictions,
  TPageRestrictionsPayload,
  TPageVersion,
  TWikiPageMovePayload,
} from "@plane/types";
// services
import { APIService } from "@/services/api.service";

/**
 * Workspace wiki pages: pages that live outside projects (/api/workspaces/<slug>/wiki/pages/).
 */
export class WorkspacePageService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private pagesPath(workspaceSlug: string, pageId?: string) {
    const base = `/api/workspaces/${workspaceSlug}/wiki/pages/`;
    return pageId ? `${base}${pageId}/` : base;
  }

  /**
   * @description fetch top-level wiki pages (optionally of one space), or the direct children of params.parent_id
   */
  async fetchAll(workspaceSlug: string, params?: { parent_id?: string; space_id?: string }): Promise<TPage[]> {
    return this.get(this.pagesPath(workspaceSlug), { params })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async fetchById(workspaceSlug: string, pageId: string): Promise<TPage> {
    return this.get(this.pagesPath(workspaceSlug, pageId))
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async create(workspaceSlug: string, data: Partial<TPage>): Promise<TPage> {
    return this.post(this.pagesPath(workspaceSlug), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async update(workspaceSlug: string, pageId: string, data: Partial<TPage>): Promise<TPage> {
    return this.patch(this.pagesPath(workspaceSlug, pageId), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async updateAccess(workspaceSlug: string, pageId: string, data: Pick<TPage, "access">): Promise<void> {
    return this.post(`${this.pagesPath(workspaceSlug, pageId)}access/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async remove(workspaceSlug: string, pageId: string): Promise<void> {
    return this.delete(this.pagesPath(workspaceSlug, pageId))
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async archive(workspaceSlug: string, pageId: string): Promise<{ archived_at: string }> {
    return this.post(`${this.pagesPath(workspaceSlug, pageId)}archive/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async restore(workspaceSlug: string, pageId: string): Promise<void> {
    return this.delete(`${this.pagesPath(workspaceSlug, pageId)}archive/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async lock(workspaceSlug: string, pageId: string): Promise<void> {
    return this.post(`${this.pagesPath(workspaceSlug, pageId)}lock/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async unlock(workspaceSlug: string, pageId: string): Promise<void> {
    return this.delete(`${this.pagesPath(workspaceSlug, pageId)}lock/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async fetchDescriptionBinary(workspaceSlug: string, pageId: string): Promise<any> {
    return this.get(`${this.pagesPath(workspaceSlug, pageId)}description/`, {
      headers: {
        "Content-Type": "application/octet-stream",
      },
      responseType: "arraybuffer",
    })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async updateDescription(workspaceSlug: string, pageId: string, data: TDocumentPayload): Promise<any> {
    return this.patch(`${this.pagesPath(workspaceSlug, pageId)}description/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error;
      });
  }

  /**
   * @description move a page (with its sub-pages) to another parent, space and/or position
   */
  async move(workspaceSlug: string, pageId: string, data: TWikiPageMovePayload): Promise<TPage> {
    return this.post(`${this.pagesPath(workspaceSlug, pageId)}move/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async fetchPermissions(
    workspaceSlug: string,
    pageId: string
  ): Promise<{ can_view: boolean; can_edit: boolean; can_manage: boolean; can_edit_content: boolean }> {
    return this.get(`${this.pagesPath(workspaceSlug, pageId)}permissions/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async fetchRestrictions(workspaceSlug: string, pageId: string): Promise<TPageRestrictions> {
    return this.get(`${this.pagesPath(workspaceSlug, pageId)}restrictions/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async updateRestrictions(
    workspaceSlug: string,
    pageId: string,
    payload: TPageRestrictionsPayload
  ): Promise<TPageRestrictions> {
    return this.put(`${this.pagesPath(workspaceSlug, pageId)}restrictions/`, payload)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async fetchAllVersions(workspaceSlug: string, pageId: string): Promise<TPageVersion[]> {
    return this.get(`${this.pagesPath(workspaceSlug, pageId)}versions/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async fetchVersionById(workspaceSlug: string, pageId: string, versionId: string): Promise<TPageVersion> {
    return this.get(`${this.pagesPath(workspaceSlug, pageId)}versions/${versionId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
