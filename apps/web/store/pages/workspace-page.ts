/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { computed, makeObservable } from "mobx";
import { computedFn } from "mobx-utils";
// constants
import { EPageAccess, EUserPermissions } from "@plane/constants";
import type { TPage } from "@plane/types";
// plane web store
import type { RootStore } from "@/store/root.store";
// services
import { WorkspacePageService } from "@/services/page";
// store
import { BasePage } from "./base-page";
import type { TPageInstance } from "./base-page";

const workspacePageService = new WorkspacePageService();

export type TWorkspacePage = TPageInstance;

/**
 * A workspace wiki page (outside projects). Permissions follow the user's workspace role;
 * the API enforces the same rules (admins/members only, owner-or-admin for lock/archive/delete).
 */
export class WorkspacePage extends BasePage implements TWorkspacePage {
  constructor(store: RootStore, page: TPage) {
    // required fields for API calls
    const { workspaceSlug } = store.router;
    const requireIds = () => {
      if (!workspaceSlug || !page.id) throw new Error("Missing required fields.");
      return { slug: workspaceSlug, pageId: page.id };
    };
    super(store, page, {
      update: async (payload) => {
        const { slug, pageId } = requireIds();
        return await workspacePageService.update(slug, pageId, payload);
      },
      updateDescription: async (document) => {
        const { slug, pageId } = requireIds();
        await workspacePageService.updateDescription(slug, pageId, document);
      },
      updateAccess: async (payload) => {
        const { slug, pageId } = requireIds();
        await workspacePageService.updateAccess(slug, pageId, payload);
      },
      lock: async () => {
        const { slug, pageId } = requireIds();
        await workspacePageService.lock(slug, pageId);
      },
      unlock: async () => {
        const { slug, pageId } = requireIds();
        await workspacePageService.unlock(slug, pageId);
      },
      archive: async () => {
        const { slug, pageId } = requireIds();
        return await workspacePageService.archive(slug, pageId);
      },
      restore: async () => {
        const { slug, pageId } = requireIds();
        await workspacePageService.restore(slug, pageId);
      },
      duplicate: async () => {
        throw new Error("Duplicating wiki pages is not supported yet.");
      },
    });
    makeObservable(this, {
      // computed
      canCurrentUserAccessPage: computed,
      canCurrentUserEditPage: computed,
      canCurrentUserDuplicatePage: computed,
      canCurrentUserLockPage: computed,
      canCurrentUserChangeAccess: computed,
      canCurrentUserArchivePage: computed,
      canCurrentUserDeletePage: computed,
      canCurrentUserFavoritePage: computed,
      canCurrentUserMovePage: computed,
      isContentEditable: computed,
    });
  }

  private getWorkspaceRole = computedFn((): number | undefined => {
    const { workspaceSlug } = this.rootStore.router;
    if (!workspaceSlug) return undefined;
    return this.rootStore.user.permission.getWorkspaceRoleByWorkspaceSlug(workspaceSlug.toString()) as
      | number
      | undefined;
  });

  private get isWorkspaceMember() {
    const role = this.getWorkspaceRole();
    return !!role && role >= EUserPermissions.MEMBER;
  }

  private get isWorkspaceAdmin() {
    return this.getWorkspaceRole() === EUserPermissions.ADMIN;
  }

  get canCurrentUserAccessPage() {
    return this.access === EPageAccess.PUBLIC || this.isCurrentUserOwner;
  }

  get canCurrentUserEditPage() {
    const isPagePublic = this.access === EPageAccess.PUBLIC;
    return (isPagePublic && this.isWorkspaceMember) || (!isPagePublic && this.isCurrentUserOwner);
  }

  // not supported for wiki pages yet (no API)
  get canCurrentUserDuplicatePage() {
    return false;
  }

  get canCurrentUserLockPage() {
    return this.isCurrentUserOwner || this.isWorkspaceAdmin;
  }

  // the API only lets the owner change access
  get canCurrentUserChangeAccess() {
    return this.isCurrentUserOwner;
  }

  get canCurrentUserArchivePage() {
    return this.isCurrentUserOwner || this.isWorkspaceAdmin;
  }

  get canCurrentUserDeletePage() {
    return this.isCurrentUserOwner || this.isWorkspaceAdmin;
  }

  // favourites are a project feature
  get canCurrentUserFavoritePage() {
    return false;
  }

  // moving between projects does not apply to wiki pages
  get canCurrentUserMovePage() {
    return false;
  }

  /**
   * @description returns true if the page can be edited
   */
  get isContentEditable() {
    const isPublic = this.access === EPageAccess.PUBLIC;
    return !this.archived_at && !this.is_locked && (this.isCurrentUserOwner || (isPublic && this.isWorkspaceMember));
  }

  getRedirectionLink = computedFn(() => {
    const { workspaceSlug } = this.rootStore.router;
    return `/${workspaceSlug}/wiki/${this.id}`;
  });
}
