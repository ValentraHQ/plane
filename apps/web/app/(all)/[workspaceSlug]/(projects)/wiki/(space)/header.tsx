/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import {
  DeleteOutline,
  MembersOutline,
  MoreHorizontalOutline,
  PagesOutline,
  SettingsOutline,
} from "@makeplane/propel/icons";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { Header } from "@plane/blocks/layout";
import { setToast } from "@plane/blocks/toast";
import { EWikiSpaceRole } from "@plane/types";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { WikiSpaceFormModal } from "@/components/wiki/space-form-modal";
import { WikiSpaceMembersModal } from "@/components/wiki/space-members-modal";
import { WikiSpaceIcon } from "@/components/wiki/space-switcher";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";
import { useAppRouter } from "@/hooks/use-app-router";

export const WikiSpaceHeader = observer(function WikiSpaceHeader() {
  const { workspaceSlug, spaceId } = useParams();
  const slug = workspaceSlug?.toString() ?? "";
  const router = useAppRouter();
  // store hooks
  const { getSpaceById, deleteSpace } = useWikiSpaces();
  const { createPage, getPageById } = usePageStore(EPageStoreType.WORKSPACE);
  // states
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isMembersOpen, setIsMembersOpen] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  // derived values
  const space = getSpaceById(spaceId?.toString());
  const isAdmin = space?.my_role === EWikiSpaceRole.ADMIN;
  const canWrite = !!space?.my_role && space.my_role >= EWikiSpaceRole.EDITOR;

  if (!space) return null;

  const handleNewPage = async () => {
    setIsCreating(true);
    try {
      const page = await createPage({ space: space.id });
      const link = page?.id ? getPageById(page.id)?.getRedirectionLink() : undefined;
      if (link) router.push(link);
    } catch (error) {
      setToast({
        type: "error",
        title: "Error!",
        message: (error as { error?: string })?.error || "Page could not be created.",
      });
    } finally {
      setIsCreating(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteSpace(slug, space.id);
      setToast({ type: "success", title: "Deleted", message: `The space ${space.name} was deleted.` });
      router.push(`/${slug}/wiki`);
    } catch (error) {
      setToast({
        type: "error",
        title: "Error!",
        message: (error as { error?: string })?.error || "The space could not be deleted.",
      });
    } finally {
      setIsDeleteOpen(false);
    }
  };

  return (
    <>
      <Header>
        <Header.LeftItem>
          <Breadcrumbs>
            <Breadcrumbs.Item
              component={
                <BreadcrumbLink
                  label="Wiki"
                  href={`/${slug}/wiki`}
                  icon={<PagesOutline className="h-4 w-4 text-tertiary" />}
                />
              }
            />
            <Breadcrumbs.Item
              component={<BreadcrumbLink label={space.name} icon={<WikiSpaceIcon logo_props={space.logo_props} />} />}
              isLast
            />
          </Breadcrumbs>
        </Header.LeftItem>
        <Header.RightItem>
          {canWrite && (
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              label={isCreating ? "Adding…" : "New page"}
              onClick={handleNewPage}
              disabled={isCreating}
            />
          )}
          <Menu>
            <MenuTrigger
              render={
                <IconButton
                  variant="ghost"
                  size="md"
                  aria-label="Space actions"
                  icon={<Icon icon={MoreHorizontalOutline} />}
                />
              }
            />
            <MenuContent side="bottom" align="end">
              <MenuItem label="Members" icon={<Icon icon={MembersOutline} />} onClick={() => setIsMembersOpen(true)} />
              {isAdmin && (
                <MenuItem
                  label="Space settings"
                  icon={<Icon icon={SettingsOutline} />}
                  onClick={() => setIsSettingsOpen(true)}
                />
              )}
              {isAdmin && !space.is_default && (
                <MenuItem
                  label="Delete space"
                  variant="danger"
                  icon={<Icon icon={DeleteOutline} />}
                  onClick={() => setIsDeleteOpen(true)}
                />
              )}
            </MenuContent>
          </Menu>
        </Header.RightItem>
      </Header>
      <WikiSpaceFormModal
        workspaceSlug={slug}
        space={space}
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />
      <WikiSpaceMembersModal
        workspaceSlug={slug}
        spaceId={space.id}
        isOpen={isMembersOpen}
        onClose={() => setIsMembersOpen(false)}
      />
      <Dialog open={isDeleteOpen} onOpenChange={(open) => !open && setIsDeleteOpen(false)}>
        <DialogContent size="sm">
          <DialogMain>
            <DialogHeader>
              <DialogHeading>
                <DialogTitle>Delete {space.name}?</DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody>
              <p className="text-13 text-secondary">
                Only empty spaces can be deleted. Move or delete every page in this space first, including archived and
                private pages.
              </p>
            </DialogBody>
          </DialogMain>
          <DialogActions>
            <Button
              variant="secondary"
              size="md"
              stretch="auto"
              label="Cancel"
              onClick={() => setIsDeleteOpen(false)}
            />
            <Button stretch="auto" variant="danger" size="md" label="Delete space" onClick={handleDelete} />
          </DialogActions>
        </DialogContent>
      </Dialog>
    </>
  );
});
