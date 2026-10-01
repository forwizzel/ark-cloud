"""Linux-only, descriptor-relative local files. Host configuration is the authority.

openat2 forbids symlinks and mount crossings during resolution, not just before it.
Host owners are trusted: app account isolation is not isolation from host administrators.
"""

import ctypes
import errno
import hashlib
import os
import platform
import re
import stat
import threading
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.logging import get_logger

MAX_ENTRIES = 10_000
INTERNAL = ".ark-"
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
LIBC = ctypes.CDLL(None, use_errno=True)
MUTATIONS = threading.RLock()


class StorageError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def filesystem_error(error: OSError) -> StorageError:
    messages = {
        errno.ENOENT: (404, "Item or storage location is no longer available. Refresh and retry."),
        errno.EEXIST: (409, "The destination already exists. Choose another name."),
        errno.ENOTEMPTY: (409, "Folder is not empty. Remove its contents individually first."),
        errno.EACCES: (
            403,
            "Storage access denied. Ask the host owner to check permissions and SELinux.",
        ),
        errno.EPERM: (403, "Storage operation denied. Check host permissions and SELinux."),
        errno.EROFS: (403, "This storage filesystem is read-only."),
        errno.ENOSPC: (507, "Storage is full. Free space on the host and retry."),
        errno.EDQUOT: (507, "The host filesystem quota is exhausted."),
        errno.ELOOP: (409, "Symbolic links are not supported."),
        errno.EXDEV: (409, "Crossing filesystem mounts is not supported."),
        errno.ENOTDIR: (409, "The folder changed or is not a supported directory."),
        errno.ENOSYS: (503, "Local storage requires Linux openat2 and renameat2 support."),
        errno.EAGAIN: (409, "The filesystem changed during this operation. Refresh and retry."),
    }
    code, message = messages.get(
        error.errno, (503, "Storage operation failed. Check the host storage.")
    )
    return StorageError(message, code)


class RootConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    path: str
    device: int = Field(ge=0)
    inode: int = Field(gt=0)
    kind: Literal["managed", "assigned"] = "assigned"
    owner: str | None = None
    read_only: bool = False

    @model_validator(mode="after")
    def valid_root(self):
        if self.path != f"/srv/ark-storage/{self.id}":
            raise ValueError("Storage targets must match /srv/ark-storage/<root-id>.")
        if self.kind == "assigned" and not self.owner:
            raise ValueError("Assigned roots require an immutable account ID.")
        if self.kind == "managed" and (self.owner or self.read_only):
            raise ValueError("Managed storage is writable and has no shared owner.")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    roots: list[RootConfig] = Field(max_length=32)

    @model_validator(mode="after")
    def unique_roots(self):
        if len({r.id for r in self.roots}) != len(self.roots):
            raise ValueError("Duplicate root IDs.")
        if len({(r.device, r.inode) for r in self.roots}) != len(self.roots):
            raise ValueError("Duplicate filesystem roots.")
        if sum(r.kind == "managed" for r in self.roots) > 1:
            raise ValueError("Only one managed root is supported.")
        return self


def load_manifest(path: str) -> Manifest:
    try:
        with open(path, "rb") as source:
            content = source.read(65_537)
        if len(content) > 65_536:
            raise ValueError("Manifest too large")
        return Manifest.model_validate_json(content)
    except FileNotFoundError:
        return Manifest(roots=[])
    except (OSError, ValueError) as error:
        raise StorageError(
            "Storage configuration is invalid. "
            "Ask an administrator to review Local Storage diagnostics.",
            503,
        ) from error


def parts(path: str, *, allow_empty: bool = False) -> list[str]:
    if not path and allow_empty:
        return []
    result = path.split("/")
    if len(result) > 32 or len(path.encode("utf-8", errors="replace")) > 2048:
        raise StorageError("Path is too long.", 422)
    for name in result:
        if (
            name in {"", ".", ".."}
            or name.startswith(INTERNAL)
            or "\\" in name
            or len(name.encode("utf-8", errors="replace")) > 255
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in name)
        ):
            raise StorageError("Unsupported filename or path.", 422)
    return result


def open_beneath(fd: int, path: str, flags: int = DIRECTORY, mode: int = 0) -> int:
    if platform.machine() not in {"x86_64", "aarch64"}:
        raise StorageError("Local storage currently supports Linux x86_64 and aarch64.", 503)
    # RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV
    how = (ctypes.c_uint64 * 3)(flags | os.O_CLOEXEC, mode, 0x08 | 0x04 | 0x01)
    result = LIBC.syscall(ctypes.c_long(437), fd, os.fsencode(path), how, ctypes.sizeof(how))
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return result


