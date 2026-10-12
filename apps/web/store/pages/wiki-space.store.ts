/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { set, sortBy, unset } from "lodash-es";
import { action, computed, makeObservable, observable, runInAction } from "mobx";
import { computedFn } from "mobx-utils";
// types
import type { TPage, TWikiPageMovePayload, TWikiSpace, TWikiSpaceMember } from "@plane/types";
import { EWikiSpaceRole } from "@plane/types";
// services
import { WikiSpaceService, WorkspacePageService } from "@/services/page";
// store
import type { CoreRootStore } from "../root.store";

export interface IWikiSpaceStore {
  // observables
  spaces: Record<string, TWikiSpace>;
  members: Record<string, TWikiSpaceMember[]>;
  isLoading: boolean;
  currentSpaceId: string | undefined;
  // computed
  spaceIds: string[];
  currentSpace: TWikiSpace | undefined;
  // helpers
  getSpaceById: (spaceId: string | null | undefined) => TWikiSpace | undefined;
  getSpaceRole: (spaceId: string | null | undefined) => EWikiSpaceRole | null;
  getTreeChildIds: (spaceId: string, parentId: string | null) => string[];
  setCurrentSpace: (spaceId: string | undefined) => void;
  // actions
  fetchSpaces: (workspaceSlug: string) => Promise<TWikiSpace[]>;
  fetchSpace: (workspaceSlug: string, spaceId: string) => Promise<TWikiSpace>;
  createSpace: (workspaceSlug: string, data: Partial<TWikiSpace>) => Promise<TWikiSpace>;
  updateSpace: (workspaceSlug: string, spaceId: string, data: Partial<TWikiSpace>) => Promise<TWikiSpace>;
  deleteSpace: (workspaceSlug: string, spaceId: string) => Promise<void>;
  fetchTree: (workspaceSlug: string, spaceId: string) => Promise<void>;
  movePage: (workspaceSlug: string, pageId: string, payload: TWikiPageMovePayload) => Promise<void>;
  fetchMembers: (workspaceSlug: string, spaceId: string) => Promise<TWikiSpaceMember[]>;
  addMember: (
    workspaceSlug: string,
    spaceId: string,
    data: Pick<TWikiSpaceMember, "member" | "role">
  ) => Promise<TWikiSpaceMember>;
  updateMember: (workspaceSlug: string, spaceId: string, membershipId: string, role: EWikiSpaceRole) => Promise<void>;
  removeMember: (workspaceSlug: string, spaceId: string, membershipId: string) => Promise<void>;
}

const spaceService = new WikiSpaceService();
const pageService = new WorkspacePageService();

/**
 * Documentation spaces of the workspace wiki. Tree pages are stored in the workspace page store,
 * so renames, moves and archives made anywhere show up in the sidebar tree as well.
 */
export class WikiSpaceStore implements IWikiSpaceStore {
  spaces: Record<string, TWikiSpace> = {};
  members: Record<string, TWikiSpaceMember[]> = {};
  isLoading = false;
  currentSpaceId: string | undefined = undefined;

  constructor(private store: CoreRootStore) {
    makeObservable(this, {
      spaces: observable,
      members: observable,
      isLoading: observable.ref,
      currentSpaceId: observable.ref,
      spaceIds: computed,
      currentSpace: computed,
      setCurrentSpace: action,
      fetchSpaces: action,
      fetchSpace: action,
      createSpace: action,
      updateSpace: action,
      deleteSpace: action,
      fetchTree: action,
      movePage: action,
      fetchMembers: action,
      addMember: action,
      updateMember: action,
      removeMember: action,
    });
  }

  get spaceIds() {
    // the default space first, then by name
    return sortBy(Object.values(this.spaces), [(space) => !space.is_default, (space) => space.name.toLowerCase()]).map(
      (space) => space.id
    );
  }

  get currentSpace() {
    return this.currentSpaceId ? this.spaces[this.currentSpaceId] : undefined;
  }

  getSpaceById = computedFn((spaceId: string | null | undefined) => (spaceId ? this.spaces[spaceId] : undefined));

  getSpaceRole = computedFn((spaceId: string | null | undefined) => this.getSpaceById(spaceId)?.my_role ?? null);

