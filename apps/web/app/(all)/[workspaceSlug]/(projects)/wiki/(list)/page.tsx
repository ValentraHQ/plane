/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
// plane imports
import { EmptyStateDetailed } from "@plane/blocks/empty-state";
import { GlobeOutline, LockOutline } from "@makeplane/propel/icons";
import { EWikiSpaceAccess, EWikiSpaceRole } from "@plane/types";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PageHead } from "@/components/core/page-title";
import { WikiSpaceIcon } from "@/components/wiki/space-switcher";
// hooks
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";
import type { Route } from "./+types/page";

const ROLE_LABELS: Record<number, string> = {
  [EWikiSpaceRole.ADMIN]: "Admin",
  [EWikiSpaceRole.EDITOR]: "Editor",
  [EWikiSpaceRole.VIEWER]: "Viewer",
};

/** Directory of documentation spaces the user can see. */
function WikiSpacesPage({ params }: Route.ComponentProps) {
  const { workspaceSlug } = params;
  const { spaceIds, getSpaceById, fetchSpaces, setCurrentSpace } = useWikiSpaces();
  const { isLoading } = useSWR(workspaceSlug ? `WIKI_SPACES_${workspaceSlug}` : null, () => fetchSpaces(workspaceSlug));

  // the directory is not inside any space
  useEffect(() => setCurrentSpace(undefined), [setCurrentSpace]);

  return (
    <>
      <PageHead title="Wiki" />
      <div className="h-full w-full overflow-y-auto">
        {isLoading && spaceIds.length === 0 ? (
          <div className="grid h-full place-items-center">
            <LogoSpinner />
          </div>
        ) : spaceIds.length === 0 ? (
          <EmptyStateDetailed
            assetKey="page"
            title="Create your first documentation space"
            description="Spaces group related documentation — for a team, product or topic — with their own page tree and access."
          />
        ) : (
          <div className="mx-auto grid max-w-6xl grid-cols-1 gap-4 p-4 sm:grid-cols-2 sm:p-6 lg:grid-cols-3">
            {spaceIds.map((spaceId) => {
              const space = getSpaceById(spaceId);
              if (!space) return null;
              const isRestricted = space.access === EWikiSpaceAccess.RESTRICTED;
              return (
                <Link
                  key={space.id}
                  href={`/${workspaceSlug}/wiki/spaces/${space.id}`}
                  className="flex flex-col gap-3 rounded-lg border border-subtle bg-surface-1 p-4 transition-colors hover:border-strong hover:bg-layer-transparent-hover"
                >
                  <div className="flex items-center gap-2">
                    <span className="grid size-8 flex-shrink-0 place-items-center rounded-md bg-layer-2">
                      <WikiSpaceIcon logo_props={space.logo_props} size={16} />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-14 font-medium text-primary">{space.name}</p>
                      <p className="text-12 text-tertiary">{space.identifier}</p>
                    </div>
                  </div>
                  <p className="line-clamp-2 min-h-8 text-13 text-secondary">
                    {space.description || "No description yet."}
                  </p>
                  <div className="mt-auto flex items-center gap-3 text-12 text-tertiary">
                    <span>
                      {space.page_count} {space.page_count === 1 ? "page" : "pages"}
                    </span>
                    <span className="flex items-center gap-1">
                      {isRestricted ? <LockOutline className="size-3" /> : <GlobeOutline className="size-3" />}
                      {isRestricted ? "Restricted" : "Open"}
                    </span>
                    {space.my_role && <span className="ml-auto">{ROLE_LABELS[space.my_role]}</span>}
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

export default observer(WikiSpacesPage);
