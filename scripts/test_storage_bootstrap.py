import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import storage
import storage_bootstrap as bootstrap
import storage_manager as manager


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.config = self.repo / ".ark-storage"
        self.config.mkdir()
        self.area = self.base / "locations"
        for module, name, value in [
            (storage, "REPO", self.repo),
            (storage, "CONFIG", self.config),
            (storage, "STATE", self.config / "host.json"),
            (manager, "CONFIG", self.config / "manager.json"),
        ]:
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_existing_credential_and_approved_areas_are_preserved(self):
        approved = self.base / "existing"
        approved.mkdir()
        config = {
            "token": "existing-private-credential",
            "url": "http://127.0.0.1:5173",
            "approved_paths": [str(approved)],
            "identities": {str(approved): [approved.stat().st_dev, approved.stat().st_ino]},
        }
        storage.atomic_write(manager.CONFIG, json.dumps(config))
        with (
            patch.dict(os.environ, {"ARK_STORAGE_MANAGED_AREA": str(self.area)}),
            patch.object(bootstrap.shutil, "which", return_value="tool"),
            patch.object(bootstrap.subprocess, "run"),
            patch.object(manager, "api"),
            patch.object(manager, "install_service"),
            patch.object(manager, "enroll") as enroll,
        ):
            bootstrap.ensure()
            bootstrap.ensure()
        enroll.assert_not_called()
        result = json.loads(manager.CONFIG.read_text())
        self.assertEqual(result["token"], config["token"])
        self.assertEqual(set(result["approved_paths"]), {str(approved), str(self.area)})
        self.assertEqual(result["managed_area"], str(self.area))

    def test_unowned_existing_area_is_never_adopted(self):
        self.area.mkdir()
        with (
            patch.dict(os.environ, {"ARK_STORAGE_MANAGED_AREA": str(self.area)}),
            patch.object(bootstrap.shutil, "which", return_value="tool"),
            patch.object(bootstrap.subprocess, "run"),
            self.assertRaisesRegex(ValueError, "already exists"),
        ):
            bootstrap.ensure()
        self.assertFalse(manager.CONFIG.exists())

    def test_missing_managed_area_preserves_identity_and_starts_existing_manager(self):
        self.area.mkdir()
        info = self.area.stat()
        identity = [info.st_dev, info.st_ino]
        storage.atomic_write(
            self.config / "managed-area.json",
            json.dumps(
                {
                    "path": str(self.area),
                    "device": info.st_dev,
                    "inode": info.st_ino,
                }
            ),
        )
        config = {
            "token": "existing",
            "url": "http://127.0.0.1:5173",
            "approved_paths": [str(self.area)],
            "identities": {str(self.area): identity},
        }
        storage.atomic_write(manager.CONFIG, json.dumps(config))
        self.area.rmdir()
        with (
            patch.dict(os.environ, {"ARK_STORAGE_MANAGED_AREA": str(self.area)}),
            patch.object(bootstrap.shutil, "which", return_value="tool"),
            patch.object(bootstrap.subprocess, "run"),
            patch.object(manager, "api"),
            patch.object(manager, "install_service") as installer,
            patch.object(manager, "enroll") as enroll,
        ):
            bootstrap.ensure()
        enroll.assert_not_called()
        installer.assert_called_once_with(start=False)
        self.assertFalse(self.area.exists())
        self.assertEqual(
            json.loads(manager.CONFIG.read_text())["identities"][str(self.area)], identity
        )

    def test_first_start_enrolls_and_installs_without_a_separate_user_command(self):
        def enrolled(args):
            config = {
                "token": "new-private-credential",
                "url": "http://127.0.0.1:5173",
                "approved_paths": args.approve,
                "identities": {
                    value: [Path(value).stat().st_dev, Path(value).stat().st_ino]
                    for value in args.approve
                },
            }
            storage.atomic_write(manager.CONFIG, json.dumps(config))

        with (
            patch.dict(os.environ, {"ARK_STORAGE_MANAGED_AREA": str(self.area)}),
            patch.object(bootstrap.shutil, "which", return_value="tool"),
            patch.object(bootstrap.subprocess, "run"),
            patch.object(manager, "api"),
            patch.object(manager, "install_service") as installer,
            patch.object(manager, "enroll", side_effect=enrolled) as enroll,
        ):
            bootstrap.ensure()
        enroll.assert_called_once()
        installer.assert_called_once_with(start=False)
        self.assertTrue(self.area.is_dir())
        self.assertTrue((self.config / "managed-area.json").exists())
