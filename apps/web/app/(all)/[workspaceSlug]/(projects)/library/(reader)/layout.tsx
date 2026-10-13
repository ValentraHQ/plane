/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Outlet } from "react-router";
// components
import { ContentWrapper } from "@/components/core/content-wrapper";

/** The reader brings its own toolbar: no app header, the whole area is the page. */
export default function LibraryReaderLayout() {
  return (
    <ContentWrapper>
      <Outlet />
    </ContentWrapper>
  );
}
