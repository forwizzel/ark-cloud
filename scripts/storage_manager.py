#!/usr/bin/env python3
"""Enrolled host service. Polls the loopback API; never accepts shell/Compose input."""

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import storage
import storage_fs
import storage_permissions

CONFIG = storage.CONFIG / "manager.json"
JOURNAL = storage.CONFIG / "manager-journal.json"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None  # Never forward the host credential to a redirected origin.


HTTP = urllib.request.build_opener(NoRedirect())


def compose(*args, input=None):
    storage.local_daemon()
    command = ["docker", "compose", "-f", str(storage.REPO / "compose.yaml")]
    if storage.OVERRIDE.exists():
        command.extend(["-f", str(storage.OVERRIDE)])
    # No browser input reaches executable names, options, environment or Compose fragments.
    result = subprocess.run(
        command + list(args),
        cwd=storage.REPO,
        input=input,
        text=True,
        capture_output=True,
        timeout=180,
        env={**os.environ, "ARK_BIND_ADDRESS": "127.0.0.1"},
    )
    if result.returncode:
        causes = {
            "permission denied": "Docker or mount access was denied. "
            "Check host permissions and labels.",
            "no such file": "A deployment file or source directory is missing. "
            "Check the mounted disk.",
            "unhealthy": "The API did not become healthy. "
            "Check API startup and database connectivity.",
            "address already in use": "The deployment port is already in use on the host.",
        }
        detail = next(
            (message for phrase, message in causes.items() if phrase in result.stderr.lower()),
            "Docker could not apply the storage configuration. "
            "Check the host Docker service and disk availability.",
        )
        raise ValueError(detail)
    return result.stdout.strip()


def api(config, route, body=None):
    request = urllib.request.Request(
        config["url"] + "/api/storage-manager/" + route,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + config["token"], "Content-Type": "application/json"},
    )
    with HTTP.open(request, timeout=15) as response:
        return json.load(response)


def approved(config, value, *, new=False):
    path = storage.source_path(value)
    anchor = next(
        (
            Path(base)
            for base in config["approved_paths"]
            if path == Path(base) or Path(base) in path.parents
        ),
        None,
    )
    if anchor is None:
        raise ValueError("Choose a folder inside a host-owner-approved area.")
    # Approved roots pin both filesystem and directory identity; no disappeared-disk fallback.
    try:
        info = anchor.stat()
    except FileNotFoundError as error:
        raise ValueError(
            "The approved storage area is missing. "
            "The host owner must verify the disk and re-enroll an existing area."
        ) from error
    expected = config["identities"][str(anchor)]
    if [info.st_dev, info.st_ino] != expected:
        raise ValueError(
            "The approved storage area changed identity. "
            "The host owner must re-enroll after checking the disk."
        )
    current = anchor
    mounts = host_mounts()
    for part in path.relative_to(anchor).parts:
        current /= part
        if not current.exists():
            if new and current == path and current.parent.is_dir():
                break
            raise ValueError(
                "The selected folder is missing. Mount the disk or choose an existing parent."
            )
        if current.is_symlink() or current.stat().st_dev != info.st_dev or str(current) in mounts:
            raise ValueError("Symlinks and nested filesystem mounts cannot be provisioned.")
    return path


def host_mounts():
    with open("/proc/self/mountinfo") as source:
        return {
            re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), line.split()[4])
            for line in source
        }


def browse(config, value):
    if not value:
        return {"path": "", "folders": config["approved_paths"], "parent": None}
    path = approved(config, value)
    anchor = next(
        Path(base)
        for base in config["approved_paths"]
        if path == Path(base) or Path(base) in path.parents
    )
    folders = []
    mounts = host_mounts()
    with os.scandir(path) as entries:
        for entry in entries:
            if (
                entry.path not in mounts
                and entry.is_dir(follow_symlinks=False)
                and entry.stat(follow_symlinks=False).st_dev == path.stat().st_dev
            ):
                try:
                    storage.source_path(entry.path)
                except ValueError:
                    continue
                folders.append(entry.path)
                if len(folders) >= 200:
                    break
    return {
        "path": str(path),
        "folders": sorted(folders),
        "parent": str(path.parent) if path != anchor else "",
    }


