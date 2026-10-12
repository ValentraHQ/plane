/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { combine } from "@atlaskit/pragmatic-drag-and-drop/combine";
import { draggable, dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import type { Instruction } from "@atlaskit/pragmatic-drag-and-drop-hitbox/tree-item";
import { attachInstruction, extractInstruction } from "@atlaskit/pragmatic-drag-and-drop-hitbox/tree-item";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { Logo } from "@plane/blocks/emoji-icon-picker";
import { setToast } from "@plane/blocks/toast";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import {
  AddOutline,
  ChevronRightOutline,
  LockOutline,
  MoreHorizontalOutline,
  PagesOutline,
  RightArrowOutline,
} from "@makeplane/propel/icons";
import { cn, getPageName } from "@plane/utils";
// hooks
import { EPageStoreType, usePage, usePageStore } from "@/hooks/store";
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";
import { useAppRouter } from "@/hooks/use-app-router";
// local imports
import type { TTreeDragData } from "./utils";
import { TREE_INDENT_PER_LEVEL, getDropDestination } from "./utils";

type Props = {
  pageId: string;
  spaceId: string;
  workspaceSlug: string;
  level: number;
  activePageId: string | undefined;
  expandedIds: Set<string>;
  toggleExpanded: (pageId: string, expanded?: boolean) => void;
  onMoveTo: (pageId: string) => void;
  isLastInGroup: boolean;
};

const storeType = EPageStoreType.WORKSPACE;

export const WikiTreeNode = observer(function WikiTreeNode(props: Props) {
  const { pageId, spaceId, workspaceSlug, level, activePageId, expandedIds, toggleExpanded, onMoveTo, isLastInGroup } =
    props;
  // refs
  const rowRef = useRef<HTMLDivElement>(null);
  // states
  const [isDragging, setIsDragging] = useState(false);
  const [instruction, setInstruction] = useState<Instruction | null>(null);
  // store hooks
  const page = usePage({ pageId, storeType });
  const { createPage, getPageById } = usePageStore(storeType);
  const { getTreeChildIds, movePage, getSpaceRole } = useWikiSpaces();
  const router = useAppRouter();
  // derived values
  const childIds = getTreeChildIds(spaceId, pageId);
  const hasChildren = childIds.length > 0;
  const isExpanded = expandedIds.has(pageId);
  const isActive = activePageId === pageId;
  const canMove = !!page?.canCurrentUserMovePage;
  const spaceRole = getSpaceRole(spaceId);
  const canAddSubPage = !!spaceRole && spaceRole >= 15;

  // drag and drop: the row is both a draggable and a drop target (above / below / make child)
  useEffect(() => {
    const element = rowRef.current;
    if (!element) return;
    const data: TTreeDragData = { type: "wiki-tree-page", pageId, parentId: page?.parent ?? null, level };
    return combine(
      draggable({
        element,
        getInitialData: () => data,
        canDrag: () => canMove,
        onDragStart: () => setIsDragging(true),
        onDrop: () => setIsDragging(false),
      }),
      dropTargetForElements({
        element,
        canDrop: ({ source }) => source.data.type === "wiki-tree-page" && source.data.pageId !== pageId,
        getData: ({ input, element: target }) =>
          attachInstruction(data, {
            input,
            element: target,
            currentLevel: level,
            indentPerLevel: TREE_INDENT_PER_LEVEL,
            mode: isExpanded && hasChildren ? "expanded" : isLastInGroup ? "last-in-group" : "standard",
            // a page can only be re-parented through make-child here; keep the gesture simple
            block: ["reparent"],
          }),
        onDrag: ({ self }) => setInstruction(extractInstruction(self.data)),
        onDragLeave: () => setInstruction(null),
        onDrop: async ({ self, source }) => {
          setInstruction(null);
          const sourceId = source.data.pageId as string;
          const destination = getDropDestination(sourceId, pageId, extractInstruction(self.data), {
            getParentId: (id) => getPageById(id)?.parent ?? null,
            getSortOrder: (id) => getPageById(id)?.sort_order ?? 0,
            getChildIds: (parentId) => getTreeChildIds(spaceId, parentId),
          });
          if (!destination) return;
          try {
            await movePage(workspaceSlug, sourceId, destination);
            if (destination.parent) toggleExpanded(destination.parent, true);
          } catch (error) {
            setToast({
              type: "error",
              title: "Error!",
              message: (error as { error?: string })?.error || "The page could not be moved.",
            });
          }
        },
      })
    );
  }, [
    canMove,
    getPageById,
    getTreeChildIds,
    hasChildren,
    isExpanded,
    isLastInGroup,
    level,
    movePage,
    page?.parent,
    pageId,
    spaceId,
    toggleExpanded,
    workspaceSlug,
  ]);

  if (!page) return null;

  const handleAddSubPage = async () => {
    try {
      const subPage = await createPage({ parent: pageId, access: page.access });
      toggleExpanded(pageId, true);
      const link = subPage?.id ? getPageById(subPage.id)?.getRedirectionLink() : undefined;
      if (link) router.push(link);
    } catch (error) {
      setToast({
        type: "error",
        title: "Error!",
        message: (error as { error?: string })?.error || "Sub-page could not be created.",
      });
    }
  };

  return (
    <div role="treeitem" aria-expanded={hasChildren ? isExpanded : undefined} aria-selected={isActive}>
      <div
        ref={rowRef}
        className={cn(
          "group relative flex h-8 items-center gap-1 rounded-md pr-1 text-13 text-secondary hover:bg-layer-transparent-hover",
          {
            "bg-layer-transparent-selected font-medium text-primary": isActive,
            "opacity-50": isDragging,
            "ring-1 ring-accent-strong": instruction?.type === "make-child",
          }
        )}
        style={{ paddingLeft: level * TREE_INDENT_PER_LEVEL + 4 }}
      >
        {instruction?.type === "reorder-above" && (
          <span
            className="bg-accent-strong absolute top-0 right-0 h-0.5"
            style={{ left: level * TREE_INDENT_PER_LEVEL }}
          />
        )}
        {instruction?.type === "reorder-below" && (
          <span
            className="bg-accent-strong absolute right-0 bottom-0 h-0.5"
            style={{ left: level * TREE_INDENT_PER_LEVEL }}
          />
        )}
        <button
          type="button"
          onClick={() => toggleExpanded(pageId)}
          className={cn(
            "grid size-5 flex-shrink-0 place-items-center rounded-sm text-tertiary hover:bg-layer-transparent-hover",
            {
              invisible: !hasChildren,
            }
          )}
          aria-label={isExpanded ? "Collapse" : "Expand"}
          tabIndex={hasChildren ? 0 : -1}
        >
          <ChevronRightOutline className={cn("size-3 transition-transform", { "rotate-90": isExpanded })} />
        </button>
        <Link href={page.getRedirectionLink()} className="flex min-w-0 flex-1 items-center gap-1.5 py-1">
          {page.logo_props?.in_use ? (
            <Logo logo={page.logo_props} size={14} type="lucide" />
          ) : (
            <PagesOutline className="size-3.5 flex-shrink-0 text-tertiary" />
          )}
          <span className="truncate">{getPageName(page.name)}</span>
          {page.access === 1 && <LockOutline className="size-3 flex-shrink-0 text-placeholder" aria-label="Private" />}
        </Link>
        <div className="hidden flex-shrink-0 items-center group-focus-within:flex group-hover:flex">
          {canAddSubPage && (
            <IconButton
              variant="ghost"
              size="sm"
              aria-label="Add sub-page"
              icon={<Icon icon={AddOutline} />}
              onClick={handleAddSubPage}
            />
          )}
          {canMove && (
            <Menu>
              <MenuTrigger
                render={
                  <IconButton
                    variant="ghost"
                    size="sm"
                    aria-label="Page actions"
                    icon={<Icon icon={MoreHorizontalOutline} />}
                  />
                }
              />
              <MenuContent side="bottom" align="end">
                <MenuItem label="Move to…" icon={<Icon icon={RightArrowOutline} />} onClick={() => onMoveTo(pageId)} />
              </MenuContent>
            </Menu>
          )}
        </div>
      </div>
      {isExpanded && hasChildren && (
        <div role="group">
          {childIds.map((childId, index) => (
            <WikiTreeNode
              key={childId}
              {...props}
              pageId={childId}
              level={level + 1}
              isLastInGroup={index === childIds.length - 1}
            />
          ))}
        </div>
      )}
    </div>
  );
});