def rename_exclusive(source_fd: int, source: str, dest_fd: int, dest: str):
    if LIBC.renameat2(source_fd, os.fsencode(source), dest_fd, os.fsencode(dest), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def revision(info: os.stat_result) -> str:
    return hashlib.sha256(
        f"{info.st_dev}:{info.st_ino}:{info.st_ctime_ns}:{info.st_mtime_ns}:{info.st_size}".encode()
    ).hexdigest()[:32]


def supported(info: os.stat_result):
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise StorageError("Links and special files are not supported.")
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise StorageError("Files with multiple hard links are not supported.")


def mount_points() -> set[str]:
    def unescape(value: str) -> str:
        return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)

    with open("/proc/self/mountinfo") as source:
        return {unescape(line.split()[4]) for line in source}


class LocalStorage:
    def __init__(self, manifest: Manifest, *, verification: bool = False):
        self.manifest = manifest
        self.verification = verification

    def config(self, root_id: str, owner: str) -> RootConfig:
        from app.services.storage_control import blocked_roots

        if not self.verification and root_id in blocked_roots():
            raise StorageError("This location is disconnected or being reconfigured.", 404)
        for root in self.manifest.roots:
            if root.id == root_id and (root.kind == "managed" or root.owner == owner):
                return root
        raise StorageError("Storage location not found.", 404)

    @contextmanager
    def root(
        self,
        root_id: str,
        owner: str,
        *,
        write: bool = False,
        provision: bool = False,
        base: bool = False,
    ):
        if platform.machine() not in {"x86_64", "aarch64"}:
            raise StorageError("Local storage requires Linux x86_64 or aarch64.", 503)
        config = self.config(root_id, owner)
        if write and config.read_only:
            raise StorageError("This location is read-only.", 403)
        if config.path not in mount_points():
            raise StorageError(
                "Storage mount is missing. Ask an administrator to reconnect this location.", 503
            )
        # Resolve the mount itself without following any component symlinks.
        anchor = os.open("/", DIRECTORY)
        try:
            how = (ctypes.c_uint64 * 3)(DIRECTORY, 0, 0x08 | 0x04)
            fd = LIBC.syscall(
                ctypes.c_long(437), anchor, os.fsencode(config.path[1:]), how, ctypes.sizeof(how)
            )
            if fd < 0:
                code = ctypes.get_errno()
                raise OSError(code, os.strerror(code))
        finally:
            os.close(anchor)
        try:
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != (config.device, config.inode):
                raise StorageError("Storage identity changed. Host owner review is required.", 503)
            if config.kind == "managed" and not base:
                if not re.fullmatch(r"[a-zA-Z0-9-]{1,128}", owner):
                    raise StorageError("Invalid account identity.", 403)
                if provision:
                    with suppress(FileExistsError):
                        os.mkdir(owner, mode=0o770, dir_fd=fd)
                private = open_beneath(fd, owner)
                os.close(fd)
                fd = private
            # Probe kernel support even for an empty directory.
            probe = open_beneath(fd, ".")
            os.close(probe)
            yield fd
        finally:
            os.close(fd)

    def locations(self, owner: str) -> dict:
        items = []
        for config in self.manifest.roots:
            if config.kind != "managed" and config.owner != owner:
                continue
            item = {
                "id": config.id,
                "label": config.label,
                "read_only": config.read_only,
                "kind": config.kind,
                "needs_setup": False,
                "state": "healthy",
                "message": "Ready",
                "available_bytes": None,
                "total_bytes": None,
            }
            try:
                with self.root(config.id, owner) as fd:
                    usage = os.fstatvfs(fd)
                    if not config.read_only and usage.f_flag & os.ST_RDONLY:
                        raise StorageError("This storage filesystem is read-only.", 403)
                    if not os.access(".", os.R_OK | os.X_OK, dir_fd=fd):
                        raise StorageError(
                            "Storage access denied. Check host permissions and SELinux.", 403
                        )
                    if not config.read_only and not os.access(".", os.W_OK | os.X_OK, dir_fd=fd):
                        raise StorageError(
                            "Storage is not writable. Check host permissions and SELinux.", 403
                        )
                    item.update(
                        available_bytes=usage.f_bavail * usage.f_frsize,
                        total_bytes=usage.f_blocks * usage.f_frsize,
                    )
            except FileNotFoundError:
                item.update(
                    state="unavailable",
                    needs_setup=config.kind == "managed",
                    message=(
                        "Your private folder has not been created. "
                        "Choose Create my private folder to set it up."
                        if config.kind == "managed"
                        else "This directory is missing. "
                        "Ask your administrator to check the storage location."
                    ),
                )
            except (StorageError, OSError) as error:
                item.update(
                    state="unavailable",
                    message=str(
                        error if isinstance(error, StorageError) else filesystem_error(error)
                    ),
                )
            items.append(item)
        return {
            "roots": items,
            "message": "" if items else "No storage has been assigned to your account yet.",
        }

    @contextmanager
    def parent(self, root_fd: int, path: str):
        segments = parts(path)
        fd = open_beneath(root_fd, "/".join(segments[:-1]) or ".")
        try:
            yield fd, segments[-1]
        finally:
            os.close(fd)

    def listing(self, root_id: str, owner: str, path: str, offset: int, expected: str | None):
        parts(path, allow_empty=True)
        with self.root(root_id, owner) as root, self.directory(root, path) as fd:
            before = revision(os.fstat(fd))
            if expected and expected != before:
                raise StorageError("Folder changed. Refresh before loading more items.")
            entries = []
            skipped = 0
            with os.scandir(fd) as scan:
                for index, entry in enumerate(scan):
                    if index >= MAX_ENTRIES:
                        raise StorageError("Folder exceeds the 10,000-entry browsing limit.", 413)
                    try:
                        parts(entry.name)
                        child = open_beneath(fd, entry.name, os.O_PATH)
                        try:
                            info = os.fstat(child)
                            supported(info)
                        finally:
                            os.close(child)
                    except StorageError, OSError:
                        skipped += 1
                        continue
                    entries.append(
                        {
                            "name": entry.name,
                            "path": f"{path}/{entry.name}".lstrip("/"),
                            "kind": "folder" if stat.S_ISDIR(info.st_mode) else "file",
                            "size_bytes": info.st_size if stat.S_ISREG(info.st_mode) else None,
                            "modified_at": datetime.fromtimestamp(info.st_mtime, UTC).isoformat(),
                            "revision": revision(info),
                        }
                    )
            if revision(os.fstat(fd)) != before:
                raise StorageError("Folder changed while reading. Refresh and retry.")
            entries.sort(key=lambda item: (item["kind"] != "folder", item["name"]))
            return {
                "items": entries[offset : offset + 100],
                "revision": before,
                "next_offset": offset + 100 if offset + 100 < len(entries) else None,
                "skipped_count": skipped,
            }

    @contextmanager
    def directory(self, root: int, path: str):
        fd = open_beneath(root, path or ".")
        try:
            yield fd
        finally:
            os.close(fd)

    def checked_item(self, parent: int, name: str, expected: str) -> os.stat_result:
        fd = open_beneath(parent, name, os.O_PATH)
        try:
            info = os.fstat(fd)
            supported(info)
            if revision(info) != expected:
                raise StorageError("Item changed. Refresh before trying again.")
            return info
        finally:
            os.close(fd)

    def mkdir(self, root_id: str, owner: str, path: str):
        with (
            MUTATIONS,
            self.root(root_id, owner, write=True) as root,
            self.parent(root, path) as (fd, name),
        ):
            os.mkdir(name, mode=0o770, dir_fd=fd)
            os.fsync(fd)
        self.audit("mkdir", root_id, owner)

    def move(self, root_id: str, owner: str, path: str, destination: str, expected: str):
        with (
            MUTATIONS,
            self.root(root_id, owner, write=True) as root,
            self.parent(root, path) as (src, name),
            self.parent(root, destination) as (dst, target),
        ):
            self.checked_item(src, name, expected)
            rename_exclusive(src, name, dst, target)
            os.fsync(src)
            os.fsync(dst)
        self.audit("move", root_id, owner)

    def delete(self, root_id: str, owner: str, path: str, expected: str):
        with (
            MUTATIONS,
            self.root(root_id, owner, write=True) as root,
            self.parent(root, path) as (fd, name),
        ):
            info = self.checked_item(fd, name, expected)
            if stat.S_ISDIR(info.st_mode):
                os.rmdir(name, dir_fd=fd)
            else:
                os.unlink(name, dir_fd=fd)
            os.fsync(fd)
        self.audit("delete", root_id, owner)

    def download(self, root_id: str, owner: str, path: str, expected: str):
        parts(path)
        with self.root(root_id, owner) as root:
            fd = open_beneath(root, path, os.O_PATH)
            try:
                info = os.fstat(fd)
                supported(info)
                if not stat.S_ISREG(info.st_mode):
                    raise StorageError("Only regular files can be downloaded.")
                if revision(info) != expected:
                    raise StorageError("File changed. Refresh before downloading.")
                # Reopen the validated regular inode, not its mutable pathname.
                source = os.open(f"/proc/self/fd/{fd}", os.O_RDONLY | os.O_CLOEXEC)
                return source, info.st_size
            finally:
                os.close(fd)

    @staticmethod
    def audit(action: str, root: str, owner: str):
        get_logger(__name__).info(
            "local_storage_mutation",
            extra={"action": action, "root_id": root, "principal_id": owner},
        )
