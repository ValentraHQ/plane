/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { TextSelection } from "@tiptap/pm/state";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewContent } from "@tiptap/react";
import { useEffect, useRef, useState } from "react";
import { CodeOutline, EditOutline, TickOutline } from "@makeplane/propel/icons";
// plane utils
import { cn } from "@plane/utils";
// local imports
import type { TMermaidTheme } from "./render";
import { getMermaidTheme, renderMermaid } from "./render";

type Props = Pick<NodeViewProps, "node" | "editor" | "getPos">;

const RENDER_DELAY_MS = 350;

/**
 * A code block in the `mermaid` language: shows the rendered diagram, and the source while it
 * is being edited. The source stays the node's content, so collaboration, saved HTML and
 * markdown import / export treat it like any other code block.
 */
export function MermaidBlock({ node, editor, getPos }: Props) {
  const source = node.textContent;
  const isEditable = editor.isEditable;
  // states
  // opened with "Edit" (editable) or "Show source" (read-only)
  const [showSource, setShowSource] = useState(false);
  const [isCursorInside, setIsCursorInside] = useState(false);
  const [svg, setSvg] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | undefined>(undefined);
  const [theme, setTheme] = useState<TMermaidTheme>(() => getMermaidTheme());
  // render the first time right away, then wait for typing to pause
  const hasRendered = useRef(false);

  // follow light / dark theme switches
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(getMermaidTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  // the source is also shown while the cursor is inside it, so nothing is typed out of sight
  useEffect(() => {
    if (!isEditable) return;
    const handleTransaction = () => {
      const pos = typeof getPos === "function" ? getPos() : undefined;
      const current = typeof pos === "number" ? editor.state.doc.nodeAt(pos) : null;
      if (typeof pos !== "number" || !current) return;
      const { from, to } = editor.state.selection;
      setIsCursorInside(from > pos && to < pos + current.nodeSize);
    };
    handleTransaction();
    editor.on("transaction", handleTransaction);
    return () => {
      editor.off("transaction", handleTransaction);
    };
  }, [editor, getPos, isEditable]);

  useEffect(() => {
    if (source.trim() === "") {
      setSvg(undefined);
      setError(undefined);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(
      () => {
        renderMermaid(source, theme)
          .then((result) => {
            if (cancelled) return;
            hasRendered.current = true;
            setSvg(result);
            setError(undefined);
            return;
          })
          .catch((err: unknown) => {
            if (cancelled) return;
            setError(err instanceof Error ? err.message : String(err));
          });
      },
      hasRendered.current ? RENDER_DELAY_MS : 0
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [source, theme]);

  const openSource = () => {
    setShowSource(true);
    const pos = typeof getPos === "function" ? getPos() : undefined;
    // put the cursor at the end of the source
    if (typeof pos === "number")
      editor
        .chain()
        .focus()
        .setTextSelection(pos + node.nodeSize - 1)
        .run();
  };

  const closeSource = () => {
    setShowSource(false);
    const pos = typeof getPos === "function" ? getPos() : undefined;
    if (typeof pos !== "number") return;
    // move the cursor to the start of the next block (adding a paragraph if the diagram is last).
    // Dispatched directly: a chained focus() would restore the old cursor inside the source.
    const { state, view } = editor;
    const { tr } = state;
    const after = pos + (tr.doc.nodeAt(pos)?.nodeSize ?? node.nodeSize);
    if (after >= tr.doc.content.size) tr.insert(after, state.schema.nodes.paragraph.create());
    tr.setSelection(TextSelection.near(tr.doc.resolve(after + 1), 1));
    view.dispatch(tr.scrollIntoView());
    view.focus();
  };

  const isSourceVisible = showSource || (isEditable && (isCursorInside || source.trim() === ""));

  return (
    <div className="my-2 rounded-lg border border-subtle bg-layer-1" data-mermaid-block="">
      <div
        className="flex items-center justify-between gap-2 border-b border-subtle px-3 py-1.5"
        contentEditable={false}
        data-mermaid-controls=""
      >
        <span className="text-11 font-medium tracking-wide text-tertiary uppercase">Mermaid</span>
        {isEditable ? (
          <button
            type="button"
            // keep the click from moving the editor cursor into the source first
            onMouseDown={(e) => e.preventDefault()}
            className="flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-12 text-secondary hover:bg-layer-1-hover hover:text-primary"
            onClick={isSourceVisible ? closeSource : openSource}
          >
            {isSourceVisible ? <TickOutline className="size-3" /> : <EditOutline className="size-3" />}
            {isSourceVisible ? "Done" : "Edit"}
          </button>
        ) : (
          <button
            type="button"
            // keep the click from moving the editor cursor into the source first
            onMouseDown={(e) => e.preventDefault()}
            className="flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-12 text-secondary hover:bg-layer-1-hover hover:text-primary"
            onClick={() => setShowSource((value) => !value)}
          >
            <CodeOutline className="size-3" />
            {showSource ? "Hide source" : "Show source"}
          </button>
        )}
      </div>
      {/* the source is the node's editable content; it stays mounted while hidden */}
      <pre className={cn("m-0 rounded-none bg-layer-3 p-4 text-primary", { hidden: !isSourceVisible })}>
        <NodeViewContent as="code" className="whitespace-pre-wrap" />
      </pre>
      <div contentEditable={false} data-mermaid-controls="">
        {error ? (
          <p className="font-mono px-4 py-3 text-12 whitespace-pre-wrap text-danger-primary" role="alert">
            {error}
          </p>
        ) : source.trim() === "" ? (
          <p className="px-4 py-3 text-12 text-placeholder">Write a Mermaid diagram above.</p>
        ) : svg ? (
          // sanitized by mermaid (securityLevel "strict")
          <div
            role="img"
            aria-label="Mermaid diagram"
            className="flex justify-center overflow-x-auto p-4 [&_svg]:h-auto [&_svg]:max-w-full"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        ) : (
          <p className="px-4 py-3 text-12 text-placeholder">Rendering diagram…</p>
        )}
      </div>
    </div>
  );
}
