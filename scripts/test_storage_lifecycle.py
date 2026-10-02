"""Exercise the real lifecycle shell and preflight with a disposable Docker shim."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        scripts = self.repo / "scripts"
        scripts.mkdir(parents=True)
        for name in ("ark", "storage.py", "storage_health.py", "storage_fs.py"):
            shutil.copyfile(Path(__file__).parent / name, scripts / name)
        (scripts / "ark").chmod(0o755)
        (scripts / "storage_bootstrap.py").write_text(
            "# No service enrollment in disposable tests.\n"
        )
        (self.repo / ".env").write_text("# Test deployment\n")
        (self.repo / "compose.yaml").write_text("services: {}\n")
        self.source = self.base / "content"
        self.source.mkdir()
        info = self.source.stat()
        self.state = {
            "version": 1,
            "roots": [
                {
                    "id": "content",
                    "label": "Content",
                    "source": str(self.source),
                    "path": "/srv/ark-storage/content",
                    "device": info.st_dev,
                    "inode": info.st_ino,
                    "kind": "shared",
                    "owner": None,
                    "read_only": False,
                    "selinux": "preserve",
                }
            ],
        }
        config = self.repo / ".ark-storage"
        config.mkdir()
        (config / "host.json").write_text(json.dumps(self.state))
        (config / "manager.json").write_text(
            json.dumps(
                {
                    "approved_paths": [str(self.source)],
                    "identities": {str(self.source): [info.st_dev, info.st_ino]},
                }
            )
        )
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.log = self.base / "commands.jsonl"
        shim = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as log:
    log.write(json.dumps([Path(sys.argv[0]).name, *args]) + "\\n")
if "port" in args:
    print("127.0.0.1:5173")
if "up" in args:
    if os.environ.get("FAIL_UNRELATED"):
        sys.exit(1)
    source = Path(os.environ["SOURCE"])
    if os.environ.get("DELETE_DURING_UP") and source.exists():
        source.rmdir()
    for item in json.loads(os.environ.get("DELETE_SEQUENCE", "[]")):
        if Path(item).exists():
            Path(item).rmdir()
            break
    mounts = json.loads(Path("compose.storage.yaml").read_text())["services"]["api"]["volumes"]
    if any(not Path(m["source"]).exists() for m in mounts):
        print("invalid mount config: bind source path does not exist", file=sys.stderr)
        sys.exit(1)
"""
        for tool in ("docker", "curl", "systemctl"):
            path = self.bin / tool
            path.write_text(shim)
            path.chmod(0o755)

    def run_ark(self, action, **extra):
        result = subprocess.run(
            [str(self.repo / "scripts/ark"), action],
            cwd=self.repo,
            env={
                **os.environ,
                "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                "COMMAND_LOG": str(self.log),
                "SOURCE": str(self.source),
                **extra,
            },
            text=True,
            capture_output=True,
            timeout=20,
        )
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(json.loads((self.repo / ".ark-storage/host.json").read_text()), self.state)
        return result, calls

    def test_up_and_restart_omit_deleted_sources_before_docker(self):
        self.source.rmdir()
        for action in ("up", "restart"):
            with self.subTest(action=action):
                result, _ = self.run_ark(action)
                self.assertEqual(result.returncode, 0, result.stderr)
                mounts = json.loads((self.repo / "compose.storage.yaml").read_text())["services"][
                    "api"
                ]["volumes"]
                self.assertEqual(len(mounts), 1)
                self.assertFalse(self.source.exists())

    def test_deletion_during_bind_creation_retries_with_missing_source_omitted(self):
        result, calls = self.run_ark("up", DELETE_DURING_UP="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(call[0] == "docker" and "up" in call for call in calls), 2)
        self.assertFalse(self.source.exists())

    def test_unrelated_startup_failure_is_not_retried_and_restores_manager(self):
        result, calls = self.run_ark("up", FAIL_UNRELATED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(call[0] == "docker" and "up" in call for call in calls), 1)
        self.assertIn(["systemctl", "--user", "start", "ark-storage-manager.service"], calls)

    def test_successive_deletions_during_retries_still_start_core_services(self):
        second = self.base / "second"
        second.mkdir()
        info = second.stat()
        self.state["roots"].append(
            {
                **self.state["roots"][0],
                "id": "second",
                "source": str(second),
                "path": "/srv/ark-storage/second",
                "device": info.st_dev,
                "inode": info.st_ino,
            }
        )
        config = self.repo / ".ark-storage"
        (config / "host.json").write_text(json.dumps(self.state))
        manager = json.loads((config / "manager.json").read_text())
        manager["approved_paths"].append(str(second))
        manager["identities"][str(second)] = [info.st_dev, info.st_ino]
        (config / "manager.json").write_text(json.dumps(manager))
        result, calls = self.run_ark(
            "up", DELETE_SEQUENCE=json.dumps([str(self.source), str(second)])
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(call[0] == "docker" and "up" in call for call in calls), 3)
