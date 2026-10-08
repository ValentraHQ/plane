/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { redirect } from "react-router";
import { SHOW_UPGRADE_PROMPTS } from "@plane/constants";
// components
import { PageHead } from "@/components/core/page-title";
// hooks
import { useWorkspace } from "@/hooks/store/use-workspace";
// local imports
import { WorkspaceActiveCyclesUpgrade } from "@/components/active-cycles/workspace-active-cycles-upgrade";
import type { Route } from "./+types/page";

export function clientLoader({ params }: Route.ClientLoaderArgs) {
  // This page is only an upgrade advert in the Community Edition
  if (!SHOW_UPGRADE_PROMPTS) throw redirect(`/${params.workspaceSlug}/`);
  return null;
}

function WorkspaceActiveCyclesPage() {
  const { currentWorkspace } = useWorkspace();
  // derived values
  const pageTitle = currentWorkspace?.name ? `${currentWorkspace?.name} - Active Cycles` : undefined;

  return (
    <>
      <PageHead title={pageTitle} />
      <WorkspaceActiveCyclesUpgrade />
    </>
  );
}

export default observer(WorkspaceActiveCyclesPage);
