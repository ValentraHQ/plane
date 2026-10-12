/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Icon } from "@makeplane/propel/components/icon";
import { MenuOutline } from "@makeplane/propel/icons";
import { cn } from "@plane/utils";
// hooks
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";
// local imports
import { WikiSpaceSidebar } from "./space-tree/root";

type Props = {
  workspaceSlug: string;
  spaceId: string;
  activePageId?: string;
  children: React.ReactNode;
};

/**
 * Documentation layout: the space's page tree beside the content. On small screens the tree
 * is a drawer opened from a "Pages" button.
 */
export const WikiShell = observer(function WikiShell(props: Props) {
  const { workspaceSlug, spaceId, activePageId, children } = props;
  const { setCurrentSpace } = useWikiSpaces();
  const [isTreeOpen, setIsTreeOpen] = useState(false);

  // lists, "new page" and permissions follow the space being viewed
  useEffect(() => {
    setCurrentSpace(spaceId);
  }, [setCurrentSpace, spaceId]);

  // close the mobile drawer after navigating
  useEffect(() => {
    setIsTreeOpen(false);
  }, [activePageId]);

  return (
    <div className="relative flex h-full w-full overflow-hidden">
      <aside
        className={cn(
          "absolute inset-y-0 left-0 z-20 w-72 flex-shrink-0 border-r border-subtle bg-surface-1 transition-transform duration-200 md:static md:z-auto md:translate-x-0",
          isTreeOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <WikiSpaceSidebar workspaceSlug={workspaceSlug} spaceId={spaceId} activePageId={activePageId} />
      </aside>
      {isTreeOpen && (
        <button
          type="button"
          aria-label="Close page tree"
          className="absolute inset-0 z-10 bg-layer-1/50 md:hidden"
          onClick={() => setIsTreeOpen(false)}
        />
      )}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex flex-shrink-0 items-center border-b border-subtle px-3 py-1.5 md:hidden">
          <button
            type="button"
            onClick={() => setIsTreeOpen(true)}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 text-13 text-secondary hover:bg-layer-transparent-hover"
            aria-expanded={isTreeOpen}
          >
            <Icon icon={MenuOutline} />
            Pages
          </button>
        </div>
        <div className="relative min-h-0 flex-1 overflow-hidden">{children}</div>
      </div>
    </div>
  );
});
