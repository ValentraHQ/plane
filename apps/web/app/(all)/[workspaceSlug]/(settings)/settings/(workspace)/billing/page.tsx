/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { redirect } from "react-router";
// component
import { EUserPermissions, EUserPermissionsLevel, SHOW_UPGRADE_PROMPTS } from "@plane/constants";
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
// hooks
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { BillingWorkspaceSettingsHeader } from "./header";
import { BillingRoot } from "@/components/workspace/billing";
import type { Route } from "./+types/page";

export function clientLoader({ params }: Route.ClientLoaderArgs) {
  // Billing & plans is an upsell-only page; send users back to settings when upsells are off
  if (!SHOW_UPGRADE_PROMPTS) throw redirect(`/${params.workspaceSlug}/settings/`);
  return null;
}

function BillingSettingsPage() {
  // store hooks
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { currentWorkspace } = useWorkspace();
  // derived values
  const canPerformWorkspaceAdminActions = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);
  const pageTitle = currentWorkspace?.name ? `${currentWorkspace.name} - Billing & Plans` : undefined;

  if (workspaceUserInfo && !canPerformWorkspaceAdminActions) {
    return <NotAuthorizedView section="settings" className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<BillingWorkspaceSettingsHeader />} hugging>
      <PageHead title={pageTitle} />
      <BillingRoot />
    </SettingsContentWrapper>
  );
}

export default observer(BillingSettingsPage);
