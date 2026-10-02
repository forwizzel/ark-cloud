import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

import controller as c

DNS = "arkcloud.example.ts.net"
RUNNING = {"BackendState": "Running", "Self": {"ID": "node123", "DNSName": DNS + "."}}
WORK = {"revision": 4, "desired_enabled": True, "disconnect": False, "auth_key": None}
SERVE = {
    "TCP": {"443": {"HTTPS": True}},
    "Web": {DNS + ":443": {"Handlers": {"/": {"Proxy": c.TARGET}}}},
}


class ControllerTests(unittest.TestCase):
    def reconcile(self, work=WORK, status=RUNNING, configs=None, result=(0, "")):
        def cli(*args):
            if args == ("status", "--json"):
                return status
            return next(configs)

        configs = iter(configs if configs is not None else [SERVE, SERVE])
        with (
            patch.object(c, "json_command", side_effect=cli),
            patch.object(c, "command", return_value=result) as command,
        ):
            report = c.Controller().reconcile(work, status)
        return report, command

    def test_running_node_never_reregisters_even_with_key(self):
        report, command = self.reconcile({**WORK, "auth_key": "sensitive"})
        self.assertEqual(report["state"], "connected")
        self.assertEqual(report["serve_url"], "https://" + DNS)
        self.assertEqual(report["revision"], 4)
        command.assert_not_called()

    def test_successful_serve_command_is_not_readiness(self):
        report, _ = self.reconcile(configs=[{}, {}])
        self.assertEqual(report["state"], "connecting")
        self.assertIsNone(report["serve_url"])

    def test_waiting_serve_approval(self):
        report, _ = self.reconcile(
            configs=[{}],
            result=(-1, "Enable HTTPS: https://login.tailscale.com/f/serve?node=123\nsecret"),
        )
        self.assertEqual(report["state"], "approval_required")
        self.assertEqual(report["approval_url"], "https://login.tailscale.com/f/serve?node=123")
        self.assertNotIn("secret", json.dumps(report))

    def test_untrusted_urls_rejected(self):
        for url in (
            "https://login.tailscale.com.evil/f/test",
            "https://user@login.tailscale.com/f/test",
            "http://login.tailscale.com/f/test",
            "https://console.tailscale.com:444/admin/test",
            "https://console.tailscale.com/evil",
            "https://console.tailscale.com/admin/test#secret",
        ):
            self.assertIsNone(c.approval_url(url), url)

    def test_disable_removes_only_managed_root(self):
        report, command = self.reconcile({**WORK, "desired_enabled": False}, configs=[SERVE, {}])
        self.assertEqual(report["state"], "disabled")
        command.assert_called_once_with(
            "serve", "--bg", "--yes", "--https=443", "--set-path=/", "off"
        )

    def test_disable_foreign_handler_does_not_reset(self):
        foreign = {"Web": {DNS + ":443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9000"}}}}}
        report, command = self.reconcile({**WORK, "desired_enabled": False}, configs=[foreign])
        self.assertEqual(report["state"], "disabled")
        command.assert_not_called()

    def test_failed_disable_is_not_reported_disabled(self):
        report, _ = self.reconcile(
            {**WORK, "desired_enabled": False}, configs=[SERVE], result=(1, "raw failure")
        )
        self.assertEqual(report["state"], "error")
        self.assertNotIn("raw failure", json.dumps(report))

    def test_disconnect_logs_out_once(self):
        instance = c.Controller()
        work = {**WORK, "disconnect": True}
        with (
            patch.object(c, "json_command", return_value={}),
            patch.object(c, "command", return_value=(0, "")) as command,
        ):
            self.assertEqual(instance.reconcile(work, RUNNING)["state"], "disconnected")
            for desire in (work, WORK):
                report = instance.reconcile(desire, {"BackendState": "NeedsLogin"})
                self.assertEqual(report["state"], "disconnected")
        command.assert_called_once_with("logout")

    def test_unauthenticated_without_key_stays_offline(self):
        report, command = self.reconcile(status={"BackendState": "NoState"}, configs=[{}])
        self.assertEqual(report["state"], "offline")
        command.assert_not_called()

    def test_auth_key_in_private_file_not_argv(self):
        status = {"BackendState": "NeedsLogin"}
        observed = []

        def command(*args):
            observed.append(args)
            key_arg = next(arg for arg in args if arg.startswith("--auth-key=file:"))
            path = c.Path(key_arg.removeprefix("--auth-key=file:"))
            self.assertEqual(path.read_text(), "sensitive-key")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            return 0, ""

        with (
            patch.object(c, "json_command", side_effect=[SERVE, RUNNING, RUNNING, SERVE]),
            patch.object(c, "command", side_effect=command),
        ):
            report = c.Controller().reconcile({**WORK, "auth_key": "sensitive-key"}, status)
        self.assertEqual(report["state"], "connected")
        self.assertEqual(len(observed), 1)
        self.assertFalse(c.Path(observed[0][1].removeprefix("--auth-key=file:")).exists())
        self.assertNotIn("sensitive-key", str(observed))

    def test_poll_requests_credentials_only_for_unauthenticated_node(self):
        states = (
            ("NeedsLogin", "true"),
            ("NoState", "true"),
            ("Running", "false"),
            ("Stopped", "false"),
        )
        for backend, expected in states:
            instance = c.Controller()
            with (
                patch.object(c, "json_command", return_value={"BackendState": backend}),
                patch.object(c, "api_request", return_value=WORK) as api,
                patch.object(instance, "reconcile", return_value={"revision": 4}),
            ):
                instance.poll()
            self.assertEqual(api.call_args_list[0].args, ("/work?needs_auth=" + expected,))
            self.assertEqual(api.call_args_list[1].args, ("/report", {"revision": 4}))

    def test_timeout_cancels_and_reaps_cli_preserving_approval_output(self):
        process = Mock()
        process.stdout = io.BytesIO(b"https://login.tailscale.com/f/serve")
        process.wait.side_effect = [
            subprocess.TimeoutExpired("tailscale", 15),
            -15,
        ]
        with patch.object(c.subprocess, "Popen", return_value=process):
            code, output = c.command("serve", "--bg", c.TARGET)
        self.assertEqual(code, -1)
        self.assertIsNotNone(c.approval_url(output))
        process.terminate.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_funnel_and_arbitrary_dns_never_report_connected(self):
        self.assertFalse(c.serving({**SERVE, "AllowFunnel": {DNS + ":443": True}}, DNS))
        self.assertIsNone(c.identity({"Self": {"DNSName": "evil.example/path"}})[1])

    def test_report_uses_bearer_token_and_fixed_api_endpoint(self):
        response = Mock()
        response.read.return_value = b"{}"
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        token = Mock()
        token.read_text.return_value = "controller-secret\n"
        payload = {"revision": 4, "state": "disabled"}
        with patch.object(c, "TOKEN", token), patch.object(c, "build_opener", return_value=opener):
            c.api_request("/report", payload)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, c.API + "/report")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer controller-secret")
        self.assertEqual(json.loads(request.data), payload)

    def test_cli_is_force_killed_if_cancellation_does_not_finish(self):
        process = Mock()
        process.stdout = io.BytesIO(b"")
        process.wait.side_effect = [
            subprocess.TimeoutExpired("tailscale", 15),
            subprocess.TimeoutExpired("tailscale", 2),
            -9,
        ]
        with patch.object(c.subprocess, "Popen", return_value=process):
            self.assertEqual(c.command("serve", "--bg", c.TARGET)[0], -1)
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 3)

    def test_cli_output_is_bounded_and_truncation_cannot_be_approval(self):
        process = Mock()
        process.stdout = io.BytesIO(b"https://login.tailscale.com/f/serve " + b"a" * 2000)
        process.returncode = 0
        with (
            patch.object(c.subprocess, "Popen", return_value=process),
            patch.object(c, "MAX_CLI_OUTPUT", 1024),
        ):
            self.assertEqual(c.command("serve", "--bg", c.TARGET), (-2, ""))
        process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
