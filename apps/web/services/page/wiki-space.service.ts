/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TWikiSpace, TWikiSpaceMember, TWikiTreeNode } from "@plane/types";
// services
import { APIService } from "@/services/api.service";

/**
 * Documentation spaces of the workspace wiki: /api/workspaces/<slug>/wiki/spaces/
 */
export class WikiSpaceService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private spacesPath(workspaceSlug: string, spaceId?: string) {
    const base = `/api/workspaces/${workspaceSlug}/wiki/spaces/`;
    return spaceId ? `${base}${spaceId}/` : base;
  }

  private async unwrap<T>(promise: Promise<{ data: T }>): Promise<T> {
    return promise
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async fetchAll(workspaceSlug: string): Promise<TWikiSpace[]> {
    return this.unwrap(this.get(this.spacesPath(workspaceSlug)));
  }

  async fetchById(workspaceSlug: string, spaceId: string): Promise<TWikiSpace> {
    return this.unwrap(this.get(this.spacesPath(workspaceSlug, spaceId)));
  }

  async create(workspaceSlug: string, data: Partial<TWikiSpace>): Promise<TWikiSpace> {
    return this.unwrap(this.post(this.spacesPath(workspaceSlug), data));
  }

  async update(workspaceSlug: string, spaceId: string, data: Partial<TWikiSpace>): Promise<TWikiSpace> {
    return this.unwrap(this.patch(this.spacesPath(workspaceSlug, spaceId), data));
  }

  async remove(workspaceSlug: string, spaceId: string): Promise<void> {
    return this.unwrap(this.delete(this.spacesPath(workspaceSlug, spaceId)));
  }

  async fetchTree(workspaceSlug: string, spaceId: string): Promise<TWikiTreeNode[]> {
    return this.unwrap(this.get(`${this.spacesPath(workspaceSlug, spaceId)}pages-tree/`));
  }

  async fetchMembers(workspaceSlug: string, spaceId: string): Promise<TWikiSpaceMember[]> {
    return this.unwrap(this.get(`${this.spacesPath(workspaceSlug, spaceId)}members/`));
  }

  async addMember(
    workspaceSlug: string,
    spaceId: string,
    data: Pick<TWikiSpaceMember, "member" | "role">
  ): Promise<TWikiSpaceMember> {
    return this.unwrap(this.post(`${this.spacesPath(workspaceSlug, spaceId)}members/`, data));
  }

  async updateMember(
    workspaceSlug: string,
    spaceId: string,
    membershipId: string,
    data: Pick<TWikiSpaceMember, "role">
  ): Promise<TWikiSpaceMember> {
    return this.unwrap(this.patch(`${this.spacesPath(workspaceSlug, spaceId)}members/${membershipId}/`, data));
  }

  async removeMember(workspaceSlug: string, spaceId: string, membershipId: string): Promise<void> {
    return this.unwrap(this.delete(`${this.spacesPath(workspaceSlug, spaceId)}members/${membershipId}/`));
  }
}
