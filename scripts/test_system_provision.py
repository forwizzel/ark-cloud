import contextlib
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import system_provision as provision

INVENTORY = {
    "supported": True,
    "account": "owner",
    "default_shell": "/bin/bash",
    "shells": ["/bin/bash"],
    "power": False,
    "services": [{"unit": "backup.service", "scope": "user", "actions": ["restart"]}],
}
CONFIGURATION = {
    "terminal": True,
    "processes": False,
    "power": False,
    "shell": "",
    "services": INVENTORY["services"],
}
JOB = {"id": "fixture-job", "payload": {"action": "connect", "configuration": CONFIGURATION}}


class ProvisionTests(unittest.TestCase):
    def test_enrollment_uses_host_shell_and_preserves_granular_actions(self):
        with patch.object(provision.system_agent, "enroll") as enroll:
            provision.execute(JOB, INVENTORY)
        args = enroll.call_args.args[0]
        self.assertEqual(args.shell, "/bin/bash")
        self.assertFalse(args.processes)
        self.assertTrue(args.install)
        self.assertEqual(enroll.call_args.kwargs["service_policy"], INVENTORY["services"])
        self.assertFalse(enroll.call_args.kwargs["announce"])

    def test_unapproved_shell_power_and_service_are_rejected(self):
        for change in (
            {"shell": "/arbitrary/shell"},
            {"power": True},
            {"services": [{"unit": "bad.service", "scope": "user", "actions": ["stop"]}]},
        ):
            with (
                self.subTest(change=change),
                patch.object(provision.system_agent, "enroll") as enroll,
            ):
                with self.assertRaises(ValueError):
                    provision.execute(
                        {
                            "payload": {
                                "action": "connect",
                                "configuration": {**CONFIGURATION, **change},
                            }
                        },
                        INVENTORY,
                    )
                enroll.assert_not_called()

    def test_verification_retry_does_not_reinstall_or_rotate_credentials(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(provision, "JOURNAL", Path(directory) / "journal.json"),
            patch.object(provision, "inventory", return_value=INVENTORY),
            patch.object(
                provision.storage, "configuration_lock", side_effect=contextlib.nullcontext
            ),
            patch.object(provision, "execute") as execute,
        ):
            completed = False
            states = []

            def api(config, route, body=None):
                if route == "work":
                    return {"job": JOB}
                if body.get("state") == "completed" and not completed:
                    raise urllib.error.HTTPError(
                        "http://127.0.0.1", 409, "Waiting for readings", {}, None
                    )
                if body.get("state"):
                    states.append(body["state"])
                return {"accepted": True}

            with patch.object(provision, "api", side_effect=api):
                provision.cycle({})
                self.assertEqual(json.loads(provision.JOURNAL.read_text())["phase"], "verify")
                completed = True
                provision.cycle({})
            execute.assert_called_once()
            self.assertEqual(states, ["applying", "verifying", "completed"])
            self.assertFalse(provision.JOURNAL.exists())

    def test_refused_claim_never_touches_host_configuration(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(provision, "JOURNAL", Path(directory) / "journal.json"),
            patch.object(provision, "inventory", return_value=INVENTORY),
            patch.object(provision, "execute") as execute,
        ):

            def api(config, route, body=None):
                return {"job": JOB} if route == "work" else {"accepted": not body.get("job_id")}

            with patch.object(provision, "api", side_effect=api):
                provision.cycle({})
            execute.assert_not_called()
            self.assertFalse(provision.JOURNAL.exists())


if __name__ == "__main__":
    unittest.main()
