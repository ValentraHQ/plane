/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { AddOutline, GlobeOutline, InfoOutline, LockOutline, MinusOutline } from "@makeplane/propel/icons";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { FavoriteStar } from "@plane/blocks/common";
import { setToast } from "@plane/blocks/toast";
import { renderFormattedDate, getFileURL } from "@plane/utils";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useAppRouter } from "@/hooks/use-app-router";
import { usePageOperations } from "@/hooks/use-page-operations";
// plane web hooks
import type { EPageStoreType } from "@/hooks/store";
import { usePageStore } from "@/hooks/store";
// store
import type { TPageInstance } from "@/store/pages/base-page";
// local imports
import { PageActions } from "../dropdowns";

type Props = {
  page: TPageInstance;
  parentRef: React.RefObject<HTMLElement | null>;
  storeType: EPageStoreType;
};

export const BlockItemAction = observer(function BlockItemAction(props: Props) {
  const { page, parentRef, storeType } = props;
  // router
  const router = useAppRouter();
  const { workspaceSlug, projectId } = useParams();
  // store hooks
  const { getUserDetails } = useMember();
  const { canCurrentUserCreatePage, createPage } = usePageStore(storeType);
  // page operations
  const { pageOperations } = usePageOperations({
    page,
  });
  // derived values
  const { access, archived_at, created_at, is_favorite, owned_by, canCurrentUserFavoritePage } = page;
  const ownerDetails = owned_by ? getUserDetails(owned_by) : undefined;

  // a sub-page inherits the parent's access so a private parent never gets public children
  const handleAddSubPage = async () => {
    try {
      const subPage = await createPage({ parent: page.id, access });
      if (subPage?.id) router.push(`/${workspaceSlug}/projects/${projectId}/pages/${subPage.id}`);
    } catch (err) {
      setToast({
        type: "error",
        title: "Error!",
        message: (err as { error?: string })?.error || "Sub-page could not be created. Please try again.",
      });
    }
  };

  return (
    <>
      {/* page details */}
      <div className="cursor-default">
        <Tooltip label={`Owned by: ${ownerDetails?.display_name ?? ""}`} layout="stacked">
          <Avatar
            alt={ownerDetails?.display_name}
            fallback={ownerDetails?.display_name?.[0]?.toUpperCase()}
            src={getFileURL(ownerDetails?.avatar_url ?? "")}
            size="xs"
          />
        </Tooltip>
      </div>
      <div className="cursor-default text-tertiary">
        <Tooltip label={access === 0 ? "Public" : "Private"}>
          {access === 0 ? <GlobeOutline className="h-4 w-4" /> : <LockOutline className="h-4 w-4" />}
        </Tooltip>
      </div>
      {/* vertical divider */}
      <MinusOutline className="-mx-3 h-5 w-5 rotate-90 text-placeholder" />

      {/* page info */}
      <Tooltip label={`Created on ${renderFormattedDate(created_at)}`} layout="stacked">
        <span className="grid h-4 w-4 cursor-default place-items-center">
          <InfoOutline className="h-4 w-4 text-tertiary" />
        </span>
      </Tooltip>

      {/* favorite/unfavorite */}
      {canCurrentUserFavoritePage && (
        <FavoriteStar
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            pageOperations.toggleFavorite();
          }}
          selected={is_favorite}
        />
      )}

      {/* quick actions dropdown */}
      <PageActions
        extraOptions={[
          {
            key: "add-sub-page",
            action: handleAddSubPage,
            title: "Add sub-page",
            icon: AddOutline,
            shouldRender: canCurrentUserCreatePage && !archived_at,
          },
        ]}
        optionsOrder={[
          "add-sub-page",
          "open-in-new-tab",
          "copy-link",
          "make-a-copy",
          "toggle-lock",
          "toggle-access",
          "archive-restore",
          "delete",
        ]}
        page={page}
        parentRef={parentRef}
        storeType={storeType}
      />
    </>
  );
});
