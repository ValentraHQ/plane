/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
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
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { getPageName } from "@plane/utils";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";
// local imports
import { isSameOrDescendant } from "./space-tree/utils";

type Props = {
  workspaceSlug: string;
  pageId: string;
  isOpen: boolean;
  onClose: () => void;
};

type TOption = { id: string; label: string };
const TOP_LEVEL: TOption = { id: "", label: "Top level of the space" };

/** "Move to…": pick a target space and parent; the page's sub-pages move with it. */
export const WikiMovePageModal = observer(function WikiMovePageModal(props: Props) {
  const { workspaceSlug, pageId, isOpen, onClose } = props;
  // store hooks
  const { spaceIds, getSpaceById, getSpaceRole, getTreeChildIds, fetchTree, movePage } = useWikiSpaces();
  const { getPageById } = usePageStore(EPageStoreType.WORKSPACE);
  const page = getPageById(pageId);
  // states
  const [spaceId, setSpaceId] = useState<string>(page?.space ?? "");
  const [parentId, setParentId] = useState<string>(page?.parent ?? "");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // only spaces where the user may write are valid targets
  const spaceOptions: TOption[] = spaceIds
    .filter((id) => {
      const role = getSpaceRole(id);
      return !!role && role >= 15;
    })
    .map((id) => ({ id, label: getSpaceById(id)?.name ?? "" }));

  useEffect(() => {
    if (spaceId) fetchTree(workspaceSlug, spaceId).catch(() => undefined);
  }, [fetchTree, spaceId, workspaceSlug]);

  // every page of the target space, indented by depth, except this page and its own sub-tree
  const parentOptions = useMemo(() => {
    const options: TOption[] = [TOP_LEVEL];
    const walk = (parent: string | null, depth: number) => {
      for (const id of getTreeChildIds(spaceId, parent)) {
        if (isSameOrDescendant(id, pageId, (child) => getPageById(child)?.parent ?? null)) continue;
        options.push({ id, label: `${"  ".repeat(depth)}${getPageName(getPageById(id)?.name)}` });
        walk(id, depth + 1);
      }
    };
    if (spaceId) walk(null, 0);
    return options;
  }, [getPageById, getTreeChildIds, pageId, spaceId]);

  const selectedSpace = spaceOptions.find((option) => option.id === spaceId);
  const selectedParent = parentOptions.find((option) => option.id === parentId) ?? TOP_LEVEL;

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      await movePage(workspaceSlug, pageId, { space: spaceId, parent: parentId || null });
      setToast({ type: "success", title: "Moved", message: "The page and its sub-pages were moved." });
      onClose();
    } catch (error) {
      setToast({
        type: "error",
        title: "Error!",
        message: (error as { error?: string })?.error || "The page could not be moved.",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="md">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>Move “{getPageName(page?.name)}”</DialogTitle>
            </DialogHeading>
          </DialogHeader>
          <DialogBody>
            <div className="flex flex-col gap-4">
              <div role="group" aria-label="Space" className="flex flex-col gap-1.5 text-13 text-secondary">
                <span>Space</span>
                <Select<TOption>
                  getValues={() => spaceOptions}
                  value={selectedSpace ?? null}
                  onChange={(value) => {
                    if (!value) return;
                    setSpaceId(String(value));
                    setParentId("");
                  }}
                  getOptionValue={(option) => option.id}
                  getOptionLabel={(option) => option.label}
                  pinSelected={false}
                >
                  <Select.Trigger variant="select-md">
                    <span className="grow truncate">{selectedSpace?.label ?? "Select a space"}</span>
                  </Select.Trigger>
                </Select>
              </div>
              <div role="group" aria-label="Parent page" className="flex flex-col gap-1.5 text-13 text-secondary">
                <span>Parent page</span>
                <Select<TOption>
                  getValues={() => parentOptions}
                  value={selectedParent}
                  onChange={(value) => setParentId(!value || value === "top-level" ? "" : String(value))}
                  getOptionValue={(option) => option.id || "top-level"}
                  getOptionLabel={(option) => option.label}
                  pinSelected={false}
                >
                  <Select.Trigger variant="select-md">
                    <span className="grow truncate">{selectedParent.label.trim()}</span>
                  </Select.Trigger>
                </Select>
              </div>
              <p className="text-12 text-tertiary">Sub-pages move together with this page.</p>
            </div>
          </DialogBody>
        </DialogMain>
        <DialogActions>
          <Button stretch="auto" variant="secondary" size="md" label="Cancel" onClick={onClose} />
          <Button
            stretch="auto"
            variant="primary"
            size="md"
            label={isSubmitting ? "Moving…" : "Move"}
            onClick={handleSubmit}
            disabled={isSubmitting || !spaceId}
          />
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
});
