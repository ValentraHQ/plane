/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Logo } from "@plane/blocks/emoji-icon-picker";
import { setToast } from "@plane/blocks/toast";
import { ChevronRightOutline, PagesOutline } from "@makeplane/propel/icons";
// plane imports
import { cn, getPageName } from "@plane/utils";
// components
import { ListItem } from "@/components/core/list";
import { BlockItemAction } from "@/components/pages/list/block-item-action";
// hooks
import { usePlatformOS } from "@/hooks/use-platform-os";
// plane web hooks
import type { EPageStoreType } from "@/hooks/store";
import { usePage, usePageStore } from "@/hooks/store";

// indentation per nesting level, in px
const SUB_PAGE_INDENT = 20;

type TPageListBlock = {
  pageId: string;
  storeType: EPageStoreType;
  depth?: number;
};

export const PageListBlock = observer(function PageListBlock(props: TPageListBlock) {
  const { pageId, storeType, depth = 0 } = props;
  // states
  const [isExpanded, setIsExpanded] = useState(false);
  // refs
  const parentRef = useRef(null);
  // router
  const { workspaceSlug, projectId } = useParams();
  // hooks
  const page = usePage({
    pageId,
    storeType,
  });
  const { fetchSubPages, getSubPageIds } = usePageStore(storeType);
  const { isMobile } = usePlatformOS();

  // re-fetch on every expand so archive/restore cascades from the server are reflected
  useEffect(() => {
    if (!isExpanded || !workspaceSlug || !projectId) return;
    fetchSubPages(workspaceSlug.toString(), projectId.toString(), pageId).catch(() => {
      setToast({ type: "error", title: "Error!", message: "Sub-pages could not be loaded. Please try again." });
      setIsExpanded(false);
    });
  }, [isExpanded, workspaceSlug, projectId, pageId, fetchSubPages]);

  // handle page check
  if (!page) return null;
  // derived values
  const { name, logo_props, getRedirectionLink, sub_pages_count } = page;
  const subPageIds = getSubPageIds(pageId);
  const hasSubPages = (sub_pages_count ?? 0) > 0 || subPageIds.length > 0;

  const toggleExpanded = (e: React.MouseEvent) => {
    // the toggle sits inside the row link: keep it from navigating
    e.preventDefault();
    e.stopPropagation();
    setIsExpanded((prev) => !prev);
  };

  return (
    <>
      <ListItem
        prependTitleElement={
          <div className="flex items-center gap-1.5">
            {depth > 0 && <span aria-hidden className="flex-shrink-0" style={{ width: depth * SUB_PAGE_INDENT }} />}
            {hasSubPages ? (
              <button
                type="button"
                onClick={toggleExpanded}
                className="grid size-4 flex-shrink-0 place-items-center rounded-sm text-tertiary hover:bg-layer-transparent-hover"
                aria-label={isExpanded ? "Collapse sub-pages" : "Expand sub-pages"}
                aria-expanded={isExpanded}
              >
                <ChevronRightOutline className={cn("size-3 transition-transform", { "rotate-90": isExpanded })} />
              </button>
            ) : (
              <span aria-hidden className="size-4 flex-shrink-0" />
            )}
            {logo_props?.in_use ? (
              <Logo logo={logo_props} size={16} type="lucide" />
            ) : (
              <PagesOutline className="h-4 w-4 text-tertiary" />
            )}
          </div>
        }
        title={getPageName(name)}
        itemLink={getRedirectionLink()}
        actionableItems={<BlockItemAction page={page} parentRef={parentRef} storeType={storeType} />}
        isMobile={isMobile}
        parentRef={parentRef}
      />
      {isExpanded &&
        subPageIds.map((subPageId) => (
          <PageListBlock key={subPageId} pageId={subPageId} storeType={storeType} depth={depth + 1} />
        ))}
    </>
  );
});
