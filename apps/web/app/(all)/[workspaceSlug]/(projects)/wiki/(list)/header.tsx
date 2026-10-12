/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { PagesOutline } from "@makeplane/propel/icons";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { Header } from "@plane/blocks/layout";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { WikiSpaceFormModal } from "@/components/wiki/space-form-modal";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";

export const WikiPagesListHeader = observer(function WikiPagesListHeader() {
  const { workspaceSlug } = useParams();
  const router = useAppRouter();
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  return (
    <>
      <Header>
        <Header.LeftItem>
          <Breadcrumbs>
            <Breadcrumbs.Item
              component={<BreadcrumbLink label="Wiki" icon={<PagesOutline className="h-4 w-4 text-tertiary" />} />}
            />
          </Breadcrumbs>
        </Header.LeftItem>
        <Header.RightItem>
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            label="Create space"
            onClick={() => setIsCreateOpen(true)}
          />
        </Header.RightItem>
      </Header>
      <WikiSpaceFormModal
        workspaceSlug={workspaceSlug?.toString() ?? ""}
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onSaved={(space) => router.push(`/${workspaceSlug}/wiki/spaces/${space.id}`)}
      />
    </>
  );
});