def snapshot(config):
    data = storage.state()
    areas = []
    for value in config["approved_paths"]:
        try:
            approved(config, value)
            state, message = "ready", "Available"
        except FileNotFoundError:
            state, message = "missing", "Directory is missing. Review the disk before re-enrolling."
        except (ValueError, OSError) as error:
            state = "missing" if not Path(value).exists() else "unavailable"
            message = str(error)
        areas.append({"path": value, "state": state, "message": message})
    return {
        "roots": data["roots"],
        "approved_paths": config["approved_paths"],
        "approved_areas": areas,
        "repository_path": str(storage.REPO),
        "default_path": str(Path.home() / "Ark-Files"),
        "managed_area": config.get("managed_area", ""),
        "generation": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
    }


def grant_access(path, read_only):
    if path.stat().st_uid != os.getuid():
        raise ValueError(
            "Only the owner of this folder can grant its ACL. "
            "Select a host-owned folder or ask its owner to authorize access."
        )
    uid, _ = storage.probe()
    access = "rx" if read_only else "rwx"
    storage.run(
        "setfacl", "-m", f"u:{uid}:{access},d:u:{uid}:{access},d:u:{os.getuid()}:rwx", str(path)
    )


def inspect_folder(config, path, root=None):
    uid, gid = storage.runtime_identity()
    info = path.stat()
    if root and (info.st_dev, info.st_ino) != (root["device"], root["inode"]):
        raise ValueError("This directory changed identity. Verify the disk before reconnecting it.")
    if not path.is_dir():
        raise ValueError("Choose a directory on the server.")
    with storage_fs.opened(path) as fd:
        for _, _, child in storage_permissions.walk(fd):
            if child.st_uid not in {os.getuid(), uid}:
                raise ValueError(
                    "Content owned by another host account cannot be prepared automatically."
                )
        read_only = bool(os.fstatvfs(fd).f_flag & os.ST_RDONLY)
    return {
        "path": str(path),
        "api_host_uid": uid,
        "api_host_gid": gid,
        "existing_root_id": root["id"] if root else None,
        "checks": [
            {
                "code": "directory_identity",
                "state": "passed",
                "message": "Directory identity verified",
            },
            {
                "code": "provisioning_authority",
                "state": "passed",
                "message": "Host ownership permits automatic access preparation",
            },
            {
                "code": "filesystem_writable",
                "state": "blocked" if read_only else "passed",
                "message": "Filesystem is read-only" if read_only else "Filesystem permits writes",
            },
            {
                "code": "runtime_access",
                "state": "pending",
                "message": "The running API will verify access before accounts are enabled",
            },
        ],
        "message": "Directory inspected. Ark prepares access automatically and verifies the running API before connecting.",
    }


def prepare_access(config, job, path, root=None):
    result = inspect_folder(config, path, root)
    if not job["payload"]["read_only"] and any(
        check["code"] == "filesystem_writable" and check["state"] == "blocked"
        for check in result["checks"]
    ):
        raise ValueError(
            "The filesystem is read-only. Choose read-only access or restore the filesystem."
        )
    storage_permissions.prepare(
        path,
        result["api_host_uid"],
        job["payload"]["read_only"],
        storage.CONFIG / ("permissions-" + job["id"] + ".jsonl"),
    )
    result["checks"].append(
        {
            "code": "unix_access",
            "state": "passed",
            "message": "API access ACLs prepared; existing effective permissions and labels preserved",
        }
    )
    return result


