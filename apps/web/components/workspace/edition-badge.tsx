/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// ui
import { SHOW_UPGRADE_PROMPTS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Tooltip } from "@makeplane/propel/components/tooltip";
// hooks
import { usePlatformOS } from "@/hooks/use-platform-os";
import packageJson from "package.json";
// local components
import { Button } from "@makeplane/propel/components/button";
import { PaidPlanUpgradeModal } from "@/components/license/modal/upgrade-modal";

export const WorkspaceEditionBadge = observer(function WorkspaceEditionBadge() {
  // states
  const [isPaidPlanPurchaseModalOpen, setIsPaidPlanPurchaseModalOpen] = useState(false);
  // translation
  const { t } = useTranslation();
  // platform
  const { isMobile } = usePlatformOS();

  // Without upsells the badge only shows the edition and version
  if (!SHOW_UPGRADE_PROMPTS) {
    return (
      <Tooltip label={`Version: v${packageJson.version}`} disabled={isMobile}>
        <span className="px-2 text-13 font-medium text-tertiary">Community</span>
      </Tooltip>
    );
  }

  return (
    <>
      <PaidPlanUpgradeModal
        isOpen={isPaidPlanPurchaseModalOpen}
        handleClose={() => setIsPaidPlanPurchaseModalOpen(false)}
      />
      <Tooltip label={`Version: v${packageJson.version}`} disabled={isMobile}>
        <Button
          variant="tertiary"
          size="md"
          stretch="auto"
          label="Community"
          onClick={() => setIsPaidPlanPurchaseModalOpen(true)}
          aria-haspopup="dialog"
          aria-label={t("aria_labels.projects_sidebar.edition_badge")}
        />
      </Tooltip>
    </>
  );
});
