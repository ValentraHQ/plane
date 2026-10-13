/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// components
import { PageHead } from "@/components/core/page-title";
import { BookGrid, ContinueReading } from "@/components/library/book-grid";
import { LibraryNav } from "@/components/library/library-nav";
import { LibraryToolbar } from "@/components/library/library-toolbar";
import { BookDropZone, BookUploadModal, BookUploadPanel } from "@/components/library/upload";
// hooks
import { useInstance } from "@/hooks/store/use-instance";
import { useLibrary } from "@/hooks/store/use-library";
import { useUserPermissions } from "@/hooks/store/user";
import type { Route } from "./+types/page";

function LibraryPage({ params }: Route.ComponentProps) {
  const { workspaceSlug } = params;
  const { config } = useInstance();
  const {
    filters,
    fetchBooks,
    fetchTags,
    fetchCollections,
    fetchContinueReading,
    uploadDialog,
    openUploadDialog,
    closeUploadDialog,
  } = useLibrary();
  const { allowPermissions } = useUserPermissions();
  const enabled = !!config?.is_library_enabled;
  const canUpload =
    enabled && allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.WORKSPACE);
  const filtersKey = JSON.stringify(filters);

  useEffect(() => {
    if (enabled) void fetchBooks(workspaceSlug);
  }, [enabled, fetchBooks, filtersKey, workspaceSlug]);
  useSWR(enabled ? `LIBRARY_TAGS_${workspaceSlug}` : null, () => fetchTags(workspaceSlug));
  useSWR(enabled ? `LIBRARY_COLLECTIONS_${workspaceSlug}` : null, () => fetchCollections(workspaceSlug));
  useSWR(enabled ? `LIBRARY_CONTINUE_${workspaceSlug}` : null, () => fetchContinueReading(workspaceSlug), {
    revalidateOnMount: true,
  });
  const isHome =
    !filters.search &&
    filters.visibility === null &&
    !filters.format &&
    !filters.tag &&
    !filters.collection &&
    !filters.archived &&
    !filters.reading;

  if (config && !enabled) {
    return (
      <div className="grid h-full place-items-center p-6 text-center text-13 text-tertiary">
        The library is not enabled on this Plane instance.
      </div>
    );
  }

  return (
    <>
      <PageHead title="Library" />
      <BookDropZone disabled={!canUpload} onFiles={(files) => openUploadDialog(files)}>
        <div className="flex h-full w-full flex-col gap-4 overflow-y-auto p-4 sm:p-6 md:flex-row md:gap-6">
          <aside className="md:w-56 md:shrink-0">
            <LibraryNav workspaceSlug={workspaceSlug} />
          </aside>
          <main className="flex min-w-0 flex-1 flex-col gap-4">
            {isHome && <ContinueReading workspaceSlug={workspaceSlug} />}
            <LibraryToolbar />
            <BookGrid workspaceSlug={workspaceSlug} canUpload={canUpload} onUpload={() => openUploadDialog()} />
          </main>
        </div>
      </BookDropZone>
      <BookUploadModal
        workspaceSlug={workspaceSlug}
        isOpen={uploadDialog.isOpen}
        initialFiles={uploadDialog.files}
        onClose={closeUploadDialog}
      />
      <BookUploadPanel workspaceSlug={workspaceSlug} />
    </>
  );
}

export default observer(LibraryPage);
