/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import {
  ChevronLeftOutline,
  ChevronRightOutline,
  CloseOutline,
  ListLayoutOutline,
  SearchOutline,
  SettingsOutline,
} from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import type {
  TBookChapterContent,
  TBookChapterSummary,
  TBookPosition,
  TBookReadingStatePayload,
  TReaderPreferences,
} from "@plane/types";
import { EBookReadingStatus, EBookStatus } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { useLibrary } from "@/hooks/store/use-library";
import { LibraryService } from "@/services/library.service";
import { libraryErrorMessage } from "@/store/library.store";
// local imports
import { bookTitle } from "../utils";
import type { TReaderFrameHandle } from "./reader-frame";
import { ReaderFrame, THEMES } from "./reader-frame";
import { SearchPanel, SettingsPanel, TocPanel } from "./reader-panels";

const service = new LibraryService();

const DEFAULT_PREFERENCES: TReaderPreferences = {
  font_family: "publisher",
  font_size: 18,
  line_height: 1.6,
  margin: "normal",
  theme: "light",
  layout: "paginated",
};
const SAVE_DELAY = 1500;
// refetch a chapter a minute before its image links expire
const LINK_MARGIN_SECONDS = 60;

type TTarget =
  | { kind: "start" }
  | { kind: "end" }
  | { kind: "offset"; offset: number }
  | { kind: "fragment"; fragment: string }
  | { kind: "occurrence"; text: string; occurrence: number };

type TCached = { content: TBookChapterContent; fetchedAt: number };

const isDarkApp = () => (document.documentElement.getAttribute("data-theme") ?? "").includes("dark");

type Props = { workspaceSlug: string; bookId: string };

