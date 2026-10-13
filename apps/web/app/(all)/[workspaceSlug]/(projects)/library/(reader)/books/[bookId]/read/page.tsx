/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// components
import { PageHead } from "@/components/core/page-title";
import { BookReader } from "@/components/library/reader/reader";
import { bookTitle } from "@/components/library/utils";
// hooks
import { useLibrary } from "@/hooks/store/use-library";
import type { Route } from "./+types/page";

function LibraryReaderPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, bookId } = params;
  const { getBookById } = useLibrary();
  const book = getBookById(bookId);

  return (
    <>
      <PageHead title={book ? `Reading: ${bookTitle(book)}` : "Reader"} />
      <BookReader workspaceSlug={workspaceSlug} bookId={bookId} />
    </>
  );
}

export default observer(LibraryReaderPage);
