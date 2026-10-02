import json
import os
import subprocess
import time
import unittest
from pathlib import Path

import controller
import runtime


@unittest.skipUnless(os.environ.get("ARK_TEST_RUNTIME_SMOKE") == "1", "requires disposable volumes")
class RuntimeSmokeTests(unittest.TestCase):
    def test_offline_start_delayed_token_rotation_and_secret_free_shutdown(self):
        token = "runtime_test_token_-123"
        controller.TOKEN.unlink(missing_ok=True)
        process = subprocess.Popen(
            ["python3", runtime.__file__], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        def wait_for(predicate):
            for _ in range(100):
                if predicate():
                    return
                self.assertIsNone(process.poll())
                time.sleep(0.1)
            self.fail("Runtime did not reach expected state")

        def healthy():
            subprocess.run(
                ["python3", str(Path(runtime.__file__).with_name("healthcheck.py"))],
                check=True,
            )

        try:
            wait_for(lambda: Path("/tmp/controller-heartbeat").exists())
            self.assertFalse(runtime.GATEWAY_READY.exists())
            self.assertFalse(runtime.GATEWAY_CONFIG.exists())
            healthy()
            controller.TOKEN.write_text("invalid;directive")
            time.sleep(5.2)
            self.assertFalse(runtime.GATEWAY_READY.exists())
            healthy()
            controller.TOKEN.write_text(token)
            wait_for(runtime.GATEWAY_READY.exists)
            time.sleep(0.2)
            healthy()
            self.assertIn(token, runtime.GATEWAY_CONFIG.read_text())
            self.assertEqual(runtime.GATEWAY_CONFIG.stat().st_mode & 0o777, 0o600)
            status = json.loads(
                subprocess.check_output(
                    ["tailscale", f"--socket={controller.SOCKET}", "status", "--json"]
                )
            )
            self.assertEqual(status["BackendState"], "NeedsLogin")
            self.assertIs(status["TUN"], False)
            controller.TOKEN.write_text("rotated_runtime_token")
            wait_for(lambda: "rotated_runtime_token" in runtime.GATEWAY_CONFIG.read_text())
            time.sleep(0.2)
            healthy()
        finally:
            process.terminate()
            output, errors = process.communicate(timeout=35)
            self.assertEqual(process.returncode, 0)
            self.assertNotIn(token.encode(), output + errors)
            self.assertNotIn(b"rotated_runtime_token", output + errors)
            self.assertEqual(output + errors, b"")


if __name__ == "__main__":
    unittest.main()
