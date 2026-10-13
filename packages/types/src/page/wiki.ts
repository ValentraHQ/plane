/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TLogoProps } from "../common";

/** Role of a user in a documentation space (matches the API's WikiSpaceMember roles). */
export enum EWikiSpaceRole {
  ADMIN = 20,
  EDITOR = 15,
  VIEWER = 5,
}

/** OPEN: every workspace admin/member can read and write. RESTRICTED: only space members. */
export enum EWikiSpaceAccess {
  OPEN = 0,
  RESTRICTED = 1,
}

export type TWikiSpace = {
  id: string;
  workspace: string;
  name: string;
  identifier: string;
  description: string;
  logo_props: TLogoProps;
  access: EWikiSpaceAccess;
  is_default: boolean;
  sort_order: number;
  /** the current user's effective role; null means no access */
  my_role: EWikiSpaceRole | null;
  /** pages the current user can see (excluding archived) */
  page_count: number;
  created_at: string;
  updated_at: string;
  created_by: string | null;
};

export type TWikiSpaceMember = {
  id: string;
  space: string;
  member: string;
  role: EWikiSpaceRole;
  member__display_name: string;
  member__avatar_url: string;
  created_at: string;
};

/** A page as returned by the space tree endpoint (lightweight, non-archived, visible pages). */
export type TWikiTreeNode = {
  id: string;
  name: string;
  parent: string | null;
  sort_order: number;
  logo_props: TLogoProps;
  access: number;
  is_locked: boolean;
  owned_by: string;
  space: string;
  /** the page has its own view / edit restrictions (inherited ones are not flagged) */
  view_restricted: boolean;
  edit_restricted: boolean;
};

export type TWikiPageMovePayload = {
  space?: string;
  parent?: string | null;
  sort_order?: number;
};
