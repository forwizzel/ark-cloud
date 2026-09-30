"""Owner-tool checks: never use real data directories or Docker."""

import argparse
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import storage


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


if __name__ == "__main__":
    unittest.main()
