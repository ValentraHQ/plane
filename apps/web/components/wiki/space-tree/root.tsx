/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
// plane imports
import { setToast } from "@plane/blocks/toast";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { AddOutline, FolderOutline } from "@makeplane/propel/icons";
import { cn } from "@plane/utils";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";
import { useAppRouter } from "@/hooks/use-app-router";
// local imports
import { WikiMovePageModal } from "../move-page-modal";
import { WikiSpaceSwitcher } from "../space-switcher";
import { WikiTreeNode } from "./node";
import { SORT_ORDER_STEP, lastWhere } from "./utils";

type Props = {
  workspaceSlug: string;
  spaceId: string;
  activePageId?: string;
};

const storeType = EPageStoreType.WORKSPACE;

/** Persistent documentation-space navigation: space switcher, new page, and the page tree. */
export const WikiSpaceSidebar = observer(function WikiSpaceSidebar(props: Props) {
  const { workspaceSlug, spaceId, activePageId } = props;
  // refs
  const rootDropRef = useRef<HTMLDivElement>(null);
  // states
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [movePageId, setMovePageId] = useState<string | undefined>(undefined);
  const [isRootDropTarget, setIsRootDropTarget] = useState(false);
  // store hooks
  const { fetchTree, getTreeChildIds, getSpaceById, getSpaceRole, movePage } = useWikiSpaces();
  const { createPage, getPageById } = usePageStore(storeType);
  const router = useAppRouter();
  // derived values
  const space = getSpaceById(spaceId);
  const rootIds = getTreeChildIds(spaceId, null);
  const role = getSpaceRole(spaceId);
  const canWrite = !!role && role >= 15;

  const { isLoading } = useSWR(
    workspaceSlug && spaceId ? `WIKI_SPACE_TREE_${spaceId}` : null,
    () => fetchTree(workspaceSlug, spaceId),
    { revalidateOnFocus: true }
  );

  const toggleExpanded = useCallback((pageId: string, expanded?: boolean) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      const open = expanded ?? !next.has(pageId);
      if (open) next.add(pageId);
      else next.delete(pageId);
      return next;
    });
  }, []);

  // keep the active page visible: expand all of its ancestors
  const activeParentId = activePageId ? getPageById(activePageId)?.parent : undefined;
  useEffect(() => {
    if (!activePageId) return;
    const ancestors: string[] = [];
    const seen = new Set<string>();
    for (let id = getPageById(activePageId)?.parent; id && !seen.has(id); id = getPageById(id)?.parent) {
      seen.add(id);
      ancestors.push(id);
    }
    if (ancestors.length) setExpandedIds((prev) => new Set([...prev, ...ancestors]));
  }, [activePageId, activeParentId, getPageById]);

  // dropping below the tree makes a page the last top-level page
  useEffect(() => {
    const element = rootDropRef.current;
    if (!element) return;
    return dropTargetForElements({
      element,
      canDrop: ({ source }) => source.data.type === "wiki-tree-page",
      onDragEnter: () => setIsRootDropTarget(true),
      onDragLeave: () => setIsRootDropTarget(false),
      onDrop: async ({ source }) => {
        setIsRootDropTarget(false);
        const sourceId = source.data.pageId as string;
        const last = lastWhere(getTreeChildIds(spaceId, null), (id) => id !== sourceId);
        try {
          await movePage(workspaceSlug, sourceId, {
            parent: null,
            sort_order: (last ? (getPageById(last)?.sort_order ?? 0) : 0) + SORT_ORDER_STEP,
          });
        } catch (error) {
          setToast({
            type: "error",
            title: "Error!",
            message: (error as { error?: string })?.error || "The page could not be moved.",
          });
        }
      },
    });
  }, [getPageById, getTreeChildIds, movePage, spaceId, workspaceSlug]);

  const handleNewPage = async () => {
    try {
      const page = await createPage({ space: spaceId });
      const link = page?.id ? getPageById(page.id)?.getRedirectionLink() : undefined;
      if (link) router.push(link);
    } catch (error) {
      setToast({
        type: "error",
        title: "Error!",
        message: (error as { error?: string })?.error || "Page could not be created.",
      });
    }
  };

  return (
    <nav aria-label="Space pages" className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex flex-shrink-0 items-center gap-1 border-b border-subtle px-2 py-2">
        <div className="min-w-0 flex-1">
          <WikiSpaceSwitcher workspaceSlug={workspaceSlug} spaceId={spaceId} />
        </div>
        {canWrite && (
          <IconButton
            variant="ghost"
            size="sm"
            aria-label="New page in this space"
            icon={<Icon icon={AddOutline} />}
            onClick={handleNewPage}
          />
        )}
      </div>
      <Link
        href={`/${workspaceSlug}/wiki/spaces/${spaceId}`}
        className={cn(
          "mx-2 mt-2 flex h-8 flex-shrink-0 items-center gap-1.5 rounded-md px-2 text-13 text-secondary hover:bg-layer-transparent-hover",
          { "bg-layer-transparent-selected font-medium text-primary": !activePageId }
        )}
      >
        <FolderOutline className="size-3.5 text-tertiary" />
        <span className="truncate">{space?.name ?? "Space"} home</span>
      </Link>
      <div role="tree" aria-label={`${space?.name ?? "Space"} pages`} className="mt-1 flex-1 overflow-y-auto px-2 pb-2">
        {isLoading && rootIds.length === 0 && <p className="px-2 py-1 text-13 text-placeholder">Loading pages…</p>}
        {!isLoading && rootIds.length === 0 && (
          <p className="px-2 py-1 text-13 text-placeholder">No pages yet{canWrite ? " — use + to add one." : "."}</p>
        )}
        {rootIds.map((pageId, index) => (
          <WikiTreeNode
            key={pageId}
            pageId={pageId}
            spaceId={spaceId}
            workspaceSlug={workspaceSlug}
            level={0}
            activePageId={activePageId}
            expandedIds={expandedIds}
            toggleExpanded={toggleExpanded}
            onMoveTo={setMovePageId}
            isLastInGroup={index === rootIds.length - 1}
          />
        ))}
        <div
          ref={rootDropRef}
          className={cn("mt-1 h-6 rounded-md", { "border border-dashed border-accent-strong": isRootDropTarget })}
          aria-hidden
        />
      </div>
      {movePageId && (
        <WikiMovePageModal
          workspaceSlug={workspaceSlug}
          pageId={movePageId}
          isOpen={!!movePageId}
          onClose={() => setMovePageId(undefined)}
        />
      )}
    </nav>
  );
});
