/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { unset, set } from "lodash-es";
import { makeObservable, observable, runInAction, action, computed } from "mobx";
import { computedFn } from "mobx-utils";
// types
import { EUserPermissions } from "@plane/constants";
import type { TPage, TPageFilters, TPageNavigationTabs } from "@plane/types";
// helpers
import { filterPagesByPageType, getPageName, orderPages, shouldFilterPage } from "@plane/utils";
// services
import { WorkspacePageService } from "@/services/page";
// store
import type { CoreRootStore } from "../root.store";
import type { IProjectPageStore } from "./project-page.store";
import type { TWorkspacePage } from "./workspace-page";
import { WorkspacePage } from "./workspace-page";

type TLoader = "init-loader" | "mutation-loader" | undefined;

type TError = { title: string; description: string };

/**
 * Store for the workspace wiki. It implements the same interface as the project page store so the
 * shared page list, block and action components work with either; the projectId arguments of that
 * interface are ignored here because wiki pages belong to the workspace.
 */
export type IWorkspacePageStore = IProjectPageStore;

export class WorkspacePageStore implements IWorkspacePageStore {
  // observables
  loader: TLoader = "init-loader";
  data: Record<string, TWorkspacePage> = {}; // pageId => Page
  error: TError | undefined = undefined;
  filters: TPageFilters = {
    searchQuery: "",
    sortKey: "updated_at",
    sortBy: "desc",
  };
  // service
  service: WorkspacePageService;

  constructor(private store: CoreRootStore) {
    makeObservable(this, {
      // observables
      loader: observable.ref,
      data: observable,
      error: observable,
      filters: observable,
      // computed
      isAnyPageAvailable: computed,
      canCurrentUserCreatePage: computed,
      // helper actions
      updateFilters: action,
      clearAllFilters: action,
      // actions
      fetchPagesList: action,
      fetchPageDetails: action,
      fetchSubPages: action,
      createPage: action,
      removePage: action,
      movePage: action,
    });
    this.service = new WorkspacePageService();
  }

  /**
   * @description check if any wiki page is available
   */
  get isAnyPageAvailable() {
    if (this.loader) return true;
    return Object.keys(this.data).length > 0;
  }

  /**
   * @description workspace admins and members can write in the wiki; guests cannot
   */
  get canCurrentUserCreatePage() {
    const { workspaceSlug } = this.store.router;
    if (!workspaceSlug) return false;
    const role = this.store.user.permission.getWorkspaceRoleByWorkspaceSlug(workspaceSlug.toString()) as
      | number
      | undefined;
    return !!role && role >= EUserPermissions.MEMBER;
  }

  private get pagesInWorkspace() {
    const { workspaceSlug } = this.store.router;
    if (!workspaceSlug) return [];
    // pages are loaded per workspace; drop any left from another workspace
    const workspaceId = this.store.workspaceRoot.getWorkspaceBySlug(workspaceSlug.toString())?.id;
    return Object.values(this.data).filter((p) => !workspaceId || p.workspace === workspaceId);
  }

  getCurrentProjectPageIdsByTab = computedFn((pageType: TPageNavigationTabs) => {
    const pagesByType = filterPagesByPageType(pageType, this.pagesInWorkspace);
    return pagesByType.map((page) => page.id) as string[];
  });

  getCurrentProjectPageIds = computedFn((_projectId: string) => this.pagesInWorkspace.map((p) => p.id) as string[]);

  getCurrentProjectFilteredPageIdsByTab = computedFn((pageType: TPageNavigationTabs) => {
    const pagesByType = filterPagesByPageType(pageType, this.pagesInWorkspace);
    let filteredPages = pagesByType.filter(
      (p) =>
        getPageName(p.name).toLowerCase().includes(this.filters.searchQuery.toLowerCase()) &&
        shouldFilterPage(p, this.filters.filters)
    );
    // Without a search, a sub-page is listed under its parent rather than at the top level,
    // unless the parent is not part of this tab (e.g. a private page under a public parent).
    if (!this.filters.searchQuery) {
      const pageIdsInTab = new Set(pagesByType.map((p) => p.id));
      filteredPages = filteredPages.filter((p) => !p.parent || !pageIdsInTab.has(p.parent));
    }
    filteredPages = orderPages(filteredPages, this.filters.sortKey, this.filters.sortBy);
    return filteredPages.map((page) => page.id) as string[];
  });

  getSubPageIds = computedFn((parentId: string) => {
    const parent = this.data?.[parentId];
    if (!parent) return [];
    const subPages = Object.values(this.data).filter(
      (p) => p.parent === parentId && !!p.archived_at === !!parent.archived_at
    );
    return orderPages(subPages, this.filters.sortKey, this.filters.sortBy).map((p) => p.id) as string[];
  });

