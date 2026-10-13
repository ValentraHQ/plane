/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { FormEvent } from "react";
import { useState } from "react";
import type { TBookSearchResponse, TBookTocEntry, TReaderPreferences } from "@plane/types";
import { cn } from "@plane/utils";

// --- table of contents ---

type TocProps = {
  entries: TBookTocEntry[];
  /** spine chapters, for books without a table of contents */
  chapters: { index: number; title: string }[];
  currentChapter: number;
  onSelect: (chapter: number, fragment: string) => void;
};

function TocEntries({ entries, currentChapter, onSelect, depth }: Omit<TocProps, "chapters"> & { depth: number }) {
  return (
    <ol className={cn("flex flex-col", depth && "ml-3 border-l border-subtle pl-2")}>
      {entries.map((entry, index) => (
        // oxlint-disable-next-line react/no-array-index-key -- TOC entries have no identity; the list never reorders
        <li key={`${depth}-${index}`}>
          <button
            type="button"
            disabled={entry.chapter === null}
            aria-current={entry.chapter === currentChapter && !entry.fragment ? "true" : undefined}
            onClick={() => entry.chapter !== null && onSelect(entry.chapter, entry.fragment)}
            className={cn(
              "w-full rounded-sm px-2 py-1.5 text-left text-13 text-secondary hover:bg-layer-transparent-hover disabled:opacity-60",
              {
                "bg-layer-transparent-active font-medium text-primary":
                  entry.chapter === currentChapter && !entry.fragment,
              }
            )}
          >
            {entry.title || "Untitled"}
          </button>
          {entry.children.length > 0 && depth < 4 && (
            <TocEntries
              entries={entry.children}
              currentChapter={currentChapter}
              onSelect={onSelect}
              depth={depth + 1}
            />
          )}
        </li>
      ))}
    </ol>
  );
}

export function TocPanel({ entries, chapters, currentChapter, onSelect }: TocProps) {
  if (entries.length)
    return <TocEntries entries={entries} currentChapter={currentChapter} onSelect={onSelect} depth={0} />;
  return (
    <TocEntries
      entries={chapters.map((c) => ({
        title: c.title || `Section ${c.index + 1}`,
        chapter: c.index,
        fragment: "",
        children: [],
      }))}
      currentChapter={currentChapter}
      onSelect={onSelect}
      depth={0}
    />
  );
}

// --- reading settings ---

type SettingsProps = {
  preferences: TReaderPreferences;
  onChange: (change: Partial<TReaderPreferences>) => void;
};

const option = (active: boolean) =>
  cn("flex-1 rounded-md border border-subtle px-2 py-1.5 text-12 text-secondary hover:bg-layer-transparent-hover", {
    "border-accent-strong bg-layer-transparent-active font-medium text-primary": active,
  });

