/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { computed, makeObservable } from "mobx";
import { computedFn } from "mobx-utils";
// constants
import { EPageAccess } from "@plane/constants";
import type { TPage } from "@plane/types";
import { EWikiSpaceRole } from "@plane/types";
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
      fetchRestrictions: async () => {
        const { slug, pageId } = requireIds();
        return await workspacePageService.fetchRestrictions(slug, pageId);
      },
      updateRestrictions: async (payload) => {
        const { slug, pageId } = requireIds();
        return await workspacePageService.updateRestrictions(slug, pageId, payload);
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
      canCurrentUserChangeRestrictions: computed,
      isContentEditable: computed,
    });
  }

  /**
   * Same rules as the API (plane.utils.wiki_permissions): the space role decides,
   * page access (public/private) narrows who can see the page.
   */
  private get spaceRole() {
    return this.rootStore.wikiSpaces.getSpaceRole(this.space);
  }

  private get canView() {
    return this.access === EPageAccess.PUBLIC || this.isCurrentUserOwner;
  }

  private get canEdit() {
    return this.canView && !!this.spaceRole && this.spaceRole >= EWikiSpaceRole.EDITOR;
  }

  // lock, archive, delete, move: a space admin, or the owner while still an editor
  private get canManage() {
    return this.canView && (this.spaceRole === EWikiSpaceRole.ADMIN || (this.isCurrentUserOwner && this.canEdit));
  }

  get canCurrentUserAccessPage() {
    return this.canView && this.serverAllows("can_view");
  }

  get canCurrentUserEditPage() {
    return this.canEdit && this.serverAllows("can_edit");
  }

  // not supported for wiki pages yet (no API)
  get canCurrentUserDuplicatePage() {
    return false;
  }

  get canCurrentUserLockPage() {
    return this.canManage && this.serverAllows("can_manage");
  }

  // the API only lets the owner change access
  get canCurrentUserChangeAccess() {
    return this.isCurrentUserOwner && this.canEdit && this.serverAllows("can_manage");
  }

  get canCurrentUserArchivePage() {
    return this.canManage && this.serverAllows("can_manage");
  }

  get canCurrentUserDeletePage() {
    return this.canManage && this.serverAllows("can_manage");
  }

  // favourites are a project feature
  get canCurrentUserFavoritePage() {
    return false;
  }

  // moving within/between documentation spaces (tree drag-and-drop, Move to…)
  get canCurrentUserMovePage() {
    return this.canManage && !this.archived_at && this.serverAllows("can_manage");
  }

  // who may view / edit the page and its sub-pages
  get canCurrentUserChangeRestrictions() {
    return this.canManage && this.serverAllows("can_manage");
  }

  /**
   * @description returns true if the page content can be edited right now
   */
  get isContentEditable() {
    return !this.archived_at && !this.is_locked && this.canEdit && this.serverAllows("can_edit");
  }

  getRedirectionLink = computedFn(() => {
    const { workspaceSlug } = this.rootStore.router;
    return `/${workspaceSlug}/wiki/${this.id}`;
  });
}
