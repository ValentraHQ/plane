/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// types
import { API_BASE_URL } from "@plane/constants";
import type { TDocumentPayload, TPage, TPageVersion } from "@plane/types";
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
   * @description fetch top-level wiki pages, or the direct children of params.parent_id
   */
  async fetchAll(workspaceSlug: string, params?: { parent_id?: string }): Promise<TPage[]> {
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