  /**
   * @description visible, non-archived pages of a space under parentId (null = top level), in tree order
   */
  getTreeChildIds = computedFn((spaceId: string, parentId: string | null) =>
    sortBy(
      Object.values(this.store.workspacePages.data).filter(
        (page) => page.space === spaceId && !page.archived_at && (page.parent ?? null) === parentId
      ),
      [(page) => page.sort_order ?? 0, (page) => (page.name ?? "").toLowerCase()]
    ).map((page) => page.id as string)
  );

  setCurrentSpace = (spaceId: string | undefined) => {
    this.currentSpaceId = spaceId;
  };

  fetchSpaces = async (workspaceSlug: string) => {
    runInAction(() => {
      this.isLoading = true;
    });
    try {
      const spaces = await spaceService.fetchAll(workspaceSlug);
      runInAction(() => {
        this.spaces = {};
        spaces.forEach((space) => set(this.spaces, [space.id], space));
      });
      return spaces;
    } finally {
      runInAction(() => {
        this.isLoading = false;
      });
    }
  };

  fetchSpace = async (workspaceSlug: string, spaceId: string) => {
    const space = await spaceService.fetchById(workspaceSlug, spaceId);
    runInAction(() => set(this.spaces, [space.id], space));
    return space;
  };

  createSpace = async (workspaceSlug: string, data: Partial<TWikiSpace>) => {
    const space = await spaceService.create(workspaceSlug, data);
    runInAction(() => set(this.spaces, [space.id], space));
    return space;
  };

  updateSpace = async (workspaceSlug: string, spaceId: string, data: Partial<TWikiSpace>) => {
    const space = await spaceService.update(workspaceSlug, spaceId, data);
    runInAction(() => set(this.spaces, [space.id], space));
    return space;
  };

  deleteSpace = async (workspaceSlug: string, spaceId: string) => {
    await spaceService.remove(workspaceSlug, spaceId);
    runInAction(() => {
      unset(this.spaces, [spaceId]);
      unset(this.members, [spaceId]);
      if (this.currentSpaceId === spaceId) this.currentSpaceId = undefined;
    });
  };

  fetchTree = async (workspaceSlug: string, spaceId: string) => {
    const nodes = await spaceService.fetchTree(workspaceSlug, spaceId);
    runInAction(() => {
      // the tree endpoint returns lightweight pages; merge them into the shared page store
      this.store.workspacePages.upsertPages(nodes as unknown as TPage[]);
    });
  };

  movePage = async (workspaceSlug: string, pageId: string, payload: TWikiPageMovePayload) => {
    const sourceSpaceId = this.store.workspacePages.getPageById(pageId)?.space ?? undefined;
    const page = await pageService.move(workspaceSlug, pageId, payload);
    runInAction(() => this.store.workspacePages.upsertPages([page]));
    // a move to another space takes the sub-tree along: reload both trees
    const spaceIds = new Set([sourceSpaceId, page.space ?? undefined].filter(Boolean) as string[]);
    await Promise.all([...spaceIds].map((spaceId) => this.fetchTree(workspaceSlug, spaceId)));
  };

  fetchMembers = async (workspaceSlug: string, spaceId: string) => {
    const members = await spaceService.fetchMembers(workspaceSlug, spaceId);
    runInAction(() => set(this.members, [spaceId], members));
    return members;
  };

  addMember = async (workspaceSlug: string, spaceId: string, data: Pick<TWikiSpaceMember, "member" | "role">) => {
    const membership = await spaceService.addMember(workspaceSlug, spaceId, data);
    await this.fetchMembers(workspaceSlug, spaceId);
    return membership;
  };

  updateMember = async (workspaceSlug: string, spaceId: string, membershipId: string, role: EWikiSpaceRole) => {
    await spaceService.updateMember(workspaceSlug, spaceId, membershipId, { role });
    await this.fetchMembers(workspaceSlug, spaceId);
  };

  removeMember = async (workspaceSlug: string, spaceId: string, membershipId: string) => {
    await spaceService.removeMember(workspaceSlug, spaceId, membershipId);
    await this.fetchMembers(workspaceSlug, spaceId);
  };
}

export const canWriteInSpace = (role: EWikiSpaceRole | null | undefined) => !!role && role >= EWikiSpaceRole.EDITOR;
