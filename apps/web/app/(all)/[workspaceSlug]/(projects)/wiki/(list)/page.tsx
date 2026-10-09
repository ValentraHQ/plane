/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { EmptyStateDetailed } from "@plane/blocks/empty-state";
import type { TPageNavigationTabs } from "@plane/types";
// components
import { PageHead } from "@/components/core/page-title";
import { PagesListHeaderRoot } from "@/components/pages/header";
import { PagesListRoot } from "@/components/pages/list/root";
import { PageLoader } from "@/components/pages/loaders/page-loader";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import type { Route } from "./+types/page";

const storeType = EPageStoreType.WORKSPACE;

const getPageType = (pageType?: string | null): TPageNavigationTabs => {
  if (pageType === "private") return "private";
  if (pageType === "archived") return "archived";
  return "public";
};

function WikiPagesPage({ params }: Route.ComponentProps) {
  const { workspaceSlug } = params;
  const searchParams = useSearchParams();
  const pageType = getPageType(searchParams.get("type"));
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const {
    fetchPagesList,
    isAnyPageAvailable,
    loader,
    getCurrentProjectPageIdsByTab,
    getCurrentProjectFilteredPageIdsByTab,
  } = usePageStore(storeType);
  // fetch the top-level wiki pages
  useSWR(workspaceSlug ? `WIKI_PAGES_${workspaceSlug}` : null, () => fetchPagesList(workspaceSlug, ""));
  // derived values
  const pageIds = getCurrentProjectPageIdsByTab(pageType);
  const filteredPageIds = getCurrentProjectFilteredPageIdsByTab(pageType);

  const renderContent = () => {
    if (loader === "init-loader") return <PageLoader />;
    if (pageIds?.length === 0)
      return (
        <EmptyStateDetailed
          assetKey="page"
          title={
            pageType === "archived"
              ? t("project_empty_state.archive_pages.title")
              : t("workspace_empty_state.wiki.title")
          }
          description={
            pageType === "archived"
              ? t("project_empty_state.archive_pages.description")
              : "Wiki pages belong to the whole workspace, not to a project. Use Add page to start, and Add sub-page to build the tree."
          }
        />
      );
    if (filteredPageIds?.length === 0)
      return (
        <EmptyStateDetailed
          assetKey="search"
          title={t("common_empty_state.search.title")}
          description={t("common_empty_state.search.description")}
        />
      );
    return (
      <div className="h-full w-full overflow-hidden">
        <PagesListRoot pageType={pageType} storeType={storeType} />
      </div>
    );
  };

  return (
    <>
      <PageHead title="Wiki" />
      <div className="relative flex h-full w-full flex-col overflow-hidden">
        {isAnyPageAvailable && (
          <PagesListHeaderRoot pageType={pageType} projectId="" storeType={storeType} workspaceSlug={workspaceSlug} />
        )}
        {renderContent()}
      </div>
    </>
  );
}

export default observer(WikiPagesPage);
