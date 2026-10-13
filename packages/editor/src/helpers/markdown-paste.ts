/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Editor } from "@tiptap/core";
import type { EditorView } from "@tiptap/pm/view";

// block-level markdown: headings, lists, quotes, fences, tables, rules
const BLOCK_PATTERNS = [
  /^#{1,6}\s+\S/m,
  /^\s*[-*+]\s+\S/m,
  /^\s*\d+[.)]\s+\S/m,
  /^>\s?/m,
  /^(```|~~~)/m,
  /^\s*\|.+\|\s*$/m,
  /^\s*(-{3,}|\*{3,}|_{3,})\s*$/m,
];
// inline markdown: bold, links, inline code
const INLINE_PATTERNS = [/\*\*[^*\n]+\*\*/, /\[[^\]\n]+\]\([^)\s]+\)/, /`[^`\n]+`/];

// elements that end a line when the HTML is read as text
const LINE_BREAK_SELECTOR = "br,div,p,li,tr,pre,h1,h2,h3,h4,h5,h6,blockquote";

export const looksLikeMarkdown = (text: string): boolean => {
  const blocks = BLOCK_PATTERNS.filter((pattern) => pattern.test(text)).length;
  const inline = INLINE_PATTERNS.filter((pattern) => pattern.test(text)).length;
  return blocks >= 1 && blocks + inline >= 2;
};

/**
 * Whether the copied HTML is markdown *source* (a code editor, a raw file, a text area) rather than
 * a rendering of it. A rendered view never shows `##`, `|---|` or `**` in its text; a source view
 * does, whatever tags it wraps the lines in.
 */
const isMarkdownSourceHtml = (html: string): boolean => {
  if (!html) return true;
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.body.querySelectorAll(LINE_BREAK_SELECTOR).forEach((element) => element.after("\n"));
  return looksLikeMarkdown(doc.body.textContent ?? "");
};

const isMarkdownSource = (view: EditorView, data: DataTransfer, text: string): boolean => {
  // Shift+paste means "paste as plain text"
  if ((view as unknown as { input?: { shiftKey?: boolean } }).input?.shiftKey) return false;
  // inside a code block the source is pasted as is
  if (view.state.selection.$from.parent.type.spec.code) return false;
  if (!text || !looksLikeMarkdown(text)) return false;
  // VS Code tells the language: only a markdown file is pasted as markdown
  const vscode = data.getData("vscode-editor-data");
  if (vscode) {
    try {
      return (JSON.parse(vscode) as { mode?: string }).mode === "markdown";
    } catch {
      return false;
    }
  }
  return isMarkdownSourceHtml(data.getData("text/html"));
};

/**
 * Markdown copied from a code editor or a raw view comes with HTML that just wraps the text, which
 * ProseMirror prefers over the plain text, so the markdown would be pasted literally. Returns the
 * markdown converted to HTML (by the editor's markdown parser), or null to let the normal paste run.
 */
export const getMarkdownToPaste = (view: EditorView, event: ClipboardEvent): string | null => {
  const data = event.clipboardData;
  if (!data) return null;
  const text = data.getData("text/plain");
  if (!isMarkdownSource(view, data, text)) return null;
  // tiptap keeps a reference to the editor on its root element
  const editor = (view.dom as HTMLElement & { editor?: Editor }).editor;
  // tiptap-markdown's storage has the parser at runtime, but its types leave it out
  const markdown = editor?.storage.markdown as { parser?: { parse: (content: string) => string } } | undefined;
  return markdown?.parser ? markdown.parser.parse(text) : null;
};
