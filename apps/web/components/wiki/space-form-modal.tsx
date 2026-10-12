/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { FormEvent } from "react";
import { useEffect, useState } from "react";
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
import { InputField } from "@makeplane/propel/components/input-field";
import { setToast } from "@plane/blocks/toast";
import type { TWikiSpace } from "@plane/types";
import { EWikiSpaceAccess } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useWikiSpaces } from "@/hooks/store/use-wiki-spaces";

type Props = {
  workspaceSlug: string;
  isOpen: boolean;
  onClose: () => void;
  /** edit this space; create a new one when omitted */
  space?: TWikiSpace;
  onSaved?: (space: TWikiSpace) => void;
};

const ACCESS_OPTIONS = [
  {
    value: EWikiSpaceAccess.OPEN,
    label: "Open",
    description: "Every workspace admin and member can read and edit.",
  },
  {
    value: EWikiSpaceAccess.RESTRICTED,
    label: "Restricted",
    description: "Only people added to the space (and workspace admins).",
  },
];

/** "Product Docs" -> "PD"; one word -> its first 3 letters */
const suggestIdentifier = (name: string) => {
  const words = name.toUpperCase().match(/[A-Z0-9]+/g) ?? [];
  const key = words.length > 1 ? words.map((word) => word[0]).join("") : (words[0] ?? "").slice(0, 3);
  return key.slice(0, 12);
};

export const WikiSpaceFormModal = observer(function WikiSpaceFormModal(props: Props) {
  const { workspaceSlug, isOpen, onClose, space, onSaved } = props;
  const { createSpace, updateSpace } = useWikiSpaces();
  // states
  const [name, setName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [identifierEdited, setIdentifierEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [access, setAccess] = useState<EWikiSpaceAccess>(EWikiSpaceAccess.OPEN);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setName(space?.name ?? "");
    setIdentifier(space?.identifier ?? "");
    setIdentifierEdited(!!space);
    setDescription(space?.description ?? "");
    setAccess(space?.access ?? EWikiSpaceAccess.OPEN);
    setErrors({});
  }, [isOpen, space]);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrors({});
    const payload = { name, identifier, description, access };
    try {
      const saved = space
        ? await updateSpace(workspaceSlug, space.id, payload)
        : await createSpace(workspaceSlug, payload);
      onSaved?.(saved);
      onClose();
    } catch (error) {
      // field errors come back as { field: ["message"] }
      const fieldErrors = Object.fromEntries(
        Object.entries((error ?? {}) as Record<string, unknown>)
          .filter(([, value]) => Array.isArray(value))
          .map(([key, value]) => [key, String((value as string[])[0])])
      );
      setErrors(fieldErrors);
      if (!Object.keys(fieldErrors).length)
        setToast({
          type: "error",
          title: "Error!",
          message: (error as { error?: string })?.error || "The space could not be saved.",
        });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="md">
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <DialogMain>
            <DialogHeader>
              <DialogHeading>
                <DialogTitle>{space ? "Space settings" : "Create a space"}</DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody>
              <div className="flex flex-col gap-4">
                <InputField
                  id="wiki-space-name"
                  label="Name"
                  size="md"
                  orientation="vertical"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    if (!identifierEdited) setIdentifier(suggestIdentifier(e.target.value));
                  }}
                  placeholder="e.g. Engineering"
                  error={errors.name}
                  required
                />
                <InputField
                  id="wiki-space-identifier"
                  label="Key"
                  size="md"
                  orientation="vertical"
                  value={identifier}
                  onChange={(e) => {
                    setIdentifierEdited(true);
                    setIdentifier(
                      e.target.value
                        .toUpperCase()
                        .replace(/[^A-Z0-9]/g, "")
                        .slice(0, 12)
                    );
                  }}
                  placeholder="ENG"
                  description="2–12 letters or digits, unique in this workspace."
                  error={errors.identifier}
                  required
                />
                <InputField
                  id="wiki-space-description"
                  label="Description"
                  size="md"
                  orientation="vertical"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What this space is for"
                  error={errors.description}
                />
                <fieldset className="flex flex-col gap-2">
                  <legend className="mb-1.5 text-13 text-secondary">Access</legend>
                  {ACCESS_OPTIONS.map((option) => (
                    <label
                      key={option.value}
                      htmlFor={`wiki-space-access-${option.value}`}
                      aria-label={`${option.label}: ${option.description}`}
                      className={cn(
                        "flex cursor-pointer items-start gap-2 rounded-md border border-subtle p-2.5 hover:bg-layer-transparent-hover",
                        { "border-accent-strong": access === option.value }
                      )}
                    >
                      <input
                        id={`wiki-space-access-${option.value}`}
                        type="radio"
                        name="wiki-space-access"
                        className="mt-0.5"
                        checked={access === option.value}
                        onChange={() => setAccess(option.value)}
                      />
                      <span className="flex flex-col">
                        <span className="text-13 font-medium text-primary">{option.label}</span>
                        <span className="text-12 text-tertiary">{option.description}</span>
                      </span>
                    </label>
                  ))}
                </fieldset>
              </div>
            </DialogBody>
          </DialogMain>
          <DialogActions>
            <Button stretch="auto" variant="secondary" size="md" label="Cancel" onClick={onClose} type="button" />
            <Button
              stretch="auto"
              variant="primary"
              size="md"
              type="submit"
              label={isSubmitting ? "Saving…" : space ? "Save" : "Create space"}
              disabled={isSubmitting || !name.trim() || identifier.length < 2}
            />
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
});
