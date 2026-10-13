/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import type { TBook } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import { bookAuthors, bookTitle, placeholderColors } from "./utils";

type Props = {
  book: TBook;
  /** "thumbnail" for grids, "full" for the detail page */
  variant?: "thumbnail" | "full";
  className?: string;
};

/** The book's cover, or a generated cover (title and author on a colour from the title). */
export function BookCover({ book, variant = "thumbnail", className }: Props) {
  const url = variant === "full" ? book.cover_url || book.cover_thumbnail_url : book.cover_thumbnail_url;
  const [failed, setFailed] = useState(false);
  const title = bookTitle(book);

  if (url && !failed) {
    return (
      <img
        src={url}
        alt={`Cover of ${title}`}
        loading="lazy"
        onError={() => setFailed(true)}
        className={cn("shadow-sm aspect-[2/3] w-full rounded-md object-cover", className)}
      />
    );
  }
  const colors = placeholderColors(title);
  return (
    <div
      role="img"
      aria-label={`Cover of ${title}`}
      style={{ background: colors.background }}
      className={cn(
        "shadow-sm flex aspect-[2/3] w-full flex-col justify-between overflow-hidden rounded-md p-3 text-left text-white",
        className
      )}
    >
      <span className="h-1 w-8 rounded-full" style={{ background: colors.accent }} />
      <span className="line-clamp-4 text-14 leading-snug font-semibold break-words">{title}</span>
      <span className="line-clamp-2 text-11 opacity-80">{bookAuthors(book)}</span>
    </div>
  );
}
