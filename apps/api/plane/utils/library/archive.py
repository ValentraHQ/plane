# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Safe reading of EPUB (ZIP) archives.

Everything is checked before and while unpacking, never trusting the archive's own headers:
entry count, names (path traversal, absolute paths, symlinks), encryption, declared sizes and
compression ratios, and the bytes actually read (a lying header cannot unpack more than allowed).
"""

# Python imports
import posixpath
import stat
import zipfile
import zlib
from dataclasses import dataclass
from urllib.parse import unquote

# Module imports
from .errors import BookError

CHUNK = 64 * 1024
# ratios are only meaningful for entries big enough to matter
RATIO_MIN_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ArchiveLimits:
    max_entries: int
    max_unpacked: int
    max_entry: int
    max_ratio: int


def normalize_path(path, base=""):
    """
    Resolve `path` (optionally relative to the directory `base`) to a clean archive path.
    Returns None for anything that would leave the archive or is not a plain relative path.
    """
    if path is None:
        return None
    path = unquote(path.split("#", 1)[0].split("?", 1)[0])
    if not path or "\x00" in path or "\\" in path or ":" in path.split("/", 1)[0]:
        return None
    if path.startswith("/"):
        return None
    joined = posixpath.normpath(posixpath.join(base, path)) if base else posixpath.normpath(path)
    if joined in (".", "") or joined.startswith("../") or joined == ".." or joined.startswith("/"):
        return None
    return joined


class SafeArchive:
    def __init__(self, file_obj, limits: ArchiveLimits):
        self.limits = limits
        self.unpacked = 0
        try:
            self.zip = zipfile.ZipFile(file_obj)
        except (zipfile.BadZipFile, OSError, ValueError) as error:
            raise BookError("The file is not a valid EPUB (it is not a ZIP archive).") from error
        self.entries = {}
        self._check_entries()

    def _check_entries(self):
        infos = self.zip.infolist()
        if len(infos) > self.limits.max_entries:
            raise BookError(f"The EPUB has too many files ({len(infos)}; the limit is {self.limits.max_entries}).")
        declared_total = 0
        for info in infos:
            name = info.filename
            if info.is_dir():
                continue
            clean = normalize_path(name)
            if clean is None or clean != name:
                raise BookError(f"The EPUB contains an unsafe file path: {name[:200]!r}.")
            if clean in self.entries:
                raise BookError(f"The EPUB contains the same file twice: {name[:200]!r}.")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise BookError(f"The EPUB contains a symbolic link: {name[:200]!r}.")
            if info.flag_bits & 0x1:
                raise BookError("The EPUB is password-protected or encrypted.")
            if info.file_size > self.limits.max_entry:
                raise BookError(f"A file inside the EPUB is too large: {name[:200]!r}.")
            if info.file_size > RATIO_MIN_SIZE and info.file_size > self.limits.max_ratio * max(info.compress_size, 1):
                raise BookError("The EPUB looks like a decompression bomb (a file is compressed too strongly).")
            declared_total += info.file_size
            if declared_total > self.limits.max_unpacked:
                raise BookError("The EPUB unpacks to more data than allowed.")
            self.entries[clean] = info

    def exists(self, path):
        return path in self.entries

    def read(self, path, max_bytes=None):
        """Read an entry, enforcing the per-entry and total limits on the bytes actually produced."""
        info = self.entries.get(path)
        if info is None:
            raise BookError(f"The EPUB is missing a file it refers to: {path[:200]!r}.")
        limit = min(info.file_size, self.limits.max_entry, max_bytes or self.limits.max_entry)
        chunks, size = [], 0
        try:
            with self.zip.open(info) as handle:
                while True:
                    chunk = handle.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    self.unpacked += len(chunk)
                    if size > limit:
                        raise BookError(f"A file inside the EPUB is larger than it claims: {path[:200]!r}.")
                    if self.unpacked > self.limits.max_unpacked:
                        raise BookError("The EPUB unpacks to more data than allowed.")
                    chunks.append(chunk)
        except BookError:
            raise
        except (zipfile.BadZipFile, zlib.error, OSError, EOFError, NotImplementedError, ValueError) as error:
            raise BookError(f"A file inside the EPUB is damaged: {path[:200]!r}.") from error
        return b"".join(chunks)

    def close(self):
        self.zip.close()
