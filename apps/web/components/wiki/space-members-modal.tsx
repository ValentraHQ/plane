/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
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
import { DeleteOutline } from "@makeplane/propel/icons";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import type { TWikiSpaceMember } from "@plane/types";
import { EWikiSpaceAccess, EWikiSpaceRole } from "@plane/types";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";

type Props = {
  workspaceSlug: string;
  spaceId: string;
  isOpen: boolean;
  onClose: () => void;
};

type TRoleOption = { value: EWikiSpaceRole; label: string };
const ROLE_OPTIONS: TRoleOption[] = [
  { value: EWikiSpaceRole.ADMIN, label: "Admin" },
  { value: EWikiSpaceRole.EDITOR, label: "Editor" },
  { value: EWikiSpaceRole.VIEWER, label: "Viewer" },
];
type TPersonOption = { id: string; label: string };

const RoleSelect = ({
  value,
  onChange,
  disabled,
}: {
  value: EWikiSpaceRole;
  onChange: (role: EWikiSpaceRole) => void;
  disabled?: boolean;
}) => {
  const selected = ROLE_OPTIONS.find((option) => option.value === value) ?? ROLE_OPTIONS[1];
  if (disabled) return <span className="text-13 text-secondary">{selected.label}</span>;
  return (
    <Select<TRoleOption>
      getValues={() => ROLE_OPTIONS}
      value={selected}
      onChange={(nextRole) => nextRole && onChange(Number(nextRole) as EWikiSpaceRole)}
      getOptionValue={(option) => String(option.value)}
      getOptionLabel={(option) => option.label}
      showSearch={false}
      pinSelected={false}
    >
      <Select.Trigger variant="select-md">
        <span className="grow truncate">{selected.label}</span>
      </Select.Trigger>
    </Select>
  );
};

export const WikiSpaceMembersModal = observer(function WikiSpaceMembersModal(props: Props) {
  const { workspaceSlug, spaceId, isOpen, onClose } = props;
  // store hooks
  const { members, fetchMembers, addMember, updateMember, removeMember, getSpaceById } = useWikiSpaces();
  const {
    workspace: { workspaceMemberIds, getWorkspaceMemberDetails, fetchWorkspaceMembers },
  } = useMember();
  // states
  const [newMemberId, setNewMemberId] = useState<string>("");
  const [newRole, setNewRole] = useState<EWikiSpaceRole>(EWikiSpaceRole.EDITOR);
  // derived values
  const space = getSpaceById(spaceId);
  const isAdmin = space?.my_role === EWikiSpaceRole.ADMIN;
  const spaceMembers: TWikiSpaceMember[] = useMemo(() => members[spaceId] ?? [], [members, spaceId]);

  useSWR(isOpen ? `WIKI_SPACE_MEMBERS_${spaceId}` : null, () => fetchMembers(workspaceSlug, spaceId));
  useSWR(isOpen ? `WORKSPACE_MEMBERS_${workspaceSlug}` : null, () => fetchWorkspaceMembers(workspaceSlug));

  // workspace admins and members who are not in the space yet (guests never get wiki access)
  const candidates: TPersonOption[] = useMemo(() => {
    const existing = new Set(spaceMembers.map((m) => m.member));
    return (workspaceMemberIds ?? [])
      .map((userId) => getWorkspaceMemberDetails(userId))
      .filter((details) => !!details && Number(details.role) >= 15 && details.is_active !== false)
      .filter((details) => !existing.has(details!.member.id))
      .map((details) => ({ id: details!.member.id, label: details!.member.display_name }));
  }, [getWorkspaceMemberDetails, spaceMembers, workspaceMemberIds]);

  const run = async (action: () => Promise<unknown>, failure: string) => {
    try {
      await action();
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: (error as { error?: string })?.error || failure });
    }
  };

  const selectedCandidate = candidates.find((c) => c.id === newMemberId) ?? null;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="lg">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>Members of {space?.name}</DialogTitle>
            </DialogHeading>
          </DialogHeader>
          <DialogBody>
            <p className="mb-3 text-13 text-tertiary">
              {space?.access === EWikiSpaceAccess.OPEN
                ? "This space is open: every workspace admin and member can edit. Add people here to make them space admins or to limit them to viewing."
                : "This space is restricted: only the people below (and workspace admins) can see it."}
            </p>
            {isAdmin && (
              <div className="mb-4 flex items-end gap-2">
                <div className="min-w-0 flex-1">
                  <Select<TPersonOption>
                    getValues={() => candidates}
                    value={selectedCandidate}
                    onChange={(value) => setNewMemberId(value ? String(value) : "")}
                    getOptionValue={(option) => option.id}
                    getOptionLabel={(option) => option.label}
                    pinSelected={false}
                  >
                    <Select.Trigger variant="select-md">
                      <span className="grow truncate">{selectedCandidate?.label ?? "Add a workspace member"}</span>
                    </Select.Trigger>
                  </Select>
                </div>
                <RoleSelect value={newRole} onChange={setNewRole} />
                <Button
                  variant="primary"
                  size="md"
                  stretch="auto"
                  label="Add"
                  disabled={!newMemberId}
                  onClick={() =>
                    run(async () => {
                      await addMember(workspaceSlug, spaceId, { member: newMemberId, role: newRole });
                      setNewMemberId("");
                    }, "The member could not be added.")
                  }
                />
              </div>
            )}
            <ul className="divide-y divide-subtle rounded-md border border-subtle">
              {spaceMembers.length === 0 && <li className="p-3 text-13 text-placeholder">No members added yet.</li>}
              {spaceMembers.map((membership) => (
                <li key={membership.id} className="flex items-center gap-3 p-2.5">
                  <span className="min-w-0 flex-1 truncate text-13 text-primary">
                    {membership.member__display_name}
                  </span>
                  <RoleSelect
                    value={membership.role}
                    disabled={!isAdmin}
                    onChange={(role) =>
                      run(
                        () => updateMember(workspaceSlug, spaceId, membership.id, role),
                        "The role could not be changed."
                      )
                    }
                  />
                  {isAdmin && (
                    <IconButton
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove ${membership.member__display_name}`}
                      icon={<Icon icon={DeleteOutline} />}
                      onClick={() =>
                        run(
                          () => removeMember(workspaceSlug, spaceId, membership.id),
                          "The member could not be removed."
                        )
                      }
                    />
                  )}
                </li>
              ))}
            </ul>
          </DialogBody>
        </DialogMain>
        <DialogActions>
          <Button stretch="auto" variant="secondary" size="md" label="Close" onClick={onClose} />
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
});
