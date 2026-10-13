/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
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
import { setToast } from "@plane/blocks/toast";
import type { TPageRestrictions } from "@plane/types";
import { getPageName } from "@plane/utils";
// components
import { MemberSelect } from "@/components/dropdowns/member/member-select";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";
// store
import type { TPageInstance } from "@/store/pages/base-page";

type Props = {
  page: TPageInstance;
  isOpen: boolean;
  onClose: () => void;
};

const errorMessage = (error: unknown, fallback: string) => (error as { error?: string })?.error || fallback;

/**
 * Who may view and who may edit a page. Restrictions apply to all of the page's sub-pages,
 * and only ever narrow the access people already have; the owner and admins keep access.
 */
export const PageRestrictionsModal = observer(function PageRestrictionsModal(props: Props) {
  const { page, isOpen, onClose } = props;
  // params
  const { workspaceSlug, projectId } = useParams();
  // store hooks
  const {
    workspace: { workspaceMemberIds, getWorkspaceMemberDetails, fetchWorkspaceMembers },
  } = useMember();
  const { fetchTree } = useWikiSpaces();
  // states
  const [restrictions, setRestrictions] = useState<TPageRestrictions | undefined>(undefined);
  const [viewIds, setViewIds] = useState<string[]>([]);
  const [editIds, setEditIds] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // derived values
  const isWikiPage = !!page.space;
  const canManage = !!restrictions?.can_manage;
  const scopeLabel = isWikiPage ? "space" : "project";

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    const load = async () => {
      try {
        const data = await page.fetchRestrictions();
        if (cancelled) return;
        setRestrictions(data);
        setViewIds(data.view);
        setEditIds(data.edit);
      } catch (error) {
        setToast({ type: "error", title: "Error!", message: errorMessage(error, "Restrictions could not be loaded.") });
        onClose();
      }
    };
    void load();
    if (isWikiPage && workspaceSlug) fetchWorkspaceMembers(workspaceSlug.toString()).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [fetchWorkspaceMembers, isOpen, isWikiPage, onClose, page, workspaceSlug]);

  // wiki pages: workspace admins and members (guests never have wiki access); the API
  // additionally checks that each person has a role in the page's space
  const wikiCandidateIds = useMemo(
    () =>
      (workspaceMemberIds ?? []).filter((userId) => {
        const details = getWorkspaceMemberDetails(userId);
        return !!details && Number(details.role) >= 15 && details.is_active !== false;
      }),
    [getWorkspaceMemberDetails, workspaceMemberIds]
  );

  const handleSave = async () => {
    setIsSubmitting(true);
    try {
      const data = await page.updateRestrictions({ view: viewIds, edit: editIds });
      setRestrictions(data);
      if (isWikiPage && workspaceSlug && page.space) await fetchTree(workspaceSlug.toString(), page.space);
      setToast({ type: "success", title: "Saved", message: "Page restrictions were updated." });
      onClose();
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "Restrictions could not be saved.") });
    } finally {
      setIsSubmitting(false);
    }
  };

  const memberSelectProps = isWikiPage
    ? { memberIds: wikiCandidateIds }
    : { projectId: projectId?.toString() ?? page.project_ids?.[0] };

  const renderSection = (
    title: string,
    description: string,
    value: string[],
    onChange: (ids: string[]) => void,
    testId: string
  ) => (
    <div role="group" aria-label={title} className="flex flex-col gap-1.5">
      <span className="text-13 font-medium text-primary">{title}</span>
      <p className="text-12 text-tertiary">{description}</p>
      <MemberSelect
        {...memberSelectProps}
        testId={testId}
        multiple
        value={value}
        onChange={onChange}
        variant="select-md"
        showLabel
        placeholder={`Everyone with access to this ${scopeLabel}`}
        disabled={!canManage || isSubmitting}
      />
    </div>
  );

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="md">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>Restrictions for “{getPageName(page.name)}”</DialogTitle>
            </DialogHeading>
          </DialogHeader>
          <DialogBody>
            {!restrictions ? (
              <p className="text-13 text-placeholder">Loading…</p>
            ) : (
              <div className="flex flex-col gap-5">
                {restrictions.inherited.length > 0 && (
                  <div className="rounded-md border border-subtle bg-layer-2 p-3 text-12 text-secondary">
                    <p className="font-medium text-primary">Inherited from parent pages</p>
                    <ul className="mt-1 list-disc pl-4">
                      {restrictions.inherited.map((parent) => (
                        <li key={parent.page}>
                          {getPageName(parent.name)} restricts{" "}
                          {[parent.view && "viewing", parent.edit && "editing"].filter(Boolean).join(" and ")}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-1">These also apply here and cannot be loosened on this page.</p>
                  </div>
                )}
                {renderSection(
                  "Who can view",
                  "Only these people can open this page and its sub-pages.",
                  viewIds,
                  setViewIds,
                  "page-restrictions-view"
                )}
                {renderSection(
                  "Who can edit",
                  "Only these people can change this page and its sub-pages; others with access can still read them.",
                  editIds,
                  setEditIds,
                  "page-restrictions-edit"
                )}
                <p className="text-12 text-tertiary">
                  Leave a list empty for no restriction. The page owner and {scopeLabel} admins always keep access.
                  Restrictions never give anyone more access than their {scopeLabel} role allows.
                </p>
              </div>
            )}
          </DialogBody>
        </DialogMain>
        <DialogActions>
          <Button
            stretch="auto"
            variant="secondary"
            size="md"
            label={canManage ? "Cancel" : "Close"}
            onClick={onClose}
          />
          {canManage && (
            <Button
              stretch="auto"
              variant="primary"
              size="md"
              label={isSubmitting ? "Saving…" : "Save"}
              onClick={handleSave}
              disabled={isSubmitting}
            />
          )}
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
});