def execute(config, job):
    body = job["payload"]
    action = job["action"]
    data = storage.state()
    root = next((root for root in data["roots"] if root["id"] == body.get("root_id")), None)
    if action == "browse":
        return browse(config, body["path"])
    if action in {"add", "init", "preflight"}:
        managed = action == "init" or (action == "preflight" and body.get("managed", False))
        shared = body.get("shared", False)
        create = body.get("create_directory", False)
        path = approved(config, body["path"], new=managed or create)
        if root is None:
            root = next((r for r in data["roots"] if r["source"] == str(path)), None)
        if root is not None:
            if root["source"] != str(path):
                raise ValueError("The requested ID already belongs to another location.")
            if root["kind"] != ("managed" if managed else "shared" if shared else "assigned") or (
                not managed
                and (
                    root["owner"] != (None if shared else body["owner"])
                    or root["read_only"] != body["read_only"]
                    or root["selinux"] != body["selinux"]
                )
            ):
                raise ValueError(
                    "The assignment changed since this operation. "
                    "Configure the current location instead."
                )
            if action == "preflight":
                return inspect_folder(config, path, root)
            if body.get("automatic_access"):
                result = prepare_access(config, job, path, root)
            else:
                result = {}
            if body.get("grant_access") and not managed:
                grant_access(path, body["read_only"])
            root["label"] = body["label"]
            storage.save(data)  # Reconcile a crash during the multi-file save.
            return result  # Resume a saved configuration after interruption; never create twice.
        for existing in data["roots"]:
            source = Path(existing["source"])
            if source == path or source in path.parents or path in source.parents:
                raise ValueError("Storage locations must not overlap.")
        if (managed or create) and path.exists():
            raise ValueError(
                "New locations require a new directory. Choose another name or connect an existing folder."
            )
        if not managed and not create and not path.is_dir():
            raise ValueError("Choose an existing directory.")
        if action == "preflight":
            if managed or create:
                return {
                    "path": str(path),
                    "message": "Ark will create and verify this new directory.",
                }
            return inspect_folder(config, path)
        result = {}
        if body.get("automatic_access") and not managed and not create:
            result = prepare_access(config, job, path)
        args = SimpleNamespace(
            path=str(path),
            id=body["root_id"],
            owner=body["owner"],
            label=body["label"],
            read_only=body["read_only"],
            selinux=body["selinux"],
        )
        storage.add(
            args,
            managed=managed,
            shared=shared,
            create=create,
            identity=storage.runtime_identity() if body.get("automatic_access") else None,
        )
        if body.get("grant_access") and not managed:
            grant_access(path, body["read_only"])
        if managed and body["label"] != "My files":
            data = storage.state()
            next(root for root in data["roots"] if root["id"] == "personal")["label"] = body[
                "label"
            ]
            storage.save(data)
        return result
    elif action == "repair":
        if root is None:
            raise ValueError("The location was disconnected. Select a new location to connect.")
        if body.get("registration") and body["registration"] != root.get("registration"):
            raise ValueError("This registration changed. Reopen the location before repairing it.")
        path = approved(config, root["source"])
        return prepare_access(config, job, path, root)
    elif action == "relocate":
        if root is None or root["kind"] != "managed":
            raise ValueError("Only a private-folder base can be relocated.")
        storage.pin_registration(root)
        destination = approved(config, body["path"], new=True)
        if root["source"] == str(destination):
            storage.save(data)
            return {}  # Configuration was switched before an interruption.
        source = approved(config, root["source"])
        if [source.stat().st_dev, source.stat().st_ino] != [root["device"], root["inode"]]:
            raise ValueError(
                "The original private-folder base changed identity. "
                "Reconnect the reviewed directory before relocating."
            )
        for existing in data["roots"]:
            original = Path(existing["source"])
            if (
                destination == original
                or original in destination.parents
                or destination in original.parents
            ):
                raise ValueError("The new base must not overlap any current location.")
        relocation(
            config, {**job, "id": body.get("resume_id", job["id"])}, data, root, source, destination
        )
    elif action == "remove":
        # Idempotent recovery after configuration was already saved.
        data["roots"] = [root for root in data["roots"] if root["id"] != body["root_id"]]
        storage.save(data)
    elif action in {"update", "refresh-identity", "check"}:
        if root is None:
            raise ValueError("The storage location no longer exists.")
        path = approved(config, root["source"])
        if action == "update":
            if body.get("automatic_access"):
                prepare_access(config, job, path, root)
            storage.pin_registration(root)
            root["label"] = body["label"]
            if root["kind"] == "assigned":
                root.update(
                    owner=body["owner"], read_only=body["read_only"], selinux=body["selinux"]
                )
            elif root["kind"] == "shared":
                root.update(read_only=body["read_only"], selinux=body["selinux"])
            storage.save(data)
            if body.get("grant_access"):
                grant_access(path, root["read_only"])
        elif action == "refresh-identity":
            storage.pin_registration(root)
            info = path.stat()
            if any(
                r["id"] != root["id"] and (r["device"], r["inode"]) == (info.st_dev, info.st_ino)
                for r in data["roots"]
            ):
                raise ValueError("The filesystem identity is already assigned to another location.")
            root.update(device=info.st_dev, inode=info.st_ino)
            storage.save(data)
    else:
        raise ValueError("Unsupported storage operation.")
    return {}


