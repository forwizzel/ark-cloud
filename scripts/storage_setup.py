#!/usr/bin/env python3
"""One owner command for the Local Files wizard; API remains unprivileged."""

import argparse
import fcntl
import json
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.error
from uuid import uuid4
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import storage
import storage_manager as manager

RECORD = storage.CONFIG / "setup-journal.json"


def host_cli(option, body=None):
    result = json.loads(
        manager.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "app.services.storage_manager_cli",
            option,
            input=json.dumps(body) if body is not None else None,
        )
    )
    if result.get("error"):
        raise ValueError(result["error"])
    return result


def progress(record, message, state="applying"):
    record["message"] = message
    storage.atomic_write(RECORD, json.dumps(record))
    print(message, flush=True)
    host_cli("--progress", {"id": record["job_id"], "state": state, "message": message})


def reviewed_root(data, requested, kind="managed"):
    default = str(Path.home() / ("Ark-Files" if kind == "managed" else "Ark-Shared"))
    managed = next(
        (
            r
            for r in data["roots"]
            if r["kind"] == kind
            and (kind == "managed" or r["source"] == str(storage.source_path(requested or default)))
        ),
        None,
    )
    if managed:
        if requested and str(storage.source_path(requested)) != managed["source"]:
            raise ValueError(
                "Private folders already have a base. Use Change base directory in Ark Cloud."
            )
        path = storage.source_path(managed["source"])
        if not path.is_dir():
            raise ValueError(
                "The storage location is missing. Restore the disk or disconnect it in Ark Cloud."
            )
        info = path.stat()
        if (info.st_dev, info.st_ino) != (managed["device"], managed["inode"]):
            raise ValueError("Storage identity changed. Review the disk and use Reconnect in Ark Cloud.")
        return path, managed
    path = storage.source_path(requested or default)
    for root in data["roots"]:
        source = Path(root["source"])
        if path == source or path in source.parents or source in path.parents:
            raise ValueError("The new storage location overlaps an existing location.")
    if len(data["roots"]) >= 32 or (
        kind == "managed" and any(r["id"] == "personal" for r in data["roots"])
    ):
        raise ValueError("Disconnect an existing location before creating a private-folder base.")
    return path, None


def prepare_root(data, path, root, record):
    if root:
        return root
    saved = record.get("root")
    if saved:
        info = path.stat()
        if saved["source"] != str(path) or (info.st_dev, info.st_ino) != (
            saved["device"],
            saved["inode"],
        ):
            raise ValueError("The setup directory changed identity. Review it before resuming.")
        root = saved
    else:
        if path.exists():
            raise ValueError(
                "This directory already exists and is not registered as Ark storage. "
            "Use Connect existing folder in Ark Cloud, or run storage setup --path with a NEW directory."
            )
        storage.provision_new(path)
        info = path.stat()
        root = {
            "id": record["root_id"],
            "label": "My files" if record["kind"] == "managed" else "Shared files",
            "source": str(path),
            "path": "/srv/ark-storage/" + record["root_id"],
            "device": info.st_dev,
            "inode": info.st_ino,
            "kind": record["kind"],
            "owner": None,
            "read_only": False,
            "selinux": "private",
            "registration": str(uuid4()),
        }
        record["root"] = root
        storage.atomic_write(RECORD, json.dumps(record))
    data["roots"].append(root)
    return root


def approvals(path, data):
    """Preserve valid approvals; never silently accept a replaced approved disk."""
    paths = {str(path)}
    if manager.CONFIG.exists():
        old = json.loads(manager.CONFIG.read_text())
        for value in old["approved_paths"]:
            area = Path(value)
            if not area.exists():
                if any(
                    r["source"] == value or area in Path(r["source"]).parents for r in data["roots"]
                ):
                    raise ValueError(
                        "An approved disk used by a location is missing. Restore it first."
                    )
                continue
            manager.approved(old, value)
            paths.add(value)
    return sorted(paths)


def recover_manager_journal():
    if not manager.JOURNAL.exists():
        return
    pending = json.loads(manager.JOURNAL.read_text())
    state = json.loads(
        manager.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "app.services.storage_manager_cli",
            "--job-id",
            pending["job"]["id"],
        )
    )["state"]
    if pending["phase"] == "report" and state in {"failed", "completed"}:
        manager.JOURNAL.replace(storage.CONFIG / "previous-manager-journal.json")
        return
    raise ValueError(
        "An unfinished host operation needs recovery. Start the existing host helper and "
        "finish that operation before running setup; its journal has been preserved."
    )


