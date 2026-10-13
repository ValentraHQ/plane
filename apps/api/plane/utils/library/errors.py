# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.


class BookError(Exception):
    """A book that cannot be processed: invalid, unsafe or unsupported. Shown to the user; never retried."""