def relocation(config, job, data, root, source, destination):
    """Copy to a new base while writes are paused. Never erase the original tree."""
    record = storage.CONFIG / ("relocation-" + job["id"] + ".json")
    if record.exists():
        status = json.loads(record.read_text())
        if destination.exists() and status.get("identity") != [
            destination.stat().st_dev,
            destination.stat().st_ino,
        ]:
            raise ValueError(
                "The relocation destination changed identity; owner review is required."
            )
    else:
        if destination.exists():
            raise ValueError(
                "Choose a NEW destination. Existing directories are never merged or overwritten."
            )
        status = {"source": str(source), "destination": str(destination), "identity": None}
        storage.atomic_write(record, json.dumps(status))
    compose("stop", "api")
    try:
        if not destination.exists():
            storage.provision_new(destination)
            status["identity"] = [destination.stat().st_dev, destination.stat().st_ino]
            storage.atomic_write(record, json.dumps(status))
        elif status["identity"] is None:
            raise ValueError(
                "Relocation was interrupted while creating its destination. "
                "Choose a new destination; the original files are preserved."
            )
        source_device = source.stat().st_dev
        mounts = host_mounts()
        # Validate every entry before copying; never follow links or nested mounts.
        for directory, folders, files in os.walk(source, followlinks=False):
            if len(Path(directory).relative_to(source).parts) > 33:
                raise ValueError(
                    "The private tree exceeds the supported path depth. "
                    "Original files are preserved."
                )
            for name in folders + files:
                entry = Path(directory) / name
                info = entry.lstat()
                if (
                    str(entry) in mounts
                    or info.st_dev != source_device
                    or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)
                ):
                    raise ValueError(
                        "The private tree contains links, special files or nested mounts. "
                        "Resolve these before relocation."
                    )
        # Copy each account tree to an operation-owned staging directory, then publish
        # without merging. A retry can discard only its own incomplete staging tree.
        stage = destination / (".ark-relocation-" + job["id"])
        if stage.exists():
            with storage_fs.opened(destination) as target:
                storage_fs.remove_directory(target, stage.name)
        stage.mkdir(mode=0o700)
        try:
            with (
                storage_fs.opened(source) as original,
                storage_fs.opened(destination) as target,
                storage_fs.opened(stage) as staged,
            ):
                for name in os.listdir(original):
                    if name.startswith(".ark-"):
                        continue
                    try:
                        os.stat(name, dir_fd=target, follow_symlinks=False)
                    except FileNotFoundError:
                        storage_fs.copy_entry(original, staged, name)
                        storage_fs.verify_entry(original, staged, name)
                        storage_fs.publish(staged, name, target)
                    storage_fs.verify_entry(original, target, name)
            root.update(
                source=str(destination),
                device=destination.stat().st_dev,
                inode=destination.stat().st_ino,
            )
            storage.save(data)
        finally:
            if stage.exists():
                with storage_fs.opened(destination) as target:
                    storage_fs.remove_directory(target, stage.name)
    finally:
        # On failure, the original configuration remains authoritative and is restarted.
        compose("up", "--detach", "--no-deps", "--force-recreate", "--wait", "api")


def verify_copy(source, target):
    with storage_fs.opened(source.parent) as original, storage_fs.opened(target.parent) as copied:
        if source.name == target.name:
            storage_fs.verify_entry(original, copied, source.name)
        else:
            raise ValueError("Relocation verification requires matching entry names.")


