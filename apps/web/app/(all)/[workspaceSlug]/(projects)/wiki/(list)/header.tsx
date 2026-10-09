/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useSearchParams } from "next/navigation";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { PagesOutline } from "@makeplane/propel/icons";
import { EPageAccess } from "@plane/constants";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { Header } from "@plane/blocks/layout";
import { setToast } from "@plane/blocks/toast";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useAppRouter } from "@/hooks/use-app-router";

const storeType = EPageStoreType.WORKSPACE;

export const WikiPagesListHeader = observer(function WikiPagesListHeader() {
  // states
  const [isCreatingPage, setIsCreatingPage] = useState(false);
  // router
  const router = useAppRouter();
  const searchParams = useSearchParams();
  // store hooks
  const { canCurrentUserCreatePage, createPage, getPageById } = usePageStore(storeType);

  const handleCreatePage = async () => {
    setIsCreatingPage(true);
    try {
      // a page created from the Private tab starts private
      const access = searchParams.get("type") === "private" ? EPageAccess.PRIVATE : EPageAccess.PUBLIC;
      const page = await createPage({ access });
      const link = page?.id ? getPageById(page.id)?.getRedirectionLink() : undefined;
      if (link) router.push(link);
    } catch (err) {
      setToast({
        type: "error",
        title: "Error!",
        message: (err as { error?: string })?.error || "Page could not be created. Please try again.",
      });
    } finally {
      setIsCreatingPage(false);
    }
  };

  return (
    <Header>
      <Header.LeftItem>
        <Breadcrumbs>
          <Breadcrumbs.Item
            component={<BreadcrumbLink label="Wiki" icon={<PagesOutline className="h-4 w-4 text-tertiary" />} />}
          />
        </Breadcrumbs>
      </Header.LeftItem>
      {canCurrentUserCreatePage && (
        <Header.RightItem>
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            label={isCreatingPage ? "Adding..." : "Add page"}
            onClick={handleCreatePage}
            disabled={isCreatingPage}
          />
        </Header.RightItem>
      )}
    </Header>
  );
});
