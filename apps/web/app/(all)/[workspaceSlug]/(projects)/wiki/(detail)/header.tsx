/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { PagesOutline } from "@makeplane/propel/icons";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { Header } from "@plane/blocks/layout";
import { getPageName } from "@plane/utils";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { SwitcherIcon } from "@/components/common/switcher-label";
import { PageHeaderActions } from "@/components/pages/header/actions";
import { PageSyncingBadge } from "@/components/pages/header/syncing-badge";
// hooks
import { EPageStoreType, usePage, usePageStore } from "@/hooks/store";

const storeType = EPageStoreType.WORKSPACE;
// guards the ancestor walk against unexpectedly deep or cyclic data
const MAX_PAGE_ANCESTORS = 20;

export const WikiPageDetailsHeader = observer(function WikiPageDetailsHeader() {
  // router
  const { workspaceSlug, pageId } = useParams();
  // store hooks
  const { getPageById, fetchPageDetails } = usePageStore(storeType);
  const page = usePage({
    pageId: pageId?.toString() ?? "",
    storeType,
  });
  // ancestors of a sub-page, nearest last; stops at the first ancestor not loaded yet
  const ancestors: NonNullable<ReturnType<typeof getPageById>>[] = [];
  let missingAncestorId: string | undefined;
  for (let parentId = page?.parent; parentId && ancestors.length < MAX_PAGE_ANCESTORS; ) {
    const ancestor = getPageById(parentId);
    if (!ancestor) {
      missingAncestorId = parentId;
      break;
    }
    if (ancestors.includes(ancestor)) break;
    ancestors.unshift(ancestor);
    parentId = ancestor.parent;
  }

  // load ancestors one level at a time when a sub-page is opened directly
  useEffect(() => {
    if (!missingAncestorId || !workspaceSlug) return;
    fetchPageDetails(workspaceSlug.toString(), "", missingAncestorId).catch(() => undefined);
  }, [missingAncestorId, workspaceSlug, fetchPageDetails]);

  if (!page) return null;

  return (
    <Header>
      <Header.LeftItem>
        <div>
          <Breadcrumbs>
            <Breadcrumbs.Item
              component={
                <BreadcrumbLink
                  label="Wiki"
                  href={`/${workspaceSlug}/wiki/`}
                  icon={<PagesOutline className="h-4 w-4 text-tertiary" />}
                />
              }
            />
            {ancestors.map((ancestor) => (
              <Breadcrumbs.Item
                key={ancestor.id}
                component={
                  <BreadcrumbLink
                    label={getPageName(ancestor.name)}
                    href={`/${workspaceSlug}/wiki/${ancestor.id}`}
                    icon={<SwitcherIcon logo_props={ancestor.logo_props} LabelIcon={PagesOutline} size={16} />}
                  />
                }
              />
            ))}
            <Breadcrumbs.Item
              component={
                <BreadcrumbLink
                  label={getPageName(page.name)}
                  icon={<SwitcherIcon logo_props={page.logo_props} LabelIcon={PagesOutline} size={16} />}
                />
              }
              isLast
            />
          </Breadcrumbs>
        </div>
      </Header.LeftItem>
      <Header.RightItem>
        <PageSyncingBadge syncStatus={page.isSyncingWithServer} />
        <PageHeaderActions page={page} storeType={storeType} />
      </Header.RightItem>
    </Header>
  );
});