def cycle(config):
    if JOURNAL.exists():
        pending = json.loads(JOURNAL.read_text())
    else:
        api(config, "report", snapshot(config))
        job = api(config, "work")["job"]
        if job is None:
            api(config, "reconcile", snapshot(config))
            return
        pending = {"job": job, "phase": "prepare"}
        storage.atomic_write(JOURNAL, json.dumps(pending))
    job = pending["job"]
    if pending["phase"] == "prepare":
        # Persist authorization before any outage-causing operation. Recovery of an
        # already-started relocation must work even while the API is stopped.
        if not pending.get("authorized"):
            current = api(config, "work")["job"]
            if current is None or current["id"] != job["id"]:
                JOURNAL.unlink(missing_ok=True)
                return
            claim = api(
                config,
                "report",
                {
                    **snapshot(config),
                    "job_id": job["id"],
                    "state": "applying",
                    "message": "Validating host configuration.",
                },
            )
            if not claim.get("accepted"):
                JOURNAL.unlink(missing_ok=True)
                return
            pending["authorized"] = True
            storage.atomic_write(JOURNAL, json.dumps(pending))
        try:
            with storage.configuration_lock():
                # Retain the previous configuration for owner recovery; never delete content.
                storage.atomic_write(
                    storage.CONFIG / "previous-configuration.json", json.dumps(storage.state())
                )
                result = execute(config, job)
                pending.update(phase="apply", result=result)
                storage.atomic_write(JOURNAL, json.dumps(pending))
                if job["action"] not in {"browse", "preflight", "check"}:
                    # Deployment recovery cannot depend on the API being up.
                    with suppress(urllib.error.URLError, TimeoutError):
                        api(
                            config,
                            "report",
                            {
                                **snapshot(config),
                                "job_id": job["id"],
                                "state": "applying",
                                "message": "Applying mounts. The API will briefly restart.",
                            },
                        )
                    compose("config", "--quiet")
                    compose("up", "--detach", "--no-deps", "--force-recreate", "--wait", "api")
            pending.update(
                phase="report",
                state="completed",
                message=(
                    "Access check passed."
                    if job["action"] == "check"
                    else "Storage operation completed."
                ),
            )
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            pending.update(
                phase="report",
                state="failed",
                message=str(error)[:2000],
                result={
                    "checks": [
                        {
                            "code": "host_preparation",
                            "state": "blocked",
                            "message": str(error)[:2000],
                        }
                    ]
                },
            )
        storage.atomic_write(JOURNAL, json.dumps(pending))
    elif pending["phase"] == "apply":
        # A crash between saving configuration and recreating the API is safe to replay.
        with storage.configuration_lock():
            if job["action"] not in {"browse", "preflight", "check"}:
                compose("config", "--quiet")
                compose("up", "--detach", "--no-deps", "--force-recreate", "--wait", "api")
        pending.update(phase="report", state="completed", message="Storage operation completed.")
        storage.atomic_write(JOURNAL, json.dumps(pending))
    try:
        if pending["state"] == "completed":
            api(
                config,
                "report",
                {
                    **snapshot(config),
                    "job_id": job["id"],
                    "state": "verifying",
                    "message": "Verifying the applied configuration as the API user.",
                },
            )
        reported = snapshot(config)
        recorded = api(
            config,
            "report",
            {
                **reported,
                "job_id": job["id"],
                "state": pending["state"],
                "message": pending["message"],
                "result": pending.get("result", {}),
            },
        )
        if (
            recorded.get("accepted")
            and pending["state"] == "completed"
            and job["action"] not in {"browse", "preflight"}
        ):
            storage.atomic_write(
                storage.CONFIG / "last-good.json",
                json.dumps({"version": 1, "roots": reported["roots"]}),
            )
    except urllib.error.HTTPError as error:
        if (
            error.code in {400, 403, 404, 409, 413, 422, 503, 507}
            and pending["state"] == "completed"
        ):
            # Preserve the applied mount and expose a recoverable access/configuration failure.
            try:
                detail = json.loads(error.read(8192)).get("detail")
            except (ValueError, AttributeError):
                detail = None
            runtime_checks = []
            if isinstance(detail, dict):
                runtime_checks = detail.get("checks", [])
                detail = detail.get("message")
            detail = detail[:1000] if isinstance(detail, str) else "The API access check failed."
            pending.update(
                state="failed",
                message=f"Runtime verification needs attention: {detail}",
                result={
                    **pending.get("result", {}),
                    "checks": [
                        *pending.get("result", {}).get("checks", []),
                        *runtime_checks,
                        {"code": "runtime_access", "state": "blocked", "message": detail},
                    ],
                },
            )
            storage.atomic_write(JOURNAL, json.dumps(pending))
        raise
    JOURNAL.unlink(missing_ok=True)


