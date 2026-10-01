#!/usr/bin/env python3
"""Host-owned mount provisioning, shared by the CLI and enrolled storage manager."""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / ".ark-storage"
STATE = CONFIG / "host.json"
OVERRIDE = REPO / "compose.storage.yaml"


@contextmanager
def configuration_lock():
    CONFIG.mkdir(mode=0o755, exist_ok=True)
    with (CONFIG / "configuration.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run(*args):
    return subprocess.check_output(args, cwd=REPO, text=True, timeout=180).strip()


def local_daemon():
    endpoint = (
        os.environ.get("DOCKER_HOST")
        or json.loads(run("docker", "context", "inspect"))[0]["Endpoints"]["docker"]["Host"]
    )
    if not endpoint.startswith("unix://"):
        raise ValueError("Storage provisioning requires a local Unix-socket Docker daemon.")


def probe():
    local_daemon()
    image = run("docker", "compose", "images", "-q", "api")
    if not image:
        configuration = json.loads(run("docker", "compose", "config", "--format", "json"))
        image = configuration["services"]["api"].get("image", configuration["name"] + "-api")
    code = (
        "import json,os; print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),"
        "'uids':open('/proc/self/uid_map').read(),'gids':open('/proc/self/gid_map').read()}))"
    )
    info = json.loads(
        run("docker", "run", "--pull=never", "--rm", "--entrypoint", "python", image, "-c", code)
    )

    def mapped(value, text):
        for line in text.splitlines():
            inside, outside, size = map(int, line.split())
            if inside <= value < inside + size:
                return outside + value - inside
        raise ValueError("Cannot determine host UID mapping.")

    return mapped(info["uid"], info["uids"]), mapped(info["gid"], info["gids"])


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {"version": 1, "roots": []}


def pin_registration(root):
    if not root.get("registration"):
        name = f"ark-storage:{root['id']}:{root['kind']}:{root['device']}:{root['inode']}:{root.get('owner') or ''}"
        root["registration"] = str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def source_path(value):
    path = Path(value).expanduser().absolute()
    if path != path.resolve():
        raise ValueError("Source must be canonical, without symlinks or '..'.")
    if path == Path.home() or path in {
        Path("/"),
        Path("/home"),
        Path("/srv"),
        Path("/mnt"),
        Path("/media"),
    }:
        raise ValueError("Select a dedicated subdirectory, not a whole home or host root.")
    forbidden = [
        REPO,
        Path("/etc"),
        Path("/proc"),
        Path("/sys"),
        Path("/dev"),
        Path("/run"),
        Path("/usr"),
        Path("/var"),
        Path("/root"),
        Path.home() / ".ssh",
        Path.home() / ".config",
    ]
    if any(path == p or p in path.parents or path in p.parents for p in forbidden):
        raise ValueError("Source overlaps application, system, or credential directories.")
    return path


def save(data, *, announce=True):
    CONFIG.mkdir(mode=0o755, exist_ok=True)
    manifest = {"version": 1, "roots": []}
    mounts = [
        {
            "type": "bind",
            "source": str(CONFIG / "manifest.json").replace("$", "$$"),
            "target": "/etc/ark-storage/manifest.json",
            "read_only": True,
            "bind": {"create_host_path": False, "selinux": "Z"},
        }
    ]
    for item in data["roots"]:
        root = {key: value for key, value in item.items() if key not in {"source", "selinux"}}
        manifest["roots"].append(root)
        options = {"create_host_path": False, "propagation": "rprivate"}
        if item["selinux"] != "preserve":
            options["selinux"] = "Z" if item["selinux"] == "private" else "z"
        mounts.append(
            {
                "type": "bind",
                "source": item["source"].replace("$", "$$"),
                "target": item["path"],
                "read_only": item["read_only"],
                "bind": options,
            }
        )
    # JSON is valid YAML. Configuration contains paths and IDs, never credentials.
    outputs = [
        (STATE, data),
        (CONFIG / "manifest.json", manifest),
        (OVERRIDE, {"services": {"api": {"volumes": mounts}}}),
    ]
    previous = {path: path.read_bytes() if path.exists() else None for path, _ in outputs}
    try:
        for path, value in outputs:
            atomic_write(path, json.dumps(value, indent=2) + "\n", 0o644)
    except BaseException:
        for path, content in previous.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, content, 0o644)
        raise
    if announce:
        print(
            "Storage configuration saved. Apply it with ./scripts/ark up, "
            "then run ./scripts/ark storage check."
        )


