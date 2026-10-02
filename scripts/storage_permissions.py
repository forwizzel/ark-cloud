"""Owner-authorized ACL preparation, descriptor-relative and bounded-memory."""

import json
import os
import stat
import subprocess

import storage_fs


def bits(value):
    return sum(bit for letter, bit in zip("rwx", (4, 2, 1)) if letter in value)


def letters(value):
    return "".join(letter if value & bit else "-" for letter, bit in zip("rwx", (4, 2, 1)))


def acl(fd):
    return subprocess.check_output(
        ["getfacl", "-cpn", f"/proc/self/fd/{fd}"], pass_fds=(fd,), text=True, timeout=10
    )


def entries(text):
    result = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            key, permissions = line.rsplit(":", 1)
            result[key] = bits(permissions)
    return result


def prepared(text, uid, permissions, directory):
    values = entries(text)
    for prefix in ("", "default:") if directory else ("",):
        if prefix and "default:user:" not in values:
            for name in ("user:", "group:", "other:"):
                values[prefix + name] = values[name]
        mask = values.get(prefix + "mask:", 7)
        # Expanding the ACL mask must not expand existing named users/groups.
        for key in list(values):
            if not key.startswith(prefix) or (not prefix and key.startswith("default:")):
                continue
            name = key[len(prefix) :]
            if name.startswith("group:") or (name.startswith("user:") and name != "user:"):
                values[key] &= mask
        key = prefix + f"user:{uid}"
        values[key] = values.get(key, 0) | bits(permissions)
        if prefix and uid != os.getuid():
            values.setdefault(prefix + f"user:{os.getuid()}", values[prefix + "user:"])
        values[prefix + "mask:"] = 0
        for key, value in list(values.items()):
            if not key.startswith(prefix) or (not prefix and key.startswith("default:")):
                continue
            name = key[len(prefix) :]
            if name.startswith("group:") or (name.startswith("user:") and name != "user:"):
                values[prefix + "mask:"] |= value
    return ",".join(f"{key}:{letters(value)}" for key, value in sorted(values.items()))


def walk(fd, relative="", depth=0):
    if depth > 32:
        raise ValueError("This directory tree exceeds the supported depth.")
    info = os.fstat(fd)
    storage_fs.supported(info)
    yield fd, relative, info
    if stat.S_ISDIR(info.st_mode):
        with os.scandir(fd) as scan:
            for entry in scan:
                child = storage_fs.beneath(fd, entry.name, os.O_PATH)
                try:
                    child_info = os.fstat(child)
                    storage_fs.supported(child_info)
                    if stat.S_ISDIR(child_info.st_mode):
                        directory = storage_fs.beneath(fd, entry.name)
                        try:
                            yield from walk(directory, f"{relative}/{entry.name}", depth + 1)
                        finally:
                            os.close(directory)
                    else:
                        yield child, f"{relative}/{entry.name}", child_info
                finally:
                    os.close(child)


def prepare(path, uid, read_only, journal):
    with storage_fs.opened(path) as root:
        # Validate the complete tree before changing any ACL; never follow links,
        # hard links, special files or nested mounts, including same-device binds.
        for fd, _, info in walk(root):
            if info.st_uid not in {os.getuid(), uid}:
                raise ValueError(
                    "This tree contains content owned by another host account. The host owner must authorize its filesystem access."
                )
        log = os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(log, "a") as output:
            for fd, relative, info in walk(root):
                if info.st_uid == uid:
                    continue
                original = acl(fd)
                permissions = "rx" if stat.S_ISDIR(info.st_mode) else "r"
                if not read_only:
                    permissions = "rwx" if stat.S_ISDIR(info.st_mode) else "rw"
                desired = prepared(original, uid, permissions, stat.S_ISDIR(info.st_mode))
                output.write(
                    json.dumps(
                        {
                            "path": relative,
                            "device": info.st_dev,
                            "inode": info.st_ino,
                            "acl": original,
                        }
                    )
                    + "\n"
                )
                output.flush()
                os.fsync(output.fileno())
                subprocess.run(
                    ["setfacl", "-n", "-m", desired, f"/proc/self/fd/{fd}"],
                    pass_fds=(fd,),
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
