"""Complete setup orchestration with disposable files and mocked Docker/systemd."""

import ast
import inspect
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import storage
import storage_manager as manager
import storage_setup as setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.path = self.base / "Ark-Files"
        for module, name, value in [
            (storage, "REPO", self.repo),
            (storage, "CONFIG", self.repo / ".ark-storage"),
            (storage, "STATE", self.repo / ".ark-storage/host.json"),
            (storage, "OVERRIDE", self.repo / "compose.storage.yaml"),
            (manager, "CONFIG", self.repo / ".ark-storage/manager.json"),
            (manager, "JOURNAL", self.repo / ".ark-storage/manager-journal.json"),
            (setup, "RECORD", self.repo / ".ark-storage/setup-journal.json"),
        ]:
            self.mock(module, name, value)
        self.mock(storage, "local_daemon")
        self.mock(storage, "probe", return_value=(1234, 5678))
        self.mock(storage, "run")
        self.mock(setup.shutil, "which", return_value="tool")
        self.compose = self.mock(manager, "compose")
        self.cli = self.mock(setup, "host_cli", return_value={"id": "setup-job"})
        self.api = self.mock(manager, "api", return_value={"accepted": True})

        def enrolled(args):
            config = {
                "token": "test-token",
                "url": "http://127.0.0.1:5173",
                "approved_paths": args.approve,
                "identities": {
                    p: [Path(p).stat().st_dev, Path(p).stat().st_ino] for p in args.approve
                },
            }
            storage.atomic_write(manager.CONFIG, json.dumps(config))

        self.enroll = self.mock(manager, "enroll", side_effect=enrolled)

    def mock(self, module, name, *args, **kwargs):
        patcher = patch.object(module, name, *args, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def run_setup(self, **changes):
        setup.setup(SimpleNamespace(path=str(self.path), no_install=True, **changes))

    def test_host_setup_is_python_310_compatible(self):
        ast.parse(inspect.getsource(setup), feature_version=(3, 10))

    def test_fresh_setup_creates_one_private_base_and_repeat_preserves_files(self):
        self.run_setup()
        root = storage.state()["roots"][0]
        self.assertEqual(root["source"], str(self.path))
        self.assertEqual(root["kind"], "managed")
        self.assertEqual(root["selinux"], "private")
        original = self.path / "original"
        original.write_text("keep")
        inode = self.path.stat().st_ino
        self.run_setup()
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertEqual(original.read_text(), "keep")
        self.assertEqual(len(storage.state()["roots"]), 1)
        self.assertEqual(json.loads(setup.RECORD.read_text())["phase"], "completed")
        completed = [
            c.args[2]
            for c in self.api.call_args_list
            if c.args[1] == "report" and c.args[2]["state"] == "completed"
        ]
        self.assertEqual(len(completed), 2)

    def test_existing_unregistered_directory_is_never_repurposed(self):
        self.path.mkdir()
        file = self.path / "important"
        file.write_text("keep")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.run_setup()
        self.assertEqual(file.read_text(), "keep")
        self.cli.assert_not_called()
        self.assertFalse(storage.STATE.exists())

    def test_interrupted_apply_resumes_without_creating_a_second_base(self):
        self.compose.side_effect = ValueError("Docker could not apply mounts")
        with self.assertRaisesRegex(ValueError, "apply mounts"):
            self.run_setup()
        inode = self.path.stat().st_ino
        self.assertEqual(json.loads(setup.RECORD.read_text())["phase"], "interrupted")
        self.compose.side_effect = None
        self.run_setup()
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertEqual(len(storage.state()["roots"]), 1)

    def test_verification_failure_is_reported_and_not_marked_ready(self):
        self.api.side_effect = urllib.error.HTTPError("", 503, "denied", {}, None)
        with self.assertRaisesRegex(ValueError, "verification failed"):
            self.run_setup()
        self.assertEqual(json.loads(setup.RECORD.read_text())["phase"], "interrupted")
        self.assertTrue(
            any(
                c.args[1].get("state") == "failed"
                for c in self.cli.call_args_list
                if len(c.args) > 1
            )
        )

    def test_identity_change_and_missing_registered_base_fail_closed(self):
        self.run_setup()
        data = storage.state()
        data["roots"][0]["inode"] += 1
        storage.save(data)
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.run_setup()
        self.path.rmdir()
        with self.assertRaisesRegex(ValueError, "location is missing"):
            self.run_setup()

    def test_unfinished_manager_operation_is_preserved(self):
        storage.CONFIG.mkdir()
        storage.atomic_write(manager.JOURNAL, json.dumps({"phase": "apply", "job": {"id": "old"}}))
        self.compose.return_value = json.dumps({"state": "applying"})
        with self.assertRaisesRegex(ValueError, "unfinished host operation"):
            self.run_setup()
        self.assertTrue(manager.JOURNAL.exists())
        self.assertFalse(self.path.exists())

    def test_finished_report_journal_is_archived_before_new_setup(self):
        storage.CONFIG.mkdir()
        storage.atomic_write(manager.JOURNAL, json.dumps({"phase": "report", "job": {"id": "old"}}))
        self.compose.return_value = json.dumps({"state": "failed"})
        self.run_setup()
        self.assertFalse(manager.JOURNAL.exists())
        self.assertTrue((storage.CONFIG / "previous-manager-journal.json").exists())

    def test_default_flow_installs_service_and_restores_it_on_preflight_failure(self):
        commands = self.mock(
            setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        )
        installer = self.mock(manager, "install_service")
        setup.setup(SimpleNamespace(path=str(self.path), no_install=False))
        installer.assert_called_once_with(start=False)
        self.assertEqual(
            commands.call_args.args[0],
            ["systemctl", "--user", "restart", "ark-storage-manager.service"],
        )
        conflict = self.base / "existing"
        conflict.mkdir()
        # Choose a different path on an established deployment: no silent relocation.
        with self.assertRaisesRegex(ValueError, "already have a base"):
            setup.setup(SimpleNamespace(path=str(conflict), no_install=False))
        self.assertEqual(
            commands.call_args.args[0],
            ["systemctl", "--user", "start", "ark-storage-manager.service"],
        )

    def test_shared_setup_preserves_private_base_and_does_not_create_account_subfolders(self):
        self.run_setup()
        private = storage.state()["roots"][0]
        target = self.base / "Ark-Shared"
        setup.setup(SimpleNamespace(path=str(target), no_install=True, shared=True))
        roots = storage.state()["roots"]
        self.assertEqual(roots[0], private)
        self.assertEqual(roots[1]["kind"], "shared")
        self.assertEqual(roots[1]["owner"], None)
        self.assertNotEqual(roots[1]["registration"], private["registration"])
        self.assertEqual(list(target.iterdir()), [])
        setup.setup(SimpleNamespace(path=str(target), no_install=True, shared=True))
        self.assertEqual(len(storage.state()["roots"]), 2)


if __name__ == "__main__":
    unittest.main()