def atomic_write(path, content, mode=0o600):
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as output:
            output.write(content.encode() if isinstance(content, str) else content)
            output.flush()
            # The manager's systemd unit uses UMask=0077. os.open's mode is
            # masked by that umask, so set the intended mode before publishing.
            os.fchmod(output.fileno(), mode)
            os.fsync(output.fileno())
        temp.replace(path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def add(args, managed=False, *, shared=False, create=False):
    local_daemon()
    data = state()
    path = source_path(args.path)
    root_id = "personal" if managed else args.id
    if len(data["roots"]) >= 32:
        raise ValueError("At most 32 roots are supported.")
    if not managed and (not args.label.strip() or len(args.label) > 80):
        raise ValueError("Label must be between 1 and 80 characters.")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", root_id):
        raise ValueError("Root ID must use lowercase letters, digits, and hyphens.")
    if any(item["id"] == root_id for item in data["roots"]):
        raise ValueError(
            "Root ID already exists. Use storage check; remove explicitly before replacing."
        )
    for item in data["roots"]:
        existing = Path(item["source"])
        if path == existing or path in existing.parents or existing in path.parents:
            raise ValueError("Storage roots must not overlap.")
    if managed or create:
        provision_new(path)
    if not path.is_dir():
        raise ValueError("Source must be an existing directory.")
    info = path.stat()
    if any((r["device"], r["inode"]) == (info.st_dev, info.st_ino) for r in data["roots"]):
        raise ValueError("This filesystem root is already registered under another path.")
    owner = None if managed or shared else str(uuid.UUID(args.owner))
    data["roots"].append(
        {
            "id": root_id,
            "label": "My files" if managed else args.label,
            "source": str(path),
            "path": f"/srv/ark-storage/{root_id}",
            "device": info.st_dev,
            "inode": info.st_ino,
            "kind": "managed" if managed else "shared" if shared else "assigned",
            "owner": owner,
            "read_only": False if managed else args.read_only,
            "selinux": "private" if managed or create else args.selinux,
            "registration": str(uuid.uuid4()),
        }
    )
    save(data)


def provision_new(path):
    if path.exists():
        raise ValueError(
            "Init requires a NEW directory; it will not relabel or change existing data."
        )
    if not shutil.which("setfacl"):
        raise ValueError("Install Fedora's acl package (setfacl) before provisioning.")
    uid, gid = probe()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir(mode=0o700)
    try:
        run("setfacl", "-m", f"u:{uid}:rwx,d:u:{uid}:rwx,d:u:{os.getuid()}:rwx", str(path))
    except (OSError, subprocess.CalledProcessError):
        path.rmdir()
        raise
    print(f"API maps to host UID {uid}, GID {gid}; a narrow ACL was applied to the new directory.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Provision a NEW private data directory and its ACL")
    init.add_argument("--path", default=str(Path.home() / ".local/share/ark-cloud/files"))
    register = sub.add_parser(
        "add", help="Register an existing directory; does not alter Unix permissions"
    )
    register.add_argument("--id", required=True)
    register.add_argument("--path", required=True)
    register.add_argument("--owner", required=True, help="Immutable local account UUID")
    register.add_argument("--label", required=True)
    register.add_argument("--read-only", action="store_true")
    register.add_argument(
        "--selinux",
        choices=["preserve", "private", "shared"],
        required=True,
        help="private/shared explicitly authorize Docker recursive relabeling on startup",
    )
    remove = sub.add_parser("remove", help="Unregister a root; never deletes host files")
    remove.add_argument("id")
    remove.add_argument("--confirm", action="store_true", required=True)
    refresh = sub.add_parser("refresh-identity", help="Accept a reviewed remount's new identity")
    refresh.add_argument("id")
    refresh.add_argument("--confirm", action="store_true", required=True)
    sub.add_parser("list", help="Show owner-only host configuration")
    args = parser.parse_args()
    with configuration_lock():
        execute(args)


def execute(args):
    if args.command == "init":
        add(args, managed=True)
    elif args.command == "add":
        add(args)
    elif args.command in {"remove", "refresh-identity"}:
        data = state()
        if not any(r["id"] == args.id for r in data["roots"]):
            raise ValueError("Unknown root ID.")
        if args.command == "remove":
            data["roots"] = [r for r in data["roots"] if r["id"] != args.id]
        else:
            local_daemon()
            root = next(r for r in data["roots"] if r["id"] == args.id)
            pin_registration(root)
            path = source_path(root["source"])
            if not path.is_dir():
                raise ValueError("The source directory is missing.")
            info = path.stat()
            if any(
                r["id"] != root["id"] and (r["device"], r["inode"]) == (info.st_dev, info.st_ino)
                for r in data["roots"]
            ):
                raise ValueError("This filesystem identity is already assigned to another root.")
            root.update(device=info.st_dev, inode=info.st_ino)
        save(data)
    else:
        print(json.dumps(state(), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f"ark storage: {error}")
