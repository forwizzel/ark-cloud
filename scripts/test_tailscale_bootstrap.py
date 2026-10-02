import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tailscale_bootstrap


class BootstrapTests(unittest.TestCase):
    def test_actual_api_identity_and_separate_volume_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = {}

            def volume(name):
                path = Path(temp) / name.rsplit("/", 1)[1]
                paths[name] = path
                return path

            with (
                patch.object(tailscale_bootstrap, "Path", side_effect=volume),
                patch.object(tailscale_bootstrap.os, "chown") as chown,
            ):
                tailscale_bootstrap.initialize(123, 456)
                token = paths["/run/ark-tailscale"] / "controller-token"
                token.write_text("existing-token")
                tailscale_bootstrap.initialize(123, 456)
            self.assertEqual(token.read_text(), "existing-token")
            self.assertEqual(paths["/run/ark-secrets"].stat().st_mode & 0o7777, 0o700)
            self.assertEqual(paths["/run/ark-tailscale"].stat().st_mode & 0o7777, 0o2770)
            self.assertEqual(paths["/var/lib/tailscale"].stat().st_mode & 0o7777, 0o700)
            owners = [call.args[1:] for call in chown.call_args_list]
            self.assertEqual(owners, [(123, 456), (123, 10001), (10001, 10001)] * 2)


if __name__ == "__main__":
    unittest.main()