def perform_setup(args):
    if sys.platform != "linux":
        raise ValueError("Local Files setup requires Linux.")
    storage.local_daemon()
    if not shutil.which("setfacl"):
        raise ValueError("Install the acl package (setfacl), then rerun this command.")
    if not args.no_install:
        if not shutil.which("systemctl"):
            raise ValueError(
                "No systemd user service is available. Use --no-install and supervise storage manager run."
            )
        subprocess.run(["systemctl", "--user", "show-environment"], check=True, capture_output=True)
        subprocess.run(
            ["systemctl", "--user", "stop", "ark-storage-manager.service"],
            check=False,
            capture_output=True,
        )
    with storage.configuration_lock():
        with (storage.CONFIG / "manager-process.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError(
                    "Another host storage process is running. Let it finish, or pause the "
                    "foreground storage manager before running setup."
                ) from error
            data = storage.state()
            kind = "shared" if getattr(args, "shared", False) else "managed"
            path, root = reviewed_root(data, args.path, kind)
            record = json.loads(RECORD.read_text()) if RECORD.exists() else {}
            if record and record.get("path") != str(path) and record.get("phase") != "completed":
                raise ValueError(
                    "Resume the unfinished setup with its original path before choosing another."
                )
            if record.get("phase") == "completed" and record.get("path") != str(path):
                record = {}
            if not root and path.exists() and not record.get("root"):
                raise ValueError(
                    "The folder already exists. Use Connect existing folder in Ark Cloud, or "
                    "./scripts/ark storage setup --path /a/new/directory. Nothing was overwritten."
                )
            # Probe before creating any directory or changing saved configuration.
            storage.probe()
            allowed = approvals(path, data)
            if record.get("phase") in {"applying", "verifying", "interrupted"} and root:
                # Recover a setup-caused outage without depending on a running API.
                storage.save(data, announce=False)
                manager.compose("up", "--detach", "--no-deps", "--force-recreate", "--wait", "api")
            recover_manager_journal()
            root_id = (
                root["id"]
                if root
                else (
                    "personal"
                    if kind == "managed"
                    else "shared-" + hashlib.sha256(str(path).encode()).hexdigest()[:12]
                )
            )
            job = host_cli("--begin", {"path": str(path), "root_id": root_id, "kind": kind})
            record.update(
                path=str(path), job_id=job["id"], phase="preparing", kind=kind, root_id=root_id
            )
            config = None
            try:
                progress(
                    record,
                    "Creating private storage and account access."
                    if kind == "managed"
                    else "Creating a shared directory. Account access is granted in Administration.",
                )
                root = prepare_root(data, path, root, record)
                record["phase"] = "applying"
                progress(record, "Applying storage mounts. Ark Cloud will reconnect automatically.")
                storage.save(data, announce=False)
                manager.compose("config", "--quiet")
                manager.compose("up", "--detach", "--no-deps", "--force-recreate", "--wait", "api")
                manager.enroll(SimpleNamespace(approve=allowed, install=False, setup=True))
                config = json.loads(manager.CONFIG.read_text())
                record["phase"] = "verifying"
                storage.atomic_write(RECORD, json.dumps(record))
                manager.api(
                    config,
                    "report",
                    {
                        **manager.snapshot(config),
                        "job_id": job["id"],
                        "state": "verifying",
                        "message": "Verifying access as the API user and creating private account folders."
                        if kind == "managed"
                        else "Verifying the shared directory as the API user.",
                    },
                )
                if not args.no_install:
                    manager.install_service(start=False)
                manager.api(
                    config,
                    "report",
                    {
                        **manager.snapshot(config),
                        "job_id": job["id"],
                        "state": "completed",
                        "message": "Local Files is ready. Open my files in Ark Cloud."
                        if kind == "managed"
                        else "Shared directory connected. Use Manage access to choose accounts.",
                    },
                )
                # An administrator may queue a new operation just after completion.
                # Idle reconciliation will also run in the installed helper.
                with suppress(urllib.error.URLError, TimeoutError):
                    manager.api(config, "reconcile", manager.snapshot(config))
                record["phase"] = "completed"
                storage.atomic_write(RECORD, json.dumps(record))
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                message = (
                    "API verification failed. Review permissions and the Local Storage diagnostics, "
                    "then rerun ./scripts/ark storage setup."
                    if isinstance(error, urllib.error.HTTPError)
                    else str(error)
                )
                record.update(phase="interrupted", message=message)
                storage.atomic_write(RECORD, json.dumps(record))
                with suppress(ValueError, OSError, subprocess.SubprocessError):
                    host_cli("--progress", {"id": job["id"], "state": "failed", "message": message})
                raise ValueError(message) from error
    if not args.no_install:
        subprocess.run(
            ["systemctl", "--user", "restart", "ark-storage-manager.service"], check=True
        )
    next_step = (
        "Open my files" if kind == "managed" else "Manage access to grant account permissions"
    )
    print(f"Local Files ready at {path}. Return to Administration and choose {next_step}.")
    if args.no_install:
        print(
            "For ongoing UI changes, supervise ./scripts/ark storage manager run as this host owner."
        )


def setup(args):
    was_active = (
        not args.no_install
        and shutil.which("systemctl")
        and subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "ark-storage-manager.service"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    try:
        perform_setup(args)
    except (ValueError, OSError, subprocess.SubprocessError):
        if was_active:
            with suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ["systemctl", "--user", "start", "ark-storage-manager.service"],
                    check=True,
                    capture_output=True,
                )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", help="A new dedicated directory; defaults to ~/Ark-Files")
    parser.add_argument(
        "--shared",
        action="store_true",
        help="Create a shared location (default ~/Ark-Shared); grant accounts in Administration",
    )
    parser.add_argument(
        "--no-install", action="store_true", help="Do not install a systemd user service"
    )
    setup(parser.parse_args())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f"ark storage setup: {error}")
