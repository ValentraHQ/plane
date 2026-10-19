/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { sortBy } from "lodash-es";
import { useEffect, useState } from "react";
import type { TBookAnnotation, TBookAnnotationColor } from "@plane/types";
import { EBookAnnotationVisibility } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import { HIGHLIGHTS } from "./reader-frame";

export const ANNOTATION_COLORS: TBookAnnotationColor[] = ["yellow", "green", "blue", "pink", "purple"];

type Box = { top: number; left: number; bottom: number; right: number };

/** Keep a floating panel on screen, above the box when there is room, else below it. */
function placement(box: Box, width: number, height: number) {
  const left = Math.min(Math.max(8, (box.left + box.right) / 2 - width / 2), window.innerWidth - width - 8);
  const above = box.top - height - 8;
  const top = above > 8 ? above : Math.min(box.bottom + 8, window.innerHeight - height - 8);
  return { left, top };
}

function ColorDots({
  value,
  onPick,
  label = "Highlight",
}: {
  value?: string;
  onPick: (color: TBookAnnotationColor) => void;
  label?: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-1.5">
      {ANNOTATION_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          aria-label={`${label} ${color}`}
          aria-pressed={value === color}
          onClick={() => onPick(color)}
          className={cn("size-6 rounded-full border border-subtle", {
            "ring-2 ring-accent-strong ring-offset-1": value === color,
          })}
          style={{ background: HIGHLIGHTS[color].replace(/[\d.]+\)$/, "0.9)") }}
        />
      ))}
    </div>
  );
}

// --- selection toolbar ---

type ToolbarProps = {
  box: Box;
  onHighlight: (color: TBookAnnotationColor) => void;
  onNote: () => void;
  onCopy: () => void;
};

export function SelectionToolbar({ box, onHighlight, onNote, onCopy }: ToolbarProps) {
  const { left, top } = placement(box, 280, 44);
  return (
    <div
      role="toolbar"
      aria-label="Selected text"
      style={{ left, top }}
      className="shadow-lg fixed z-30 flex items-center gap-2 rounded-lg border border-subtle bg-surface-1 px-2 py-1.5"
      // keep the selection in the page while clicking the toolbar
      onMouseDown={(e) => e.preventDefault()}
    >
      <ColorDots onPick={onHighlight} />
      <span className="h-5 w-px bg-layer-3" />
      <button
        type="button"
        onClick={onNote}
        className="rounded-md px-2 py-1 text-12 text-secondary hover:bg-layer-transparent-hover"
      >
        Note
      </button>
      <button
        type="button"
        onClick={onCopy}
        className="rounded-md px-2 py-1 text-12 text-secondary hover:bg-layer-transparent-hover"
      >
        Copy
      </button>
    </div>
  );
}

// --- one annotation: view / edit ---

type PopoverProps = {
  annotation: TBookAnnotation;
  box: Box | null;
  canShare: boolean;
  /** a new note being written for the current selection */
  isNew?: boolean;
  onSave: (change: { color?: TBookAnnotationColor; note?: string; visibility?: EBookAnnotationVisibility }) => void;
  onDelete: () => void;
  onClose: () => void;
};

