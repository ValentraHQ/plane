/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { Logo } from "@plane/blocks/emoji-icon-picker";
import { Icon } from "@makeplane/propel/components/icon";
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@makeplane/propel/components/menu";
import { ChevronDownOutline, FolderOutline } from "@makeplane/propel/icons";
// hooks
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";
import { useAppRouter } from "@/hooks/use-app-router";

type Props = {
  workspaceSlug: string;
  spaceId: string;
};

export const WikiSpaceIcon = ({ logo_props, size = 14 }: { logo_props?: { in_use?: string }; size?: number }) =>
  logo_props?.in_use ? (
    <Logo logo={logo_props as never} size={size} type="lucide" />
  ) : (
    <FolderOutline className="flex-shrink-0 text-tertiary" style={{ width: size, height: size }} />
  );

export const WikiSpaceSwitcher = observer(function WikiSpaceSwitcher({ workspaceSlug, spaceId }: Props) {
  const router = useAppRouter();
  const { spaceIds, getSpaceById, fetchSpaces } = useWikiSpaces();
  useSWR(workspaceSlug ? `WIKI_SPACES_${workspaceSlug}` : null, () => fetchSpaces(workspaceSlug));
  const space = getSpaceById(spaceId);

  return (
    <Menu>
      <MenuTrigger
        render={
          <button
            type="button"
            className="flex h-8 w-full items-center gap-1.5 rounded-md px-2 text-left text-13 font-medium text-primary hover:bg-layer-transparent-hover"
            aria-label="Switch space"
          >
            <WikiSpaceIcon logo_props={space?.logo_props} />
            <span className="truncate">{space?.name ?? "Space"}</span>
            <ChevronDownOutline className="ml-auto size-3 flex-shrink-0 text-tertiary" />
          </button>
        }
      />
      <MenuContent side="bottom" align="start">
        {spaceIds.map((id) => {
          const item = getSpaceById(id);
          if (!item) return null;
          return (
            <MenuItem
              key={id}
              label={item.name}
              description={item.identifier}
              icon={<WikiSpaceIcon logo_props={item.logo_props} />}
              onClick={() => router.push(`/${workspaceSlug}/wiki/spaces/${id}`)}
            />
          );
        })}
        <MenuSeparator />
        <MenuItem
          label="All spaces"
          icon={<Icon icon={FolderOutline} />}
          onClick={() => router.push(`/${workspaceSlug}/wiki`)}
        />
      </MenuContent>
    </Menu>
  );
});
