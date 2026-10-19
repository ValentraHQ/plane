/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// components
import { PageHead } from "@/components/core/page-title";
import { LibraryNotes } from "@/components/library/library-notes";
import type { Route } from "./+types/page";

function LibraryNotesPage({ params }: Route.ComponentProps) {
  return (
    <>
      <PageHead title="Notes & highlights" />
      <div className="h-full w-full overflow-y-auto">
        <LibraryNotes workspaceSlug={params.workspaceSlug} />
      </div>
    </>
  );
}

export default observer(LibraryNotesPage);
