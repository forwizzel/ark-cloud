"""Descriptor-relative, bounded-memory copying for owner-approved base relocation."""

import ctypes
import errno
import hashlib
import os
import platform
import stat
import sys
from contextlib import contextmanager

LIBC = ctypes.CDLL(None, use_errno=True)
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC


def beneath(parent, name, flags=DIRECTORY, *, root=False):
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise ValueError("Storage relocation requires Linux x86_64 or aarch64.")
    how = (ctypes.c_uint64 * 3)(flags | os.O_CLOEXEC, 0, 0x08 | 0x04 | (0 if root else 0x01))
    fd = LIBC.syscall(ctypes.c_long(437), parent, os.fsencode(name), how, ctypes.sizeof(how))
    if fd < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return fd


@contextmanager
def opened(path):
    anchor = os.open("/", DIRECTORY)
    try:
        fd = beneath(anchor, str(path).lstrip("/") or ".", DIRECTORY, root=True)
    finally:
        os.close(anchor)
    try:
        yield fd
    finally:
        os.close(fd)


def supported(info):
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or (
        stat.S_ISREG(info.st_mode) and info.st_nlink != 1
    ):
        raise ValueError("Relocation does not follow links or copy special/multiply-linked files.")


def metadata(source, target, info):
    os.fchmod(target, stat.S_IMODE(info.st_mode))
    for name in os.listxattr(source):
        if name != "security.selinux":
            os.setxattr(target, name, os.getxattr(source, name))
    os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
    os.fsync(target)


def copy_entry(source, target, name):
    # O_NONBLOCK prevents a replaced FIFO from blocking before fstat rejects it.
    fd = beneath(source, name, os.O_RDONLY | os.O_NONBLOCK)
    dest = None
    try:
        info = os.fstat(fd)
        supported(info)
        if stat.S_ISDIR(info.st_mode):
            os.mkdir(name, mode=0o700, dir_fd=target)
            dest = beneath(target, name)
            for child in os.listdir(fd):
                copy_entry(fd, dest, child)
        else:
            dest = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=target
            )
            while chunk := os.read(fd, 262144):
                view = memoryview(chunk)
                while view:
                    count = os.write(dest, view)
                    if not count:
                        raise OSError("Incomplete relocation write")
                    view = view[count:]
        metadata(fd, dest, info)
    finally:
        os.close(fd)
        if dest is not None:
            os.close(dest)


def digest(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    value = hashlib.sha256()
    while chunk := os.read(fd, 262144):
        value.update(chunk)
    return value.digest()


def verify_entry(source, target, name):
    left = beneath(source, name, os.O_RDONLY | os.O_NONBLOCK)
    right = None
    try:
        right = beneath(target, name, os.O_RDONLY | os.O_NONBLOCK)
        old, new = os.fstat(left), os.fstat(right)
        supported(old)
        supported(new)
        if stat.S_IFMT(old.st_mode) != stat.S_IFMT(new.st_mode) or stat.S_IMODE(
            old.st_mode
        ) != stat.S_IMODE(new.st_mode):
            raise ValueError("Relocation did not preserve file types/permissions.")
        for attribute in os.listxattr(left):
            if attribute != "security.selinux" and os.getxattr(left, attribute) != os.getxattr(
                right, attribute
            ):
                raise ValueError("Relocation did not preserve ACLs/extended attributes.")
        if stat.S_ISDIR(old.st_mode):
            names = set(os.listdir(left))
            if names != set(os.listdir(right)):
                raise ValueError("Relocation folder verification failed.")
            for child in names:
                verify_entry(left, right, child)
        elif old.st_size != new.st_size or digest(left) != digest(right):
            raise ValueError("Relocation file hash verification failed.")
        os.fsync(right)
    finally:
        os.close(left)
        if right is not None:
            os.close(right)


def publish(source, name, target):
    if LIBC.renameat2(source, os.fsencode(name), target, os.fsencode(name), 1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise ValueError("The relocation destination already exists; it will not be replaced.")
        raise OSError(code, os.strerror(code))
    os.fsync(target)


def remove_directory(parent, name):
    """Remove only the manager's incomplete stage; never traverse links/mounts."""
    fd = beneath(parent, name)
    try:
        for child in os.listdir(fd):
            entry = beneath(fd, child, os.O_PATH)
            try:
                info = os.fstat(entry)
                supported(info)
            finally:
                os.close(entry)
            if stat.S_ISDIR(info.st_mode):
                remove_directory(fd, child)
            else:
                os.unlink(child, dir_fd=fd)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent)
    os.fsync(parent)
