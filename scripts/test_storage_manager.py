"""Host management tests use disposable trees and mocked deployment/API calls."""

import ast
import inspect
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import storage
import storage_fs
import storage_manager as manager


class ManagerTests(unittest.TestCase):
    def test_host_scripts_remain_python_310_compatible(self):
        for module in (storage, storage_fs, manager):
            ast.parse(inspect.getsource(module), feature_version=(3, 10))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.area = self.base / "files"
        self.area.mkdir()
        for module, name, value in [
            (storage, "REPO", self.repo),
            (storage, "CONFIG", self.repo / ".ark-storage"),
            (storage, "STATE", self.repo / ".ark-storage/host.json"),
            (storage, "OVERRIDE", self.repo / "compose.storage.yaml"),
            (manager, "JOURNAL", self.repo / ".ark-storage/manager-journal.json"),
            (manager, "CONFIG", self.repo / ".ark-storage/manager.json"),
        ]:
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        storage.CONFIG.mkdir()
        patcher = patch.object(storage, "local_daemon")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = {
            "approved_paths": [str(self.area)],
            "identities": {str(self.area): [self.area.stat().st_dev, self.area.stat().st_ino]},
        }

    def job(self, action, **payload):
        return {
            "id": str(uuid.uuid4()),
            "action": action,
            "payload": {
                "root_id": "photos",
                "path": str(self.area / "photos"),
                "label": "Photos",
                "owner": str(uuid.uuid4()),
                "read_only": True,
                "selinux": "preserve",
                **payload,
            },
        }

    def test_path_approval_identity_symlinks_and_folder_picker(self):
        folder = self.area / "photos"
        folder.mkdir()
        (self.area / "file").write_text("not listed")
        (self.area / "alias").symlink_to(folder)
        self.assertEqual(manager.browse(self.config, str(self.area))["folders"], [str(folder)])
        for path in (self.base / "outside", self.area / "alias"):
            with self.assertRaises(ValueError):
                manager.approved(self.config, str(path))
        self.config["identities"][str(self.area)][1] += 1
        with self.assertRaisesRegex(ValueError, "identity"):
            manager.approved(self.config, str(folder))

    def test_existing_directory_is_connected_without_permission_changes_and_remove_keeps_files(
        self,
    ):
        folder = self.area / "photos"
        folder.mkdir(mode=0o700)
        original = folder / "original"
        original.write_text("preserve")
        before = folder.stat().st_mode
        job = self.job("add")
        with patch.object(storage, "run") as run:
            manager.execute(self.config, job)
        run.assert_not_called()
        self.assertEqual(folder.stat().st_mode, before)
        # Replay after a crash in multi-file configuration generation.
        storage.OVERRIDE.unlink()
        manager.execute(self.config, job)
        self.assertTrue(storage.OVERRIDE.exists())
        manager.execute(self.config, self.job("remove"))
        self.assertEqual(storage.state()["roots"], [])
        self.assertEqual(original.read_text(), "preserve")

    def test_missing_approved_area_does_not_prevent_disconnecting_registered_root(self):
        folder = self.area / "photos"
        folder.mkdir()
        manager.execute(self.config, self.job("add"))
        folder.rmdir()
        self.area.rmdir()
        with self.assertRaisesRegex(ValueError, "approved storage area is missing"):
            manager.execute(self.config, self.job("update"))
        manager.execute(self.config, self.job("remove"))
        self.assertEqual(storage.state()["roots"], [])

    def test_enrolling_another_area_retains_valid_connected_roots(self):
        folder = self.area / "photos"
        folder.mkdir()
        manager.execute(self.config, self.job("add"))
        another = self.base / "another"
        another.mkdir()
        with patch.object(manager, "compose", return_value="127.0.0.1:5173"):
            manager.enroll(SimpleNamespace(approve=[str(another)], install=False))
        config = json.loads(manager.CONFIG.read_text())
        self.assertEqual(set(config["approved_paths"]), {str(another), str(folder)})
        self.assertEqual(manager.approved(config, str(folder)), folder)

    def test_inventory_reports_missing_approval_without_creating_directories(self):
        self.area.rmdir()
        snapshot = manager.snapshot(self.config)
        self.assertEqual(snapshot["approved_areas"][0]["state"], "missing")
        self.assertFalse(self.area.exists())

    def test_acl_changes_require_explicit_selection_and_folder_ownership(self):
        folder = self.area / "photos"
        folder.mkdir()
        with (
            patch.object(storage, "probe", return_value=(1234, 5678)),
            patch.object(storage, "run") as run,
        ):
            manager.execute(self.config, self.job("add", grant_access=True))
        self.assertEqual(
            run.call_args.args[:3],
            ("setfacl", "-m", f"u:1234:rx,d:u:1234:rx,d:u:{os.getuid()}:rwx"),
        )

    def test_saved_apply_phase_is_replayed_without_provisioning_twice(self):
        job = self.job("remove")
        storage.atomic_write(
            manager.JOURNAL, json.dumps({"job": job, "phase": "apply", "result": {}})
        )
        with (
            patch.object(manager, "compose") as compose,
            patch.object(manager, "api") as api,
            patch.object(manager, "execute") as execute,
        ):
            manager.cycle(self.config)
        execute.assert_not_called()
        self.assertTrue(any(call.args[0] == "up" for call in compose.call_args_list))
        self.assertEqual(api.call_args.args[2]["state"], "completed")
        self.assertFalse(manager.JOURNAL.exists())

    def test_nested_same_filesystem_mounts_are_rejected(self):
        folder = self.area / "nested"
        folder.mkdir()
        with patch.object(manager, "host_mounts", return_value={str(folder)}):
            with self.assertRaisesRegex(ValueError, "nested filesystem"):
                manager.approved(self.config, str(folder))
            self.assertEqual(manager.browse(self.config, str(self.area))["folders"], [])

    def test_canceled_claim_never_executes_host_mutations(self):
        job = self.job("remove")
        with (
            patch.object(
                manager, "api", side_effect=[{}, {"job": job}, {"job": job}, {"accepted": False}]
            ),
            patch.object(manager, "execute") as execute,
        ):
            manager.cycle(self.config)
        execute.assert_not_called()
        self.assertFalse(manager.JOURNAL.exists())

    def test_descriptor_copy_rejects_links_hardlinks_and_real_nested_mounts(self):
        source = self.area / "source"
        target = self.area / "target"
        source.mkdir()
        target.mkdir()
        (source / "link").symlink_to(self.base)
        (source / "body").write_bytes(b"original")
        os.link(source / "body", source / "hardlink")
        with storage_fs.opened(source) as original, storage_fs.opened(target) as copied:
            with self.assertRaises(OSError):
                storage_fs.copy_entry(original, copied, "link")
            with self.assertRaisesRegex(ValueError, "multiply-linked"):
                storage_fs.copy_entry(original, copied, "hardlink")
        root = os.open("/", storage_fs.DIRECTORY)
        try:
            with self.assertRaises(OSError):
                storage_fs.beneath(root, "proc")
        finally:
            os.close(root)

    def test_relocation_preserves_original_hashes_permissions_and_attributes(self):
        source = self.area / "private"
        source.mkdir()
        account = source / "account-id"
        account.mkdir(mode=0o750)
        file = account / "notes"
        file.write_bytes(b"important" * 1000)
        file.chmod(0o640)
        os.setxattr(file, "user.ark-test", b"preserved")
        root = {
            "id": "personal",
            "label": "My files",
            "source": str(source),
            "path": "/srv/ark-storage/personal",
            "device": source.stat().st_dev,
            "inode": source.stat().st_ino,
            "kind": "managed",
            "owner": None,
            "read_only": False,
            "selinux": "private",
        }
        storage.save({"version": 1, "roots": [root]})
        target = self.area / "new-private"
        with (
            patch.object(manager, "compose") as compose,
            patch.object(storage, "provision_new", side_effect=lambda path: path.mkdir(mode=0o700)),
        ):
            manager.execute(
                self.config,
                self.job("relocate", root_id="personal", path=str(target), managed=True),
            )
        self.assertEqual(storage.state()["roots"][0]["source"], str(target))
        manager.verify_copy(account, target / account.name)
        self.assertTrue(file.exists())
        self.assertEqual(os.getxattr(target / "account-id/notes", "user.ark-test"), b"preserved")
        self.assertEqual(compose.call_args_list[0].args, ("stop", "api"))

    def test_relocation_rejects_links_and_restarts_original_configuration(self):
        source = self.area / "private"
        source.mkdir()
        (source / "link").symlink_to(self.base)
        root = {
            "id": "personal",
            "label": "My files",
            "source": str(source),
            "path": "/srv/ark-storage/personal",
            "device": source.stat().st_dev,
            "inode": source.stat().st_ino,
            "kind": "managed",
            "owner": None,
            "read_only": False,
            "selinux": "private",
        }
        storage.save({"version": 1, "roots": [root]})
        with (
            patch.object(manager, "compose") as compose,
            patch.object(storage, "provision_new", side_effect=lambda path: path.mkdir()),
            self.assertRaisesRegex(ValueError, "links"),
        ):
            manager.execute(
                self.config,
                self.job("relocate", root_id="personal", path=str(self.area / "new-private")),
            )
        self.assertEqual(storage.state()["roots"][0]["source"], str(source))
        self.assertEqual(compose.call_args.args[0], "up")


if __name__ == "__main__":
    unittest.main()
