/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Instruction } from "@atlaskit/pragmatic-drag-and-drop-hitbox/tree-item";

/** spacing between sibling sort orders when a page goes first/last */
export const SORT_ORDER_STEP = 1000;
export const TREE_INDENT_PER_LEVEL = 16;

export type TTreeDragData = { type: "wiki-tree-page"; pageId: string; parentId: string | null; level: number };

export type TTreeLookups = {
  getParentId: (pageId: string) => string | null;
  getSortOrder: (pageId: string) => number;
  getChildIds: (parentId: string | null) => string[];
};

/** last item matching the predicate (Array#findLast is not in this project's TS lib) */
export const lastWhere = <T>(items: T[], predicate: (item: T) => boolean): T | undefined => {
  for (let index = items.length - 1; index >= 0; index--) if (predicate(items[index])) return items[index];
  return undefined;
};

/** true if `pageId` is `ancestorId` or nested anywhere under it */
export const isSameOrDescendant = (pageId: string, ancestorId: string, getParentId: TTreeLookups["getParentId"]) => {
  const seen = new Set<string>();
  for (let current: string | null = pageId; current && !seen.has(current); current = getParentId(current)) {
    if (current === ancestorId) return true;
    seen.add(current);
  }
  return false;
};

const between = (before: number | undefined, after: number | undefined) => {
  if (before === undefined && after === undefined) return SORT_ORDER_STEP;
  if (before === undefined) return (after as number) - SORT_ORDER_STEP;
  if (after === undefined) return before + SORT_ORDER_STEP;
  return (before + after) / 2;
};

/**
 * Where `sourceId` ends up when dropped on `targetId` with a tree-item instruction.
 * Returns null for no-op or invalid drops (onto itself or its own sub-tree).
 */
export const getDropDestination = (
  sourceId: string,
  targetId: string,
  instruction: Instruction | null,
  { getParentId, getSortOrder, getChildIds }: TTreeLookups
): { parent: string | null; sort_order: number } | null => {
  if (!instruction || instruction.type === "instruction-blocked" || sourceId === targetId) return null;

  if (instruction.type === "make-child") {
    if (isSameOrDescendant(targetId, sourceId, getParentId)) return null;
    const lastChild = lastWhere(getChildIds(targetId), (id) => id !== sourceId);
    return { parent: targetId, sort_order: between(lastChild ? getSortOrder(lastChild) : undefined, undefined) };
  }

  // reorder-above / reorder-below (and reparent, treated as "below the target") keep the target's parent
  const parent = getParentId(targetId);
  if (parent && isSameOrDescendant(parent, sourceId, getParentId)) return null;
  const siblings = getChildIds(parent).filter((id) => id !== sourceId);
  const index = siblings.indexOf(targetId);
  if (instruction.type === "reorder-above") {
    const previous = index > 0 ? siblings[index - 1] : undefined;
    return { parent, sort_order: between(previous ? getSortOrder(previous) : undefined, getSortOrder(targetId)) };
  }
  const next = index >= 0 && index < siblings.length - 1 ? siblings[index + 1] : undefined;
  return { parent, sort_order: between(getSortOrder(targetId), next ? getSortOrder(next) : undefined) };
};
