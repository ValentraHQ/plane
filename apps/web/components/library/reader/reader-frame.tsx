/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from "react";
import type { TBookAnnotation, TBookChapterContent, TReaderPreferences } from "@plane/types";

/**
 * One chapter of a book, rendered in an iframe that is sandboxed without scripts (the HTML was
 * sanitized on the server; this is the second line of defense) and carries its own
 * Content-Security-Policy: only the book's signed images and inline styles may load.
 *
 * Positions are character offsets into the chapter's text (document.body.textContent), so they
 * survive font, size, margin and window changes.
 */

export type TReaderFramePosition = { offset: number; quote: string; fraction: number; textLength: number };

/** The current text selection as an anchor, with its box in the frame's coordinates. */
export type TReaderSelection = {
  start: number;
  end: number;
  quote: string;
  prefix: string;
  suffix: string;
  rect: { top: number; left: number; bottom: number; right: number };
};

export type TReaderFrameHandle = {
  /** move one page (paginated) or one screen (scroll); false when already at the edge of the chapter */
  next: () => boolean;
  previous: () => boolean;
  goToOffset: (offset: number) => void;
  goToFragment: (fragment: string) => boolean;
  goToEnd: () => void;
  /** select and show the n-th occurrence of text in this chapter */
  showOccurrence: (text: string, occurrence: number) => boolean;
  position: () => TReaderFramePosition | null;
  pageInfo: () => { page: number; pages: number };
  focus: () => void;
  selection: () => TReaderSelection | null;
  clearSelection: () => void;
  /** draw annotations of this chapter; returns the ids that could not be placed in the text */
  showAnnotations: (annotations: TBookAnnotation[], currentUserId: string | undefined) => string[];
  pageOfOffset: (offset: number) => number;
  /** box of an annotation's first mark, in the frame's coordinates */
  annotationRect: (id: string) => TReaderSelection["rect"] | null;
};

type Props = {
  chapter: TBookChapterContent;
  preferences: TReaderPreferences;
  /** dark / light resolved for the "system" theme */
  systemDark: boolean;
  onReady: () => void;
  onPositionChange: () => void;
  onChapterLink: (chapter: number, fragment: string) => void;
  onKey: (event: KeyboardEvent) => void;
  /** tap / swipe navigation inside the page */
  onTurn: (direction: "next" | "previous") => void;
  /** the selection changed (null when cleared) */
  onSelection: (selection: TReaderSelection | null) => void;
  onAnnotationClick: (id: string) => void;
};

export const THEMES = {
  light: { bg: "#ffffff", fg: "#1f2328", link: "#0b63c4" },
  dark: { bg: "#16181d", fg: "#e3e5e8", link: "#79b8ff" },
  sepia: { bg: "#f4ecd8", fg: "#4a3b2a", link: "#7a4b12" },
};

const FONTS: Record<TReaderPreferences["font_family"], string | null> = {
  publisher: null,
  serif: 'Georgia, "Iowan Old Style", "Times New Roman", serif',
  sans: 'system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
  mono: 'ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace',
  dyslexic: '"OpenDyslexic", "Comic Sans MS", Verdana, sans-serif',
};

const MARGINS = { narrow: 16, normal: 40, wide: 88 };

export const HIGHLIGHTS: Record<string, string> = {
  yellow: "rgba(255, 213, 0, 0.42)",
  green: "rgba(52, 199, 89, 0.32)",
  blue: "rgba(10, 132, 255, 0.28)",
  pink: "rgba(255, 55, 135, 0.28)",
  purple: "rgba(175, 82, 222, 0.30)",
};
const HIGHLIGHTS_DARK: Record<string, string> = {
  yellow: "rgba(255, 214, 10, 0.32)",
  green: "rgba(48, 209, 88, 0.30)",
  blue: "rgba(64, 156, 255, 0.34)",
  pink: "rgba(255, 55, 135, 0.34)",
  purple: "rgba(191, 90, 242, 0.36)",
};
const CONTEXT = 32;

