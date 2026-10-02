"""Owner-tool checks: never use real data directories or Docker."""

import argparse
import json
import os
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import storage
import storage_health


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for name, value in {
            "REPO": self.base / "repo",
            "CONFIG": self.base / "repo/.ark-storage",
            "STATE": self.base / "repo/.ark-storage/host.json",
            "OVERRIDE": self.base / "repo/compose.storage.yaml",
        }.items():
            patcher = patch.object(storage, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        storage.REPO.mkdir()
        patcher = patch.object(storage, "local_daemon")
        patcher.start()
        self.addCleanup(patcher.stop)

    def args(self, path, **changes):
        values = dict(
            path=str(path),
            id="photos",
            owner=str(uuid.uuid4()),
            label="Photos",
            read_only=True,
            selinux="preserve",
        )
        return argparse.Namespace(**(values | changes))

    def test_existing_root_is_not_modified_and_mount_does_not_autocreate(self):
        source = self.base / "photos"
        source.mkdir(mode=0o700)
        (source / "original").write_text("preserve")
        before = source.stat()
        with patch.object(storage, "run") as command:
            storage.add(self.args(source))
        command.assert_not_called()
        manifest = json.loads((storage.CONFIG / "manifest.json").read_text())
        self.assertEqual(manifest["roots"][0]["inode"], before.st_ino)
        compose = json.loads(storage.OVERRIDE.read_text())
        mount = compose["services"]["api"]["volumes"][1]
        self.assertTrue(mount["read_only"])
        self.assertFalse(mount["bind"]["create_host_path"])
        self.assertNotIn("selinux", mount["bind"])
        self.assertEqual(source.stat().st_mode, before.st_mode)
        self.assertEqual((source / "original").read_text(), "preserve")

    def test_atomic_save_honors_modes_under_manager_umask(self):
        previous = os.umask(0o077)
        try:
            storage.save({"version": 1, "roots": []})
            for path in (storage.STATE, storage.CONFIG / "manifest.json", storage.OVERRIDE):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            credential = storage.CONFIG / "manager.json"
            storage.atomic_write(credential, "private")
            self.assertEqual(stat.S_IMODE(credential.stat().st_mode), 0o600)
            storage.save({"version": 1, "roots": []})
            self.assertEqual(stat.S_IMODE((storage.CONFIG / "manifest.json").stat().st_mode), 0o644)
        finally:
            os.umask(previous)

    def test_init_refuses_existing_tree_before_changing_permissions(self):
        source = self.base / "existing"
        source.mkdir()
        with (
            patch.object(storage, "probe") as probe,
            self.assertRaisesRegex(ValueError, "NEW directory"),
        ):
            storage.add(self.args(source), managed=True)
        probe.assert_not_called()
        self.assertFalse(storage.OVERRIDE.exists())

    def test_overlap_and_symlink_sources_are_rejected(self):
        source = self.base / "photos"
        source.mkdir()
        storage.add(self.args(source))
        child = source / "private"
        child.mkdir()
        with self.assertRaisesRegex(ValueError, "overlap"):
            storage.add(self.args(child, id="private"))
        alias = self.base / "alias"
        alias.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "canonical"):
            storage.add(self.args(alias, id="alias"))

    def test_root_and_application_sources_are_rejected(self):
        for path in ["/", "/etc", "/proc", str(Path.home()), str(storage.REPO)]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                storage.source_path(path)

    def test_missing_and_replaced_sources_are_omitted_without_retiring_registration(self):
        first = self.base / "first"
        second = self.base / "second"
        first.mkdir()
        second.mkdir()
        storage.add(self.args(first, id="first"))
        storage.add(self.args(second, id="second"))
        original = storage.state()
        first.rmdir()
        self.assertTrue(storage_health.reconcile())
        self.assertEqual(storage.state(), original)
        manifest = json.loads((storage.CONFIG / "manifest.json").read_text())
        self.assertEqual(len(manifest["roots"]), 2)
        self.assertEqual(manifest["host_health"]["first"]["state"], "missing")
        mounts = json.loads(storage.OVERRIDE.read_text())["services"]["api"]["volumes"]
        self.assertEqual([m["source"] for m in mounts[1:]], [str(second)])
        self.assertFalse(first.exists())
        # Keep the old inode allocated so replacement cannot coincidentally reuse it.
        second.rename(self.base / "original-second")
        second.mkdir()
        storage_health.reconcile()
        mounts = json.loads(storage.OVERRIDE.read_text())["services"]["api"]["volumes"]
        self.assertEqual(len(mounts), 1)
        self.assertEqual(storage.state(), original)

    def test_symlink_replacement_is_not_mounted_or_followed(self):
        source = self.base / "photos"
        source.mkdir()
        storage.add(self.args(source))
        source.rename(self.base / "original")
        source.symlink_to(self.base / "original")
        storage_health.reconcile()
        mounts = json.loads(storage.OVERRIDE.read_text())["services"]["api"]["volumes"]
        self.assertEqual(len(mounts), 1)


if __name__ == "__main__":
    unittest.main()
