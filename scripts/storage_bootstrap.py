#!/usr/bin/env python3
"""Deployment-owned host management startup. Never invoked by the browser."""

import json
import os
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import storage
import storage_fs
import storage_manager as manager


def ensure():
    if sys.platform != "linux" or not shutil.which("setfacl") or not shutil.which("getfacl"):
        raise ValueError("Host storage management requires Linux and the acl package.")
    if not shutil.which("systemctl"):
        raise ValueError(
            "Host storage management needs a systemd user service or an owner-supervised manager."
        )
    subprocess.run(["systemctl", "--user", "show-environment"], check=True, capture_output=True)
    with storage.configuration_lock():
        marker = storage.CONFIG / "managed-area.json"
        requested = os.environ.get("ARK_STORAGE_MANAGED_AREA", str(Path.home() / "Ark-Locations"))
        if marker.exists():
            area = Path(requested).expanduser().absolute()
            recorded = json.loads(marker.read_text())
            try:
                storage.source_path(str(area))
                with storage_fs.opened(area) as fd:
                    info = os.fstat(fd)
                if recorded != {"path": str(area), "device": info.st_dev, "inode": info.st_ino}:
                    info = None
            except (OSError, ValueError):
                info = None
            if info is None:
                print(
                    "Managed storage area is unavailable; existing registrations are preserved. Core services remain available."
                )
        else:
            area = storage.source_path(requested)
            if area.exists():
                raise ValueError(
                    "The proposed managed storage area already exists without Ark ownership metadata. Choose a new ARK_STORAGE_MANAGED_AREA for deployment."
                )
            area.mkdir(mode=0o700)
            info = area.stat()
            storage.atomic_write(
                marker, json.dumps({"path": str(area), "device": info.st_dev, "inode": info.st_ino})
            )
        config = json.loads(manager.CONFIG.read_text()) if manager.CONFIG.exists() else None
        paths = {str(area)} if info is not None else set()
        if config:
            for value in config["approved_paths"]:
                path = Path(value)
                if path.exists():
                    try:
                        manager.approved(config, value)
                    except (ValueError, OSError):
                        continue
                    paths.add(value)
        authenticated = False
        if config:
            try:
                manager.api(config, "report", manager.snapshot(config))
                authenticated = True
            except urllib.error.HTTPError as error:
                if error.code != 401:
                    raise
        if not authenticated:
            if not paths:
                print(
                    "Storage manager cannot enroll without an available approved area. Core services remain available; restore the original storage area."
                )
                return
            manager.enroll(SimpleNamespace(approve=sorted(paths), install=False))
            config = json.loads(manager.CONFIG.read_text())
        config["approved_paths"] = sorted(paths | set(config["approved_paths"]))
        if info is not None:
            config["identities"][str(area)] = [info.st_dev, info.st_ino]
        config["managed_area"] = str(area)
        storage.atomic_write(manager.CONFIG, json.dumps(config))
        manager.install_service(start=False)
        manager.api(config, "report", manager.snapshot(config))
    subprocess.run(["systemctl", "--user", "restart", "ark-storage-manager.service"], check=True)
    print(
        "Host storage management ready. Configure locations directly in Administration → Storage."
    )


if __name__ == "__main__":
    try:
        ensure()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f"ark storage management: {error}")
