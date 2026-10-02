import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import storage_permissions as permissions


@unittest.skipUnless(
    shutil.which("getfacl") and shutil.which("setfacl"), "Linux ACL tools required"
)
class PermissionPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "files"
        self.root.mkdir(mode=0o755)

    def acl(self, path):
        return subprocess.check_output(["getfacl", "-cpn", str(path)], text=True)

    def test_existing_755_directory_and_content_are_prepared_without_expanding_other_grants(self):
        file = self.root / "document"
        file.write_bytes(b"preserve-content")
        file.chmod(0o600)
        subprocess.run(["setfacl", "-m", "u:62001:rwx,m::r-x", str(self.root)], check=True)
        before = self.root.stat().st_ino
        permissions.prepare(self.root, 62000, False, self.base / "acl.jsonl")
        acl = permissions.entries(self.acl(self.root))
        self.assertEqual(acl["user:62000"], 7)
        self.assertEqual(acl["user:62001"], 5)
        self.assertEqual(acl["default:user:62000"], 7)
        self.assertEqual(permissions.entries(self.acl(file))["user:62000"], 6)
        self.assertEqual(file.read_bytes(), b"preserve-content")
        self.assertEqual(self.root.stat().st_ino, before)
        after = self.acl(self.root)
        permissions.prepare(self.root, 62000, False, self.base / "acl.jsonl")
        self.assertEqual(self.acl(self.root), after)

    def test_symlinks_and_hard_links_reject_before_acl_mutation(self):
        (self.root / "link").symlink_to(self.base)
        before = self.acl(self.root)
        with self.assertRaises(OSError):
            permissions.prepare(self.root, 62000, False, self.base / "acl.jsonl")
        self.assertEqual(self.acl(self.root), before)
        (self.root / "link").unlink()
        (self.root / "body").write_text("keep")
        os.link(self.root / "body", self.root / "hardlink")
        with self.assertRaises(ValueError):
            permissions.prepare(self.root, 62000, False, self.base / "acl.jsonl")
        self.assertEqual(self.acl(self.root), before)

    def test_read_only_preparation_never_adds_write_to_the_api(self):
        permissions.prepare(self.root, 62000, True, self.base / "acl.jsonl")
        self.assertEqual(permissions.entries(self.acl(self.root))["user:62000"], 5)