export function AnnotationPopover({ annotation, box, canShare, isNew, onSave, onDelete, onClose }: PopoverProps) {
  const [note, setNote] = useState(annotation.note);
  // colour and sharing change at once; the saved annotation follows
  const [color, setColor] = useState(annotation.color);
  const [visibility, setVisibility] = useState(annotation.visibility);
  useEffect(() => setNote(annotation.note), [annotation.id, annotation.note]);
  useEffect(() => setColor(annotation.color), [annotation.id, annotation.color]);
  useEffect(() => setVisibility(annotation.visibility), [annotation.id, annotation.visibility]);
  const editable = annotation.permissions.can_edit;
  const width = 320;
  const position = box ? placement(box, width, 260) : { left: window.innerWidth / 2 - width / 2, top: 120 };

  return (
    <div
      role="dialog"
      aria-label={isNew ? "New note" : annotation.kind === "note" ? "Note" : "Highlight"}
      style={{ ...position, width }}
      className="shadow-lg fixed z-30 flex max-w-[calc(100vw-1rem)] flex-col gap-3 rounded-lg border border-subtle bg-surface-1 p-3"
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      <blockquote className="line-clamp-3 border-l-2 border-subtle pl-2 text-12 text-secondary italic">
        {annotation.quote}
      </blockquote>
      {!editable && <p className="text-11 text-tertiary">Shared by {annotation.user_detail.display_name}</p>}
      {editable && annotation.kind === "highlight" && (
        <ColorDots
          value={color}
          onPick={(picked) => {
            setColor(picked);
            onSave({ color: picked });
          }}
          label="Colour"
        />
      )}
      {editable ? (
        <label className="flex flex-col gap-1">
          <span className="text-11 font-medium text-tertiary">Note</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the user just asked to write a note
            autoFocus={isNew}
            rows={3}
            maxLength={10000}
            placeholder="Add a note…"
            className="resize-y rounded-md border border-subtle bg-surface-1 p-2 text-13 text-primary placeholder:text-placeholder"
          />
        </label>
      ) : (
        annotation.note && <p className="text-13 whitespace-pre-wrap text-primary">{annotation.note}</p>
      )}
      {editable && canShare && (
        <label className="flex items-center gap-2 text-12 text-secondary">
          <input
            type="checkbox"
            checked={visibility === EBookAnnotationVisibility.SHARED}
            onChange={(e) => {
              const picked = e.target.checked ? EBookAnnotationVisibility.SHARED : EBookAnnotationVisibility.PRIVATE;
              setVisibility(picked);
              onSave({ visibility: picked });
            }}
          />
          Share with everyone who can read this book
        </label>
      )}
      <div className="flex items-center justify-between gap-2">
        {annotation.permissions.can_delete ? (
          <button
            type="button"
            onClick={onDelete}
            className="rounded-md px-2 py-1 text-12 text-danger-primary hover:bg-layer-transparent-hover"
          >
            {isNew ? "Discard" : "Delete"}
          </button>
        ) : (
          <span />
        )}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-12 text-secondary hover:bg-layer-transparent-hover"
          >
            Close
          </button>
          {editable && (
            <button
              type="button"
              disabled={(annotation.kind === "note" || isNew) && !note.trim()}
              onClick={() => onSave({ note })}
              className="rounded-md bg-accent-primary px-3 py-1 text-12 font-medium text-on-color disabled:opacity-50"
            >
              Save
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// --- every annotation of the book ---

type PanelProps = {
  annotations: TBookAnnotation[];
  currentUserId: string | undefined;
  orphanIds: Set<string>;
  chapterTitle: (index: number) => string;
  onOpen: (annotation: TBookAnnotation) => void;
  onExport: () => void;
};

const KIND_LABEL = { highlight: "Highlight", note: "Note", bookmark: "Bookmark" };

export function NotesPanel({ annotations, currentUserId, orphanIds, chapterTitle, onOpen, onExport }: PanelProps) {
  const [filter, setFilter] = useState<"all" | "mine" | "shared">("all");
  const shown = annotations.filter((a) =>
    filter === "mine" ? a.user === currentUserId : filter === "shared" ? a.user !== currentUserId : true
  );
  const hasShared = annotations.some((a) => a.user !== currentUserId);
  const groups = new Map<number, TBookAnnotation[]>();
  for (const a of sortBy(shown, ["chapter", "start_offset"])) {
    groups.set(a.chapter, [...(groups.get(a.chapter) ?? []), a]);
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        {hasShared ? (
          <div role="group" aria-label="Show" className="flex gap-1">
            {(["all", "mine", "shared"] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
                className={cn("rounded-md px-2 py-1 text-12 text-secondary hover:bg-layer-transparent-hover", {
                  "bg-layer-transparent-active font-medium text-primary": filter === value,
                })}
              >
                {value === "all" ? "All" : value === "mine" ? "Mine" : "Shared"}
              </button>
            ))}
          </div>
        ) : (
          <span className="text-12 text-tertiary">{annotations.length} in this book</span>
        )}
        <button
          type="button"
          onClick={onExport}
          className="rounded-md px-2 py-1 text-12 text-accent-primary hover:bg-layer-transparent-hover"
        >
          Export Markdown
        </button>
      </div>
      {shown.length === 0 && (
        <p className="text-13 text-tertiary">
          Select text to highlight it or add a note, or use the bookmark button to mark a page.
        </p>
      )}
      {[...groups.entries()].map(([chapterIndex, items]) => (
        <section key={chapterIndex} className="flex flex-col gap-1">
          <h3 className="text-11 font-semibold tracking-wide text-tertiary uppercase">{chapterTitle(chapterIndex)}</h3>
          <ul className="flex flex-col gap-1">
            {items.map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  onClick={() => onOpen(a)}
                  className="flex w-full gap-2 rounded-md p-2 text-left hover:bg-layer-transparent-hover"
                >
                  <span
                    aria-hidden
                    className="mt-1 h-3 w-1 shrink-0 rounded-full"
                    style={{
                      background:
                        a.kind === "highlight" ? HIGHLIGHTS[a.color || "yellow"] : "var(--border-color-subtle, #ccc)",
                    }}
                  />
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-11 text-tertiary">
                      {KIND_LABEL[a.kind]}
                      {a.user !== currentUserId && ` · ${a.user_detail.display_name}`}
                      {a.visibility === EBookAnnotationVisibility.SHARED && a.user === currentUserId && " · Shared"}
                      {orphanIds.has(a.id) && " · not found in the text"}
                    </span>
                    {a.quote && <span className="line-clamp-2 text-12 text-secondary">{a.quote}</span>}
                    {a.note && <span className="line-clamp-3 text-12 text-primary">{a.note}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