const escapeAttr = (value: string) => value.replace(/[&"<>]/g, (c) => `&#${c.charCodeAt(0)};`);

function readerCss(preferences: TReaderPreferences, systemDark: boolean, width: number) {
  const theme =
    preferences.theme === "system"
      ? THEMES[systemDark ? "dark" : "light"]
      : (THEMES[preferences.theme] ?? THEMES.light);
  // keep the margin sensible on narrow screens
  const margin = Math.min(MARGINS[preferences.margin], Math.max(12, Math.round(width * 0.08)));
  const font = FONTS[preferences.font_family];
  const paginated = preferences.layout === "paginated";
  return `
:root { color-scheme: ${theme === THEMES.dark ? "dark" : "light"}; }
html { margin: 0; padding: 0; background: ${theme.bg} !important; ${paginated ? "height: 100%; overflow: hidden;" : ""} }
body {
  margin: 0 !important; box-sizing: border-box;
  padding: ${paginated ? `40px ${margin}px` : `32px ${margin}px 96px`} !important;
  background: ${theme.bg} !important; color: ${theme.fg} !important;
  font-size: ${preferences.font_size}px !important; line-height: ${preferences.line_height} !important;
  overflow-wrap: break-word; -webkit-text-size-adjust: 100%;
  ${font ? `font-family: ${font} !important;` : ""}
  ${
    paginated
      ? // one column per page: column + gap = the frame's width, so a page turn is exactly one width
        `height: 100vh; column-width: ${Math.max(100, width - 2 * margin)}px; column-gap: ${2 * margin}px; column-fill: auto; max-width: none !important;`
      : "max-width: 46em; margin: 0 auto !important;"
  }
}
body * { color: inherit !important; background-color: transparent !important; ${font ? `font-family: ${font} !important;` : ""} }
p, li, blockquote, dd { line-height: ${preferences.line_height} !important; }
pre, code, kbd, samp { font-family: ${FONTS.mono} !important; white-space: pre-wrap; }
a { color: ${theme.link} !important; }
img { max-width: 100% !important; max-height: ${paginated ? "calc(100vh - 80px)" : "90vh"}; height: auto !important; object-fit: contain; break-inside: avoid; }
table { max-width: 100%; border-collapse: collapse; }
h1, h2, h3, h4, h5, h6 { break-after: avoid; line-height: 1.25 !important; }
::selection { background: ${theme === THEMES.dark ? "#3a5a8c" : "#b7d3ff"}; }
mark.plane-annotation { color: inherit !important; border-radius: 2px; cursor: pointer; padding: 0 !important; }
${Object.entries(theme === THEMES.dark ? HIGHLIGHTS_DARK : HIGHLIGHTS)
  .map(([color, value]) => `mark.plane-annotation.plane-color-${color} { background-color: ${value} !important; }`)
  .join("\n")}
mark.plane-annotation.plane-kind-note { background-color: transparent !important; text-decoration: underline 2px dotted; text-underline-offset: 3px; }
mark.plane-annotation.plane-others { opacity: 0.75; text-decoration: underline 1px dashed; text-underline-offset: 3px; }
mark.plane-annotation.plane-flash { outline: 2px solid ${theme.link}; outline-offset: 1px; }
`;
}

function buildDocument(chapter: TBookChapterContent) {
  // only the origins of the book's own signed resources may load
  const origins = new Set<string>();
  for (const match of `${chapter.html} ${chapter.css}`.matchAll(/(?:src="|url\(")(https?:\/\/[^"/]+)/g)) {
    origins.add(match[1]);
  }
  const csp = [
    "default-src 'none'",
    // 'none' may not be combined with other sources
    `img-src ${[...origins, "data:"].join(" ")}`,
    "style-src 'unsafe-inline'",
    "font-src 'none'",
    "media-src 'none'",
    "form-action 'none'",
  ].join("; ");
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${escapeAttr(csp)}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style id="plane-book-css">${chapter.css.replace(/<\/style/gi, "<\\/style")}</style>
<style id="plane-reader-css"></style>
</head><body>${chapter.html}</body></html>`;
}

/** Walk text nodes; map between a global character offset and (node, offset). */
function textNodes(doc: Document) {
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) nodes.push(node as Text);
  return nodes;
}

function locate(doc: Document, offset: number): { node: Text; offset: number } | null {
  let remaining = offset;
  const nodes = textNodes(doc);
  for (const node of nodes) {
    const length = node.data.length;
    if (remaining <= length) return { node, offset: remaining };
    remaining -= length;
  }
  const last = nodes[nodes.length - 1];
  return last ? { node: last, offset: last.data.length } : null;
}

function offsetOf(doc: Document, target: Node, localOffset: number) {
  let total = 0;
  for (const node of textNodes(doc)) {
    if (node === target) return total + localOffset;
    total += node.data.length;
  }
  return total;
}

const normalize = (text: string) => text.replace(/\s+/g, " ").trim();

/** Remove drawn annotation marks, keeping their text (and therefore every offset). */
function clearMarks(doc: Document) {
  const marks = Array.from(doc.querySelectorAll("mark.plane-annotation"));
  const parents = new Set<Node>();
  for (const mark of marks) {
    const parent = mark.parentNode;
    if (!parent) continue;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    parents.add(parent);
  }
  parents.forEach((parent) => parent.normalize());
}

/**
 * Where an annotation's passage is now: its stored offsets when the text there still matches,
 * otherwise the occurrence of its quote that best fits its context and old position.
 */
function resolveAnchor(text: string, annotation: TBookAnnotation): [number, number] | null {
  const { start_offset: start, end_offset: end, quote } = annotation;
  if (!quote) return end > start && end <= text.length ? [start, end] : null;
  if (normalize(text.slice(start, end)) === normalize(quote)) return [start, end];
  let best: [number, number] | null = null;
  let bestScore = -Infinity;
  for (let index = text.indexOf(quote); index >= 0; index = text.indexOf(quote, index + 1)) {
    const before = text.slice(Math.max(0, index - CONTEXT), index);
    const after = text.slice(index + quote.length, index + quote.length + CONTEXT);
    const score =
      (annotation.prefix && before.endsWith(annotation.prefix.slice(-16)) ? 2 : 0) +
      (annotation.suffix && after.startsWith(annotation.suffix.slice(0, 16)) ? 2 : 0) -
      Math.abs(index - start) / Math.max(1, text.length);
    if (score > bestScore) {
      bestScore = score;
      best = [index, index + quote.length];
    }
  }
  return best;
}

/** Wrap [start, end) of the document's text in marks, one per text node it crosses. */
function wrapRange(doc: Document, start: number, end: number, make: () => HTMLElement) {
  let position = 0;
  for (const node of textNodes(doc)) {
    const length = node.data.length;
    const from = Math.max(start, position);
    const to = Math.min(end, position + length);
    if (from < to) {
      let target = node;
      if (from > position) target = target.splitText(from - position);
      if (to < position + length) target.splitText(to - from);
      const mark = make();
      target.parentNode?.insertBefore(mark, target);
      mark.appendChild(target);
    }
    position += length;
    if (position >= end) break;
  }
}

export const ReaderFrame = forwardRef<TReaderFrameHandle, Props>(function ReaderFrame(props, ref) {
  const {
    chapter,
    preferences,
    systemDark,
    onReady,
    onPositionChange,
    onChapterLink,
    onKey,
    onTurn,
    onSelection,
    onAnnotationClick,
  } = props;
  const frame = useRef<HTMLIFrameElement>(null);
  const callbacks = useRef({ onReady, onPositionChange, onChapterLink, onKey, onTurn, onSelection, onAnnotationClick });
  callbacks.current = { onReady, onPositionChange, onChapterLink, onKey, onTurn, onSelection, onAnnotationClick };
  const paginated = preferences.layout === "paginated";

  const doc = () => frame.current?.contentDocument ?? null;
  const pageWidth = () => frame.current?.clientWidth ?? 1;
  const scroller = () => doc()?.scrollingElement as HTMLElement | null;

  const applyStyles = useCallback(() => {
    const d = doc();
    const style = d?.getElementById("plane-reader-css");
    if (style) style.textContent = readerCss(preferences, systemDark, pageWidth());
  }, [preferences, systemDark]);

  const pageCount = () => {
    const el = scroller();
    return el ? Math.max(1, Math.round(el.scrollWidth / pageWidth())) : 1;
  };

  const showRect = (rect: DOMRect) => {
    const el = scroller();
    if (!el) return;
    if (paginated) {
      const page = Math.floor((rect.left + el.scrollLeft) / pageWidth());
      el.scrollLeft = Math.max(0, Math.min(page, pageCount() - 1)) * pageWidth();
    } else {
      el.scrollTop = Math.max(0, rect.top + el.scrollTop - 48);
    }
  };

  const goToOffset = (offset: number) => {
    const d = doc();
    const spot = d && locate(d, offset);
    if (!d || !spot) return;
    const range = d.createRange();
    range.setStart(spot.node, Math.min(spot.offset, spot.node.data.length));
    range.collapse(true);
    const rect = range.getBoundingClientRect();
    // an empty range has no box in some browsers: fall back to its parent element
    showRect(rect.width || rect.height ? rect : (spot.node.parentElement?.getBoundingClientRect() ?? rect));
  };

  const position = (): TReaderFramePosition | null => {
    const d = doc();
    const el = scroller();
    if (!d || !el) return null;
    const total = d.body.textContent?.length ?? 0;
    // the first character at the top-left of what is on screen
    const view = d.defaultView;
    const style = view?.getComputedStyle(d.body);
    const padLeft = parseFloat(style?.paddingLeft ?? "0");
    const padTop = parseFloat(style?.paddingTop ?? "0");
    let offset = 0;
    const probe = (x: number, y: number) => {
      const caret =
        (d as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }).caretRangeFromPoint?.(
          x,
          y
        ) ??
        (() => {
          const p = (
            d as Document & {
              caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
            }
          ).caretPositionFromPoint?.(x, y);
          if (!p) return null;
          const r = d.createRange();
          r.setStart(p.offsetNode, p.offset);
          return r;
        })();
      return caret && caret.startContainer.nodeType === Node.TEXT_NODE
        ? offsetOf(d, caret.startContainer, caret.startOffset)
        : null;
    };
    const found =
      probe(padLeft + 4, paginated ? padTop + 4 : 8) ?? probe(pageWidth() / 2, (view?.innerHeight ?? 400) / 3);
    if (found !== null) offset = found;
    else if (paginated) offset = Math.round((el.scrollLeft / Math.max(1, el.scrollWidth)) * total);
    else offset = Math.round((el.scrollTop / Math.max(1, el.scrollHeight)) * total);
    const quote = (d.body.textContent ?? "")
      .slice(offset, offset + 60)
      .replace(/\s+/g, " ")
      .trim();
    const atEnd = paginated
      ? el.scrollLeft + pageWidth() >= el.scrollWidth - 2
      : el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
    return { offset, quote, fraction: atEnd ? 1 : total ? offset / total : 0, textLength: total };
  };

  useImperativeHandle(ref, () => ({
    next: () => {
      const el = scroller();
      if (!el) return false;
      if (paginated) {
        if (el.scrollLeft + pageWidth() >= el.scrollWidth - 2) return false;
        el.scrollLeft += pageWidth();
      } else {
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 2) return false;
        el.scrollTop += el.clientHeight * 0.9;
      }
      callbacks.current.onPositionChange();
      return true;
    },
    previous: () => {
      const el = scroller();
      if (!el) return false;
      if (paginated) {
        if (el.scrollLeft <= 1) return false;
        el.scrollLeft -= pageWidth();
      } else {
        if (el.scrollTop <= 1) return false;
        el.scrollTop -= el.clientHeight * 0.9;
      }
      callbacks.current.onPositionChange();
      return true;
    },
    goToOffset: (offset) => {
      goToOffset(offset);
      callbacks.current.onPositionChange();
    },
    goToFragment: (fragment) => {
      const target = doc()?.getElementById(fragment);
      if (!target) return false;
      showRect(target.getBoundingClientRect());
      callbacks.current.onPositionChange();
      return true;
    },
    goToEnd: () => {
      const el = scroller();
      if (!el) return;
      if (paginated) el.scrollLeft = (pageCount() - 1) * pageWidth();
      else el.scrollTop = el.scrollHeight;
      callbacks.current.onPositionChange();
    },
    showOccurrence: (text, occurrence) => {
      const d = doc();
      if (!d || !text) return false;
      // the server collapses whitespace; search the rendered text the same way
      const nodes = textNodes(d);
      let flat = "";
      const map: { node: Text; start: number }[] = [];
      for (const node of nodes) {
        map.push({ node, start: flat.length });
        flat += node.data;
      }
      const haystack = flat.toLowerCase();
      const needle = text.toLowerCase();
      let index = -1;
      for (let n = 0, from = 0; n <= occurrence; n++) {
        index = haystack.indexOf(needle, from);
        if (index < 0) break;
        from = index + needle.length;
      }
      if (index < 0) return false;
      const startSpot = locate(d, index);
      const endSpot = locate(d, index + needle.length);
      if (!startSpot || !endSpot) return false;
      const range = d.createRange();
      range.setStart(startSpot.node, startSpot.offset);
      range.setEnd(endSpot.node, endSpot.offset);
      showRect(range.getBoundingClientRect());
      const selection = d.defaultView?.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      callbacks.current.onPositionChange();
      return true;
    },
    position,
    pageInfo: () => {
      const el = scroller();
      if (!el) return { page: 1, pages: 1 };
      if (paginated) return { page: Math.round(el.scrollLeft / pageWidth()) + 1, pages: pageCount() };
      return {
        page: Math.round(el.scrollTop / Math.max(1, el.clientHeight)) + 1,
        pages: Math.max(1, Math.round(el.scrollHeight / Math.max(1, el.clientHeight))),
      };
    },
    focus: () => frame.current?.contentWindow?.focus(),
    selection: () => readSelection(),
    clearSelection: () => doc()?.getSelection()?.removeAllRanges(),
    showAnnotations: (annotations, currentUserId) => {
      const d = doc();
      if (!d) return annotations.map((a) => a.id);
      clearMarks(d);
      const text = d.body.textContent ?? "";
      const orphans: string[] = [];
      // later starts first is not needed: wrapping never changes the text, so offsets stay valid
      for (const annotation of annotations) {
        if (annotation.kind === "bookmark") continue;
        const span = resolveAnchor(text, annotation);
        if (!span) {
          orphans.push(annotation.id);
          continue;
        }
        wrapRange(d, span[0], span[1], () => {
          const mark = d.createElement("mark");
          mark.className = [
            "plane-annotation",
            `plane-kind-${annotation.kind}`,
            annotation.kind === "highlight" ? `plane-color-${annotation.color || "yellow"}` : "",
            annotation.user !== currentUserId ? "plane-others" : "",
          ].join(" ");
          mark.dataset.annotationId = annotation.id;
          return mark;
        });
      }
      return orphans;
    },
    pageOfOffset: (offset) => {
      const d = doc();
      const el = scroller();
      const spot = d && locate(d, offset);
      if (!d || !el || !spot) return 1;
      const range = d.createRange();
      range.setStart(spot.node, Math.min(spot.offset, spot.node.data.length));
      const rect = range.getBoundingClientRect();
      const box = rect.width || rect.height ? rect : (spot.node.parentElement?.getBoundingClientRect() ?? rect);
      if (paginated) return Math.floor((box.left + el.scrollLeft) / pageWidth()) + 1;
      return Math.floor((box.top + el.scrollTop) / Math.max(1, el.clientHeight)) + 1;
    },
    annotationRect: (id) => {
      const mark = doc()?.querySelector(`mark[data-annotation-id="${CSS.escape(id)}"]`);
      if (!mark) return null;
      const r = mark.getBoundingClientRect();
      return { top: r.top, left: r.left, bottom: r.bottom, right: r.right };
    },
  }));

  function readSelection(): TReaderSelection | null {
    const d = doc();
    const selection = d?.getSelection();
    if (!d || !selection || selection.isCollapsed || selection.rangeCount === 0) return null;
    const range = selection.getRangeAt(0);
    if (!d.body.contains(range.commonAncestorContainer)) return null;
    // a boundary's offset = the length of the text from the chapter's start up to it
    const offsetAt = (container: Node, offset: number) => {
      const before = d.createRange();
      before.setStart(d.body, 0);
      before.setEnd(container, offset);
      return before.toString().length;
    };
    const start = offsetAt(range.startContainer, range.startOffset);
    const end = offsetAt(range.endContainer, range.endOffset);
    if (end <= start) return null;
    const text = d.body.textContent ?? "";
    const rect = range.getBoundingClientRect();
    return {
      start,
      end,
      quote: text.slice(start, end).slice(0, 4000),
      prefix: text.slice(Math.max(0, start - CONTEXT), start),
      suffix: text.slice(end, end + CONTEXT),
      rect: { top: rect.top, left: rect.left, bottom: rect.bottom, right: rect.right },
    };
  }

  // a new chapter: write the document, then wire its events
  useEffect(() => {
    const iframe = frame.current;
    if (!iframe) return;
    const handleLoad = () => {
      const d = iframe.contentDocument;
      if (!d) return;
      applyStyles();
      d.addEventListener("click", (event) => {
        const mark = (event.target as Element | null)?.closest?.("mark.plane-annotation") as HTMLElement | null;
        if (mark && !d.getSelection()?.toString()) {
          callbacks.current.onAnnotationClick(mark.dataset.annotationId ?? "");
          return;
        }
        const anchor = (event.target as Element | null)?.closest?.("a[href]");
        if (anchor) {
          event.preventDefault();
          const href = anchor.getAttribute("href") ?? "";
          const internal = href.match(/^plane-chapter:(\d+)(?:#(.*))?$/);
          if (internal) callbacks.current.onChapterLink(Number(internal[1]), decodeURIComponent(internal[2] ?? ""));
          else if (/^(https?:|mailto:)/i.test(href)) window.open(href, "_blank", "noopener,noreferrer");
          return;
        }
        // tap the left or right edge of the page to turn it (not while selecting text)
        if (preferences.layout !== "paginated" || d.getSelection()?.toString()) return;
        const x = (event as MouseEvent).clientX;
        const width = iframe.clientWidth;
        if (x < width * 0.25) callbacks.current.onTurn("previous");
        else if (x > width * 0.75) callbacks.current.onTurn("next");
      });
      d.addEventListener("keydown", (event) => callbacks.current.onKey(event));
      // report selections once the reader stops dragging (and when the selection is cleared)
      let selectionTimer: number | undefined;
      d.addEventListener("selectionchange", () => {
        window.clearTimeout(selectionTimer);
        selectionTimer = window.setTimeout(() => callbacks.current.onSelection(readSelection()), 250);
      });
      // swipe on touch screens
      let startX: number | null = null;
      d.addEventListener("touchstart", (event) => (startX = event.touches[0]?.clientX ?? null), { passive: true });
      d.addEventListener(
        "touchend",
        (event) => {
          const endX = event.changedTouches[0]?.clientX;
          if (startX === null || endX === undefined || d.getSelection()?.toString()) return;
          if (Math.abs(endX - startX) > 50) callbacks.current.onTurn(endX < startX ? "next" : "previous");
          startX = null;
        },
        { passive: true }
      );
      d.addEventListener("scroll", () => callbacks.current.onPositionChange(), { passive: true });
      // images change the layout as they arrive; let the reader re-anchor once they are in
      const images = Array.from(d.images).filter((img) => !img.complete);
      let pending = images.length;
      const done = () => callbacks.current.onReady();
      if (!pending) done();
      else {
        const timer = window.setTimeout(done, 2500);
        images.forEach((img) => {
          const finish = () => {
            pending -= 1;
            if (pending === 0) {
              window.clearTimeout(timer);
              done();
            }
          };
          img.addEventListener("load", finish, { once: true });
          img.addEventListener("error", finish, { once: true });
        });
      }
    };
    iframe.addEventListener("load", handleLoad, { once: true });
    iframe.srcdoc = buildDocument(chapter);
    return () => iframe.removeEventListener("load", handleLoad);
    // a new document only for a new chapter (or new signed links); settings are applied in place
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter]);

  // settings change: restyle in place, keeping the reader's place
  useEffect(() => {
    const before = position();
    applyStyles();
    if (before) goToOffset(before.offset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applyStyles]);

  // window or panel resize: re-paginate around the same text
  useEffect(() => {
    const iframe = frame.current;
    if (!iframe || typeof ResizeObserver === "undefined") return;
    let last = iframe.clientWidth;
    const observer = new ResizeObserver(() => {
      if (Math.abs(iframe.clientWidth - last) < 2) return;
      last = iframe.clientWidth;
      const before = position();
      applyStyles();
      if (before) goToOffset(before.offset);
    });
    observer.observe(iframe);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applyStyles]);

  return (
    <iframe
      ref={frame}
      title="Book content"
      aria-label={chapter.title ? `Book content: ${chapter.title}` : "Book content"}
      // no scripts, no forms, no popups, no navigation of the app: same-origin only so the reader can lay it out
      sandbox="allow-same-origin"
      referrerPolicy="no-referrer"
      className="h-full w-full border-0"
    />
  );
});
