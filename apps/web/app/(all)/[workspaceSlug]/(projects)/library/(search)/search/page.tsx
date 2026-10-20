/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// components
import { PageHead } from "@/components/core/page-title";
import { LibrarySearch } from "@/components/library/library-search";
import type { Route } from "./+types/page";

function LibrarySearchPage({ params }: Route.ComponentProps) {
  return (
    <>
      <PageHead title="Search the library" />
      <div className="h-full w-full overflow-y-auto">
        <LibrarySearch workspaceSlug={params.workspaceSlug} />
      </div>
    </>
  );
}

export default observer(LibrarySearchPage);