export const BookReader = observer(function BookReader({ workspaceSlug, bookId }: Props) {
  const { getBookById, fetchBook } = useLibrary();
  const { toggleSidebar } = useAppTheme();
  const book = getBookById(bookId);
  const frame = useRef<TReaderFrameHandle>(null);
  const container = useRef<HTMLDivElement>(null);
  const cache = useRef(new Map<number, TCached>());
  const target = useRef<TTarget>({ kind: "start" });
  const pendingSave = useRef<TBookReadingStatePayload | null>(null);
  const saveTimer = useRef<number | undefined>(undefined);
  const finished = useRef(false);

  const [chapters, setChapters] = useState<TBookChapterSummary[]>([]);
  const [preferences, setPreferences] = useState<TReaderPreferences>(DEFAULT_PREFERENCES);
  const [chapter, setChapter] = useState<TBookChapterContent | null>(null);
  const [panel, setPanel] = useState<"toc" | "settings" | "search" | null>(null);
  const [progress, setProgress] = useState(0);
  const [pageInfo, setPageInfo] = useState({ page: 1, pages: 1 });
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [systemDark, setSystemDark] = useState(false);

  const totals = useMemo(() => {
    const before: number[] = [];
    let sum = 0;
    for (const c of chapters) {
      before[c.index] = sum;
      sum += Math.max(1, c.character_count);
    }
    return { before, total: Math.max(1, sum) };
  }, [chapters]);

  // --- loading ---
  const fetchChapter = useCallback(
    async (index: number) => {
      const cached = cache.current.get(index);
      const fresh = cached && Date.now() - cached.fetchedAt < (cached.content.expires_in - LINK_MARGIN_SECONDS) * 1000;
      if (cached && fresh) return cached.content;
      const content = await service.getChapter(workspaceSlug, bookId, index);
      cache.current.set(index, { content, fetchedAt: Date.now() });
      return content;
    },
    [bookId, workspaceSlug]
  );

  const openChapter = useCallback(
    async (index: number, where: TTarget) => {
      // already showing it (and its links are still valid): just move
      if (chapter?.index === index && frame.current) {
        const cached = cache.current.get(index);
        if (cached && Date.now() - cached.fetchedAt < (cached.content.expires_in - LINK_MARGIN_SECONDS) * 1000) {
          applyTarget(where);
          return;
        }
      }
      target.current = where;
      try {
        setChapter(await fetchChapter(index));
      } catch (error) {
        setToast({
          type: "error",
          title: "Error!",
          message: libraryErrorMessage(error, "The chapter could not be loaded."),
        });
      }
    },
    // applyTarget is stable enough: it only reads refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [chapter?.index, fetchChapter]
  );

  // on a phone the book needs the whole width: close the app sidebar
  useEffect(() => {
    if (window.innerWidth < 768) toggleSidebar(true);
  }, [toggleSidebar]);

  useEffect(() => {
    setSystemDark(isDarkApp());
    let cancelled = false;
    const load = async () => {
      try {
        const [detail, list, prefs, state] = await Promise.all([
          fetchBook(workspaceSlug, bookId),
          service.listChapters(workspaceSlug, bookId),
          service.getReaderPreferences(workspaceSlug).catch(() => DEFAULT_PREFERENCES),
          service.getReadingState(workspaceSlug, bookId),
        ]);
        if (cancelled) return;
        if (detail.status !== EBookStatus.READY || detail.format !== "epub" || list.length === 0) {
          setLoadError(
            detail.format === "pdf"
              ? "Reading PDFs in the browser is not available yet; download the file instead."
              : "This book is not ready to read."
          );
          return;
        }
        setChapters(list);
        setPreferences({ ...DEFAULT_PREFERENCES, ...prefs });
        const saved = state.position as TBookPosition;
        const start = list.find((c) => c.linear)?.index ?? list[0].index;
        const valid = typeof saved?.chapter === "number" && list.some((c) => c.index === saved.chapter);
        finished.current = state.status === EBookReadingStatus.COMPLETED;
        target.current = valid ? { kind: "offset", offset: saved.offset ?? 0 } : { kind: "start" };
        setChapter(await fetchChapter(valid ? saved.chapter : start));
        void service.saveReadingState(workspaceSlug, bookId, { opened: true }).catch(() => undefined);
      } catch (error) {
        if (!cancelled) setLoadError(libraryErrorMessage(error, "This book could not be opened."));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [bookId, fetchBook, fetchChapter, workspaceSlug]);

  // --- position, progress and saving ---
  const flushSave = useCallback(
    (onExit = false) => {
      window.clearTimeout(saveTimer.current);
      const payload = pendingSave.current;
      if (!payload) return;
      pendingSave.current = null;
      if (onExit) service.saveReadingStateOnExit(workspaceSlug, bookId, payload);
      else void service.saveReadingState(workspaceSlug, bookId, payload).catch(() => undefined);
    },
    [bookId, workspaceSlug]
  );

  const updatePosition = useCallback(() => {
    if (!chapter || !frame.current) return;
    const where = frame.current.position();
    if (!where) return;
    const chars = Math.max(1, chapters.find((c) => c.index === chapter.index)?.character_count ?? 1);
    const value = Math.min(100, (((totals.before[chapter.index] ?? 0) + where.fraction * chars) / totals.total) * 100);
    const isEnd = chapter.next === null && where.fraction >= 1;
    setProgress(isEnd ? 100 : value);
    setPageInfo(frame.current.pageInfo());
    // a status change waiting to be saved must survive later moves
    const pendingStatus = pendingSave.current?.status;
    pendingSave.current = {
      position: { chapter: chapter.index, offset: where.offset, quote: where.quote },
      progress: isEnd ? 100 : Math.round(value * 100) / 100,
      ...(pendingStatus !== undefined ? { status: pendingStatus } : {}),
      ...(isEnd && !finished.current ? { status: EBookReadingStatus.COMPLETED } : {}),
    };
    if (isEnd && !finished.current) {
      finished.current = true;
      setToast({ type: "success", title: "Finished", message: "You reached the end of the book." });
    }
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => flushSave(), SAVE_DELAY);
  }, [chapter, chapters, flushSave, totals]);

  // save when the tab is hidden or closed, and when leaving the reader
  useEffect(() => {
    const onHide = () => document.visibilityState === "hidden" && flushSave(true);
    const onPageHide = () => flushSave(true);
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
      flushSave(true);
    };
  }, [flushSave]);

  // --- navigation ---
  function applyTarget(where: TTarget) {
    const handle = frame.current;
    if (!handle) return;
    if (where.kind === "end") handle.goToEnd();
    else if (where.kind === "offset") handle.goToOffset(where.offset);
    else if (where.kind === "fragment") {
      if (!handle.goToFragment(where.fragment)) handle.goToOffset(0);
    } else if (where.kind === "occurrence") {
      if (!handle.showOccurrence(where.text, where.occurrence)) handle.goToOffset(0);
    } else handle.goToOffset(0);
  }

  const handleReady = useCallback(() => {
    applyTarget(target.current);
    updatePosition();
    // fetch the next chapter ahead of time
    if (chapter?.next !== null && chapter?.next !== undefined) void fetchChapter(chapter.next).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter, fetchChapter, updatePosition]);

  const next = useCallback(() => {
    if (!chapter || !frame.current) return;
    if (frame.current.next()) return;
    if (chapter.next !== null) void openChapter(chapter.next, { kind: "start" });
    else updatePosition();
  }, [chapter, openChapter, updatePosition]);

  const previous = useCallback(() => {
    if (!chapter || !frame.current) return;
    if (frame.current.previous()) return;
    if (chapter.previous !== null) void openChapter(chapter.previous, { kind: "end" });
  }, [chapter, openChapter]);

  const handleKey = useCallback(
    (event: KeyboardEvent) => {
      const field = (event.target as HTMLElement | null)?.closest?.("input, textarea, select, [contenteditable]");
      if (field || event.metaKey || event.ctrlKey || event.altKey) return;
      if (["ArrowRight", "PageDown"].includes(event.key) || (event.key === " " && !event.shiftKey)) {
        event.preventDefault();
        next();
      } else if (["ArrowLeft", "PageUp"].includes(event.key) || (event.key === " " && event.shiftKey)) {
        event.preventDefault();
        previous();
      } else if (event.key === "Escape" && panel) {
        setPanel(null);
      }
    },
    [next, panel, previous]
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  // follow the app's light/dark switch for the "Auto" theme
  useEffect(() => {
    const themeWatcher = new MutationObserver(() => setSystemDark(isDarkApp()));
    themeWatcher.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => themeWatcher.disconnect();
  }, []);

  // --- settings ---
  const prefsTimer = useRef<number | undefined>(undefined);
  // changes made in quick succession are saved together
  const pendingPrefs = useRef<Partial<TReaderPreferences>>({});
  const changePreferences = (change: Partial<TReaderPreferences>) => {
    setPreferences((current) => ({ ...current, ...change }));
    pendingPrefs.current = { ...pendingPrefs.current, ...change };
    window.clearTimeout(prefsTimer.current);
    prefsTimer.current = window.setTimeout(() => {
      const changes = pendingPrefs.current;
      pendingPrefs.current = {};
      void service.saveReaderPreferences(workspaceSlug, changes).catch(() => undefined);
    }, 600);
  };

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void container.current?.requestFullscreen?.().catch(() => undefined);
  };

  if (loadError) {
    return (
      <div className="grid h-full place-items-center p-6 text-center">
        <div className="flex flex-col items-center gap-3">
          <p className="text-14 font-medium text-primary">{loadError}</p>
          <Link
            href={`/${workspaceSlug}/library/books/${bookId}`}
            className="text-13 text-accent-primary hover:underline"
          >
            Back to the book
          </Link>
        </div>
      </div>
    );
  }

  const pageTheme =
    preferences.theme === "system"
      ? THEMES[systemDark ? "dark" : "light"]
      : (THEMES[preferences.theme] ?? THEMES.light);

  const chapterTitle =
    chapter?.title ||
    chapters.find((c) => c.index === chapter?.index)?.title ||
    (chapter ? `Section ${chapter.index + 1}` : "");

  return (
    <div ref={container} className="flex h-full w-full flex-col bg-surface-1" data-testid="book-reader">
      {/* top bar */}
      <header className="flex items-center gap-1 border-b border-subtle px-2 py-1.5 sm:px-3">
        <Link
          href={`/${workspaceSlug}/library/books/${bookId}`}
          className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-13 text-secondary hover:bg-layer-transparent-hover"
          onClick={() => flushSave()}
        >
          <ChevronLeftOutline className="size-4" />
          <span className="hidden sm:inline">Book</span>
        </Link>
        <div className="min-w-0 flex-1 px-1 text-center">
          <p className="truncate text-13 font-medium text-primary">{book ? bookTitle(book) : ""}</p>
          <p className="truncate text-11 text-tertiary">{chapterTitle}</p>
        </div>
        <IconButton
          variant="ghost"
          size="sm"
          aria-label="Contents"
          aria-pressed={panel === "toc"}
          icon={<Icon icon={ListLayoutOutline} />}
          onClick={() => setPanel(panel === "toc" ? null : "toc")}
        />
        <IconButton
          variant="ghost"
          size="sm"
          aria-label="Search in book"
          aria-pressed={panel === "search"}
          icon={<Icon icon={SearchOutline} />}
          onClick={() => setPanel(panel === "search" ? null : "search")}
        />
        <IconButton
          variant="ghost"
          size="sm"
          aria-label="Reading settings"
          aria-pressed={panel === "settings"}
          icon={<Icon icon={SettingsOutline} />}
          onClick={() => setPanel(panel === "settings" ? null : "settings")}
        />
        <button
          type="button"
          onClick={toggleFullscreen}
          className="hidden rounded-md px-2 py-1 text-12 text-secondary hover:bg-layer-transparent-hover sm:block"
        >
          Full screen
        </button>
      </header>

      <div
        className="relative flex min-h-0 flex-1"
        // the margins around the page take the page's colour
        style={{ background: pageTheme.bg, color: pageTheme.fg }}
      >
        {/* the page, with turn buttons on wide screens */}
        <button
          type="button"
          aria-label="Previous page"
          onClick={previous}
          className="hidden w-12 shrink-0 items-center justify-center opacity-50 hover:opacity-100 md:flex"
        >
          <ChevronLeftOutline className="size-5" />
        </button>
        <div className="relative min-w-0 flex-1">
          {chapter && (
            <ReaderFrame
              ref={frame}
              chapter={chapter}
              preferences={preferences}
              systemDark={systemDark}
              onReady={handleReady}
              onPositionChange={updatePosition}
              onChapterLink={(index, fragment) =>
                void openChapter(index, fragment ? { kind: "fragment", fragment } : { kind: "start" })
              }
              onKey={handleKey}
              onTurn={(direction) => (direction === "next" ? next() : previous())}
            />
          )}
          {isLoading && (
            <div className="absolute inset-0 grid place-items-center text-13 text-tertiary" role="status">
              Opening the book…
            </div>
          )}
        </div>
        <button
          type="button"
          aria-label="Next page"
          onClick={next}
          className="hidden w-12 shrink-0 items-center justify-center opacity-50 hover:opacity-100 md:flex"
        >
          <ChevronRightOutline className="size-5" />
        </button>

        {/* side panel: contents, search, settings */}
        {panel && (
          <aside
            aria-label={panel === "toc" ? "Contents" : panel === "search" ? "Search in book" : "Reading settings"}
            className="shadow-lg absolute inset-y-0 right-0 z-10 flex w-full max-w-sm flex-col gap-3 overflow-hidden border-l border-subtle bg-surface-1 p-3"
          >
            <div className="flex items-center justify-between">
              <h2 className="text-14 font-semibold text-primary">
                {panel === "toc" ? "Contents" : panel === "search" ? "Search" : "Reading settings"}
              </h2>
              <IconButton
                variant="ghost"
                size="sm"
                aria-label="Close"
                icon={<Icon icon={CloseOutline} />}
                onClick={() => setPanel(null)}
              />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {panel === "toc" && (
                <TocPanel
                  entries={book?.toc ?? []}
                  chapters={chapters}
                  currentChapter={chapter?.index ?? -1}
                  onSelect={(index, fragment) => {
                    setPanel(null);
                    void openChapter(index, fragment ? { kind: "fragment", fragment } : { kind: "start" });
                  }}
                />
              )}
              {panel === "search" && (
                <SearchPanel
                  onSearch={(query) => service.searchBook(workspaceSlug, bookId, query)}
                  onSelect={(index, text, occurrence) => {
                    if (window.innerWidth < 768) setPanel(null);
                    void openChapter(index, { kind: "occurrence", text, occurrence });
                  }}
                />
              )}
              {panel === "settings" && <SettingsPanel preferences={preferences} onChange={changePreferences} />}
            </div>
          </aside>
        )}
      </div>

      {/* progress */}
      <footer className="flex items-center gap-3 border-t border-subtle px-3 py-1.5 text-11 text-tertiary">
        <div
          role="progressbar"
          aria-label="Reading progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress)}
          className="h-1 flex-1 overflow-hidden rounded-full bg-layer-3"
        >
          <div className="h-full bg-accent-primary transition-[width]" style={{ width: `${progress}%` }} />
        </div>
        <span className="shrink-0" aria-live="polite">
          {Math.round(progress)}%
          {preferences.layout === "paginated" ? ` · page ${pageInfo.page} of ${pageInfo.pages} in this chapter` : ""}
        </span>
      </footer>
      <p className={cn("sr-only")} aria-live="polite">
        {chapterTitle}
      </p>
    </div>
  );
});
