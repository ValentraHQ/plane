/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Mermaid } from "mermaid";

export const MERMAID_LANGUAGE = "mermaid";

export const MERMAID_SAMPLE = `flowchart LR
  A[Idea] --> B{Approved?}
  B -- Yes --> C[Build]
  B -- No --> D[Revise]
  D --> B`;

export type TMermaidTheme = "default" | "dark";

let mermaidPromise: Promise<Mermaid> | undefined;
let initializedTheme: TMermaidTheme | undefined;
// mermaid keeps global state while rendering, so diagrams are rendered one at a time
let queue: Promise<unknown> = Promise.resolve();
let counter = 0;

// mermaid is large: load it only when a page actually contains a diagram
const loadMermaid = () => {
  mermaidPromise ??= import("mermaid").then((module) => module.default);
  return mermaidPromise;
};

/** The app's theme is set by next-themes as `data-theme` on <html>. */
export const getMermaidTheme = (): TMermaidTheme => {
  const theme = document.documentElement.getAttribute("data-theme") ?? "";
  if (theme.includes("dark")) return "dark";
  if (theme === "custom") {
    // custom themes: pick by the brightness of the page background
    const match = getComputedStyle(document.body).backgroundColor.match(/\d+/g);
    if (match && match.length >= 3) {
      const [r, g, b] = match.map(Number);
      if (0.299 * r + 0.587 * g + 0.114 * b < 128) return "dark";
    }
  }
  return "default";
};

/**
 * Render diagram source to an SVG string. `strict` security sanitizes the output and disables
 * click handlers and HTML labels, since page content comes from other users.
 */
export const renderMermaid = (source: string, theme: TMermaidTheme): Promise<string> => {
  const run = async () => {
    const mermaid = await loadMermaid();
    if (initializedTheme !== theme) {
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme, fontFamily: "inherit" });
      initializedTheme = theme;
    }
    const id = `plane-mermaid-${++counter}`;
    try {
      const { svg } = await mermaid.render(id, source);
      return svg;
    } finally {
      // a failed render leaves its scratch element in the document
      document.getElementById(id)?.remove();
      document.getElementById(`d${id}`)?.remove();
    }
  };
  const result = queue.then(run, run);
  queue = result.catch(() => undefined);
  return result;
};
