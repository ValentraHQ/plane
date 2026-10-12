/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/elements/button";
import { GlobeOutline, LockOutline } from "@makeplane/propel/icons";
import { EmptyStateDetailed } from "@plane/blocks/empty-state";
import type { TPageNavigationTabs } from "@plane/types";
import { EWikiSpaceAccess } from "@plane/types";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PageHead } from "@/components/core/page-title";
import { PagesListHeaderRoot } from "@/components/pages/header";
import { PagesListRoot } from "@/components/pages/list/root";
import { PageLoader } from "@/components/pages/loaders/page-loader";
import { WikiShell } from "@/components/wiki/shell";
import { WikiSpaceIcon } from "@/components/wiki/space-switcher";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";
import type { Route } from "./+types/page";

const storeType = EPageStoreType.WORKSPACE;

const getPageType = (pageType?: string | null): TPageNavigationTabs => {
  if (pageType === "private") return "private";
  if (pageType === "archived") return "archived";
  return "public";
};

/** Space home: what the space is, and its pages (tabs, search, filters, tree list). */
function WikiSpaceHomePage({ params }: Route.ComponentProps) {
  const { workspaceSlug, spaceId } = params;
  const searchParams = useSearchParams();
  const pageType = getPageType(searchParams.get("type"));
  // store hooks
  const { fetchSpace, getSpaceById, currentSpaceId } = useWikiSpaces();
  const { fetchPagesList, loader, getCurrentProjectPageIdsByTab, getCurrentProjectFilteredPageIdsByTab } =
    usePageStore(storeType);
  // load the space (also tells us the user's role in it)
  const { error: spaceError } = useSWR(`WIKI_SPACE_${spaceId}`, () => fetchSpace(workspaceSlug, spaceId));
  // the list is fetched for the current space, which WikiShell sets
  useSWR(currentSpaceId === spaceId ? `WIKI_SPACE_PAGES_${spaceId}` : null, () => fetchPagesList(workspaceSlug, ""));
  // derived values
  const space = getSpaceById(spaceId);
  const pageIds = getCurrentProjectPageIdsByTab(pageType);
  const filteredPageIds = getCurrentProjectFilteredPageIdsByTab(pageType);

  if (spaceError)
    return (
      <div className="flex h-full w-full flex-col items-center justify-center">
        <h3 className="text-center text-16 font-semibold">Space not found</h3>
        <p className="mt-3 text-center text-13 text-secondary">
          The space doesn{"'"}t exist or you don{"'"}t have access to it.
        </p>
        <Button
          variant="secondary"
          size="sm"
          stretch="auto"
          render={<Link href={`/${workspaceSlug}/wiki`} className="mt-5" />}
        >
          All spaces
        </Button>
      </div>
    );

  if (!space)
    return (
      <div className="grid size-full place-items-center">
        <LogoSpinner />
      </div>
    );

  const isRestricted = space.access === EWikiSpaceAccess.RESTRICTED;

  const renderPages = () => {
    if (loader === "init-loader") return <PageLoader />;
    if (pageIds?.length === 0)
      return (
        <EmptyStateDetailed
          assetKey="page"
          title={pageType === "archived" ? "No archived pages" : "No pages here yet"}
          description={
            pageType === "archived"
              ? "Archived pages of this space appear here."
              : "Use New page to start this space, then add sub-pages to build its tree."
          }
        />
      );
    if (filteredPageIds?.length === 0)
      return <EmptyStateDetailed assetKey="search" title="No matching pages" description="Try a different search." />;
    return <PagesListRoot pageType={pageType} storeType={storeType} />;
  };

  return (
    <>
      <PageHead title={space.name} />
      <WikiShell workspaceSlug={workspaceSlug} spaceId={spaceId}>
        <div className="flex h-full flex-col overflow-hidden">
          <section className="flex flex-shrink-0 items-start gap-3 border-b border-subtle px-4 py-4 sm:px-6">
            <span className="grid size-10 flex-shrink-0 place-items-center rounded-lg bg-layer-2">
              <WikiSpaceIcon logo_props={space.logo_props} size={20} />
            </span>
            <div className="min-w-0">
              <h1 className="truncate text-18 font-semibold text-primary">{space.name}</h1>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-12 text-tertiary">
                <span>{space.identifier}</span>
                <span className="flex items-center gap-1">
                  {isRestricted ? <LockOutline className="size-3" /> : <GlobeOutline className="size-3" />}
                  {isRestricted ? "Restricted" : "Open"}
                </span>
                <span>
                  {space.page_count} {space.page_count === 1 ? "page" : "pages"}
                </span>
              </p>
              {space.description && <p className="mt-2 max-w-3xl text-13 text-secondary">{space.description}</p>}
            </div>
          </section>
          <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
            <PagesListHeaderRoot
              pageType={pageType}
              projectId=""
              storeType={storeType}
              workspaceSlug={workspaceSlug}
              tabsBasePath={`/${workspaceSlug}/wiki/spaces/${spaceId}`}
            />
            <div className="min-h-0 flex-1 overflow-hidden">{renderPages()}</div>
          </div>
        </div>
      </WikiShell>
    </>
  );
}

export default observer(WikiSpaceHomePage);