  getPageById = computedFn((pageId: string) => this.data?.[pageId] || undefined);

  updateFilters = <T extends keyof TPageFilters>(filterKey: T, filterValue: TPageFilters[T]) => {
    runInAction(() => {
      set(this.filters, [filterKey], filterValue);
    });
  };

  clearAllFilters = () =>
    runInAction(() => {
      set(this.filters, ["filters"], {});
    });

  private mergePages(pages: TPage[]) {
    for (const page of pages) {
      if (!page?.id) continue;
      const existingPage = this.getPageById(page.id);
      if (existingPage) {
        const { name, ...otherFields } = page;
        existingPage.mutateProperties(otherFields, false);
      } else {
        set(this.data, [page.id], new WorkspacePage(this.store, page));
      }
    }
  }

  /**
   * @description fetch the top-level wiki pages
   */
  fetchPagesList = async (workspaceSlug: string, _projectId?: string, pageType?: TPageNavigationTabs) => {
    try {
      if (!workspaceSlug) return undefined;
      const currentPageIds = pageType ? this.getCurrentProjectPageIdsByTab(pageType) : undefined;
      runInAction(() => {
        this.loader = currentPageIds && currentPageIds.length > 0 ? "mutation-loader" : "init-loader";
        this.error = undefined;
      });
      const pages = await this.service.fetchAll(workspaceSlug);
      runInAction(() => {
        this.mergePages(pages);
        this.loader = undefined;
      });
      return pages;
    } catch (error) {
      runInAction(() => {
        this.loader = undefined;
        this.error = { title: "Failed", description: "Failed to fetch the wiki pages, Please try again later." };
      });
      throw error;
    }
  };

  fetchPageDetails = async (...args: Parameters<IWorkspacePageStore["fetchPageDetails"]>) => {
    const [workspaceSlug, , pageId] = args;
    try {
      if (!workspaceSlug || !pageId) return undefined;
      const page = await this.service.fetchById(workspaceSlug, pageId);
      runInAction(() => {
        this.mergePages([page]);
        // a single-page load should not leave the list in its initial loading state
        if (this.loader === "init-loader" && Object.keys(this.data).length > 0) this.loader = undefined;
      });
      return page;
    } catch (error) {
      runInAction(() => {
        this.error = { title: "Failed", description: "Failed to fetch the page, Please try again later." };
      });
      throw error;
    }
  };

  /**
   * @description fetch the direct sub-pages of a wiki page and merge them into the store
   */
  fetchSubPages = async (workspaceSlug: string, _projectId: string, parentId: string) => {
    if (!workspaceSlug || !parentId) return undefined;
    const pages = await this.service.fetchAll(workspaceSlug, { parent_id: parentId });
    runInAction(() => {
      this.mergePages(pages);
      const parent = this.getPageById(parentId);
      if (parent) parent.mutateProperties({ sub_pages_count: pages.filter((p) => !p.archived_at).length }, false);
    });
    return pages;
  };

  createPage = async (pageData: Partial<TPage>) => {
    try {
      const { workspaceSlug } = this.store.router;
      if (!workspaceSlug) return undefined;
      runInAction(() => {
        this.loader = "mutation-loader";
        this.error = undefined;
      });
      const page = await this.service.create(workspaceSlug.toString(), pageData);
      runInAction(() => {
        if (page?.id) set(this.data, [page.id], new WorkspacePage(this.store, page));
        const parent = page?.parent ? this.getPageById(page.parent) : undefined;
        if (parent) parent.mutateProperties({ sub_pages_count: (parent.sub_pages_count ?? 0) + 1 }, false);
        this.loader = undefined;
      });
      return page;
    } catch (error) {
      runInAction(() => {
        this.loader = undefined;
        this.error = { title: "Failed", description: "Failed to create a page, Please try again later." };
      });
      throw error;
    }
  };

  removePage = async ({ pageId }: { pageId: string; shouldSync?: boolean }) => {
    const { workspaceSlug } = this.store.router;
    if (!workspaceSlug || !pageId) return undefined;
    await this.service.remove(workspaceSlug.toString(), pageId);
    runInAction(() => {
      // sub-pages of a deleted page move to the top level on the server
      Object.values(this.data).forEach((p) => {
        if (p.parent === pageId) p.mutateProperties({ parent: null }, false);
      });
      unset(this.data, [pageId]);
    });
  };

  /**
   * @description moving between projects does not apply to wiki pages
   */
  movePage = async () => {
    throw new Error("Wiki pages cannot be moved to a project.");
  };
}