export function SettingsPanel({ preferences, onChange }: SettingsProps) {
  const groups: {
    label: string;
    key: keyof TReaderPreferences;
    options: { value: string | number; label: string }[];
  }[] = [
    {
      label: "Theme",
      key: "theme",
      options: [
        { value: "light", label: "Light" },
        { value: "sepia", label: "Sepia" },
        { value: "dark", label: "Dark" },
        { value: "system", label: "Auto" },
      ],
    },
    {
      label: "Layout",
      key: "layout",
      options: [
        { value: "paginated", label: "Pages" },
        { value: "scroll", label: "Scroll" },
      ],
    },
    {
      label: "Line spacing",
      key: "line_height",
      options: [
        { value: 1.3, label: "Tight" },
        { value: 1.6, label: "Normal" },
        { value: 1.9, label: "Loose" },
      ],
    },
    {
      label: "Margins",
      key: "margin",
      options: [
        { value: "narrow", label: "Narrow" },
        { value: "normal", label: "Normal" },
        { value: "wide", label: "Wide" },
      ],
    },
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <span className="text-12 font-medium text-tertiary">Text size</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className={option(false)}
            aria-label="Smaller text"
            disabled={preferences.font_size <= 12}
            onClick={() => onChange({ font_size: Math.max(12, preferences.font_size - 2) })}
          >
            A−
          </button>
          <span className="w-12 text-center text-13 text-primary" aria-live="polite">
            {preferences.font_size}px
          </span>
          <button
            type="button"
            className={option(false)}
            aria-label="Larger text"
            disabled={preferences.font_size >= 32}
            onClick={() => onChange({ font_size: Math.min(32, preferences.font_size + 2) })}
          >
            A+
          </button>
        </div>
      </div>
      <label className="flex flex-col gap-1.5">
        <span className="text-12 font-medium text-tertiary">Font</span>
        <select
          className="h-8 rounded-md border border-subtle bg-surface-1 px-2 text-13 text-primary"
          value={preferences.font_family}
          onChange={(e) => onChange({ font_family: e.target.value as TReaderPreferences["font_family"] })}
        >
          <option value="publisher">Book's own</option>
          <option value="serif">Serif</option>
          <option value="sans">Sans-serif</option>
          <option value="mono">Monospace</option>
          <option value="dyslexic">Dyslexia-friendly</option>
        </select>
      </label>
      {groups.map((group) => (
        <div key={group.key} role="group" aria-label={group.label} className="flex flex-col gap-1.5">
          <span className="text-12 font-medium text-tertiary">{group.label}</span>
          <div className="flex gap-1.5">
            {group.options.map((choice) => (
              <button
                key={String(choice.value)}
                type="button"
                aria-pressed={preferences[group.key] === choice.value}
                className={option(preferences[group.key] === choice.value)}
                onClick={() => onChange({ [group.key]: choice.value } as Partial<TReaderPreferences>)}
              >
                {choice.label}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// --- search inside the book ---

type SearchProps = {
  onSearch: (query: string) => Promise<TBookSearchResponse>;
  onSelect: (chapter: number, text: string, occurrence: number) => void;
};

export function SearchPanel({ onSearch, onSelect }: SearchProps) {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<TBookSearchResponse | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (query.trim().length < 2) return;
    setIsSearching(true);
    setError(null);
    try {
      setResponse(await onSearch(query.trim()));
    } catch {
      setError("The search failed. Try again.");
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <form onSubmit={submit} role="search" className="flex gap-2">
        <label className="flex-1">
          <span className="sr-only">Search in this book</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search in this book"
            className="h-8 w-full rounded-md border border-subtle bg-surface-1 px-2 text-13 text-primary placeholder:text-placeholder"
          />
        </label>
        <button
          type="submit"
          disabled={query.trim().length < 2 || isSearching}
          className="rounded-md border border-subtle px-3 text-13 text-secondary hover:bg-layer-transparent-hover disabled:opacity-60"
        >
          {isSearching ? "…" : "Find"}
        </button>
      </form>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {error}
        </p>
      )}
      {response && (
        <>
          <p className="text-12 text-tertiary" aria-live="polite">
            {response.results.length === 0
              ? `No matches for “${response.query}”.`
              : `${response.results.length}${response.truncated ? "+" : ""} matches`}
          </p>
          <ul className="flex min-h-0 flex-col gap-1 overflow-y-auto" aria-label="Search results">
            {response.results.map((result) => (
              <li key={`${result.chapter}-${result.occurrence}`}>
                <button
                  type="button"
                  onClick={() => onSelect(result.chapter, result.match, result.occurrence)}
                  className="w-full rounded-md px-2 py-1.5 text-left hover:bg-layer-transparent-hover"
                >
                  <span className="block truncate text-11 text-tertiary">
                    {result.chapter_title || `Section ${result.chapter + 1}`}
                  </span>
                  <span className="line-clamp-2 text-12 text-secondary">
                    …{result.before}
                    <mark className="rounded-sm bg-warning-subtle px-0.5 text-primary">{result.match}</mark>
                    {result.after}…
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
