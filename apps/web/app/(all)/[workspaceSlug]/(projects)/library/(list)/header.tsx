/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { LibraryOutline } from "@makeplane/propel/icons";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { Header } from "@plane/blocks/layout";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
// hooks
import { useInstance } from "@/hooks/store/use-instance";
import { useLibrary } from "@/hooks/store/use-library";
import { useUserPermissions } from "@/hooks/store/user";

export const LibraryListHeader = observer(function LibraryListHeader() {
  const { openUploadDialog } = useLibrary();
  const { config } = useInstance();
  const { allowPermissions } = useUserPermissions();
  // guests have no library access; the API refuses them too
  const canUpload =
    !!config?.is_library_enabled &&
    allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.WORKSPACE);

  return (
    <Header>
      <Header.LeftItem>
        <Breadcrumbs>
          <Breadcrumbs.Item
            component={<BreadcrumbLink label="Library" icon={<LibraryOutline className="h-4 w-4 text-tertiary" />} />}
          />
        </Breadcrumbs>
      </Header.LeftItem>
      <Header.RightItem>
        {canUpload && (
          <Button variant="primary" size="md" stretch="auto" label="Upload books" onClick={() => openUploadDialog()} />
        )}
      </Header.RightItem>
    </Header>
  );
});