def enroll(args):
    if sys.platform != "linux":
        raise ValueError("Host storage management requires Linux with openat2 support.")
    storage.local_daemon()
    paths = sorted({storage.source_path(value) for value in args.approve})
    # Adding an area must not strand an already-connected location outside the
    # manager's scope. Retain only existing roots with their recorded identity;
    # missing/replaced roots stay unavailable but can still be disconnected.
    for root in storage.state()["roots"]:
        source = storage.source_path(root["source"])
        if source.is_dir():
            info = source.stat()
            if (info.st_dev, info.st_ino) == (root["device"], root["inode"]):
                if not any(source == p or p in source.parents for p in paths):
                    paths.append(source)
    paths = sorted(set(paths))
    if not 1 <= len(paths) <= 32 or any(not path.is_dir() for path in paths):
        raise ValueError("Approve at least one existing dedicated directory area.")
    token = secrets.token_urlsafe(48)
    compose(
        "exec",
        "-T",
        "api",
        "python",
        "-m",
        "app.services.storage_manager_cli",
        *(["--setup"] if getattr(args, "setup", False) else []),
        input=token + "\n",
    )
    binding = compose("port", "web", "5173")
    port = int(binding.rsplit(":", 1)[1])
    storage.CONFIG.mkdir(mode=0o755, exist_ok=True)
    storage.atomic_write(
        CONFIG,
        json.dumps(
            {
                "token": token,
                "url": f"http://127.0.0.1:{port}",
                "approved_paths": [str(path) for path in paths],
                "identities": {
                    str(path): [path.stat().st_dev, path.stat().st_ino] for path in paths
                },
            }
        ),
    )
    print("Storage manager enrolled. Approved areas: " + ", ".join(map(str, paths)))
    if args.install:
        install_service()


def install_service(*, start=True):
    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)

    # systemd uses its own quoting/percent expansion, not shell quoting.
    def quoted(value):
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'

    unit = (
        "[Unit]\nDescription=Ark Cloud storage manager\nAfter=default.target\n\n"
        "[Service]\nType=simple\nExecStart="
        + quoted(sys.executable)
        + " "
        + quoted(Path(__file__).resolve())
        + " run\n"
        "Restart=on-failure\nRestartSec=5\nUMask=0077\n\n[Install]\nWantedBy=default.target\n"
    )
    storage.atomic_write(unit_dir / "ark-storage-manager.service", unit, 0o644)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "ark-storage-manager.service"], check=True)
    if start:
        subprocess.run(
            ["systemctl", "--user", "restart", "ark-storage-manager.service"], check=True
        )
        print("Host storage manager installed and started.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    enroll_parser = sub.add_parser("enroll")
    enroll_parser.add_argument("--approve", action="append", required=True)
    enroll_parser.add_argument("--install", action="store_true")
    sub.add_parser("run")
    args = parser.parse_args()
    if args.command == "enroll":
        with storage.configuration_lock():
            enroll(args)
        return
    config = json.loads(CONFIG.read_text())
    import fcntl

    process_lock = (storage.CONFIG / "manager-process.lock").open("a")
    try:
        fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise ValueError("The storage manager is already running.") from error
    while True:
        try:
            config = json.loads(CONFIG.read_text())
            cycle(config)
        except (OSError, ValueError, subprocess.SubprocessError):
            # Never print response bodies, host paths, credentials or raw Docker output.
            print(
                "Storage manager could not complete a cycle; retrying in five seconds.",
                file=sys.stderr,
                flush=True,
            )
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f"ark storage manager: {error}")
