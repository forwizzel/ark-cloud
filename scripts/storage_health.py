"""Read-only host-source checks shared by deployment and manager reporting."""

import json
import os
from pathlib import Path

import storage_fs


def inspect(root, config=None):
    import storage

    try:
        path = storage.source_path(root["source"])
        if config is not None:
            anchor = next(
                (
                    Path(p)
                    for p in config["approved_paths"]
                    if path == Path(p) or Path(p) in path.parents
                ),
                None,
            )
            if anchor is None:
                raise ValueError("Location is outside the host-approved storage areas.")
            with storage_fs.opened(anchor) as fd:
                info = os.fstat(fd)
                if [info.st_dev, info.st_ino] != config["identities"][str(anchor)]:
                    raise ValueError(
                        "Approved storage area changed identity. Host owner review is required."
                    )
                relative = str(path.relative_to(anchor))
                child = storage_fs.beneath(fd, relative)
                try:
                    info = os.fstat(child)
                finally:
                    os.close(child)
        else:
            with storage_fs.opened(path) as fd:
                info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (root["device"], root["inode"]):
            raise ValueError("Storage identity changed. Host owner review is required.")
        return {"state": "ready", "message": "Host directory verified."}
    except FileNotFoundError:
        return {
            "state": "missing",
            "message": "Host storage directory is missing. "
            "Restore the original directory or disconnect this location.",
        }
    except (OSError, ValueError):
        return {
            "state": "unavailable",
            "message": "Host storage directory is inaccessible, unsafe, or changed identity. "
            "Host owner review is required.",
        }


def configuration():
    import storage

    path = storage.CONFIG / "manager.json"
    return json.loads(path.read_text()) if path.exists() else None


def health(data, config=None):
    return {root["id"]: inspect(root, config) for root in data["roots"]}


def reconcile():
    import storage

    with storage.configuration_lock():
        if not storage.STATE.exists():
            return False
        previous = storage.OVERRIDE.read_bytes() if storage.OVERRIDE.exists() else None
        storage.save(storage.state(), announce=False)
        return previous != storage.OVERRIDE.read_bytes()


if __name__ == "__main__":
    import sys

    changed = reconcile()
    import storage

    unavailable = [
        root["id"]
        for root in storage.state()["roots"]
        if inspect(root, configuration())["state"] != "ready"
    ]
    if unavailable:
        print(
            "Starting with unavailable storage locations (registrations preserved): "
            + ", ".join(unavailable)
        )
    if "--require-change" in sys.argv and not changed:
        sys.exit(1)
