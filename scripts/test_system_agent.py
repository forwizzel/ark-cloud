import os
import select
import tempfile
import time
import unittest
from unittest.mock import patch

import psutil
from system_agent import execute, validate_config
from system_collect import Collector, sensor_group
from system_terminal import HostTerminal


class SystemAgentTests(unittest.TestCase):
    def test_loopback_and_account_binding(self):
        validate_config({"url": "ws://127.0.0.1:5173/api/system-agent/connect", "uid": os.getuid()})
        with self.assertRaises(ValueError):
            validate_config(
                {"url": "ws://remote.example/api/system-agent/connect", "uid": os.getuid()}
            )

    def test_process_identity_and_service_allowlist(self):
        config = {"policy": {"processes": True, "services": [], "power": False}}
        with self.assertRaises(ValueError):
            execute(
                {
                    "action": "service",
                    "unit": "unapproved.service",
                    "scope": "user",
                    "operation": "restart",
                },
                config,
                set(),
            )
        with self.assertRaises(ValueError):
            execute(
                {"action": "terminate", "pid": os.getpid(), "started_at": 0}, config, {os.getpid()}
            )
        with self.assertRaises(ValueError):
            execute({"action": "terminate", "pid": os.getpid(), "started_at": 0}, config, set())

    def test_sensor_groups_and_partial_collection(self):
        self.assertEqual(sensor_group("nvme", "Composite"), "storage")
        self.assertEqual(sensor_group("jc42", ""), "memory")
        collector = Collector()
        with patch("system_collect.psutil.sensors_temperatures", side_effect=psutil.AccessDenied()):
            value = collector.collect({"processes": False, "services": []})
        self.assertEqual(value["scope"], "host")
        self.assertTrue(value["identity"]["hostname"])
        self.assertIsNone(value["compute"]["percent"])
        self.assertEqual(value["temperatures"], [])
        self.assertIn("Temperature sensors could not be read.", value["warnings"])

    def test_real_shell_resize_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = HostTerminal("/bin/bash", directory)
            try:
                terminal.resize(90, 30)
                os.write(terminal.fd, b"printf 'ARK_PTY_OK'; stty size\n")
                output = b""
                deadline = time.monotonic() + 5
                while b"30 90" not in output and time.monotonic() < deadline:
                    if select.select([terminal.fd], [], [], 0.1)[0]:
                        output += os.read(terminal.fd, 8192)
                self.assertIn(b"ARK_PTY_OK", output)
                self.assertIn(b"30 90", output)
            finally:
                terminal.close()
            self.assertFalse(psutil.pid_exists(terminal.pid))
            terminal.close()

    def test_identity_is_detected_on_other_linux_distributions(self):
        for hostname, distribution, kernel in (
            ("backup-node", "Ubuntu 24.04 LTS", "6.8.0-generic"),
            ("nas", "Debian GNU/Linux 13", "6.12.0-amd64"),
        ):
            with self.subTest(distribution=distribution):
                with (
                    patch("system_collect.socket.gethostname", return_value=hostname),
                    patch(
                        "system_collect.platform.freedesktop_os_release",
                        return_value={"PRETTY_NAME": distribution},
                    ),
                    patch("system_collect.platform.release", return_value=kernel),
                ):
                    value = Collector().collect({"processes": False, "services": []})
                self.assertEqual(value["identity"]["hostname"], hostname)
                self.assertEqual(value["identity"]["os"], distribution)
                self.assertEqual(value["identity"]["kernel"], kernel)

    def test_distribution_name_falls_back_to_name_then_linux(self):
        for release, expected in (
            ({"NAME": "Alpine Linux"}, "Alpine Linux"),
            ({"PRETTY_NAME": "   ", "NAME": "Debian"}, "Debian"),
            ({}, "Linux"),
        ):
            with self.subTest(release=release):
                with patch("system_collect.platform.freedesktop_os_release", return_value=release):
                    value = Collector().collect({"processes": False, "services": []})
                self.assertEqual(value["identity"]["os"], expected)

    def test_missing_distribution_metadata_keeps_host_readings_available(self):
        with patch(
            "system_collect.platform.freedesktop_os_release", side_effect=OSError("No os-release")
        ):
            value = Collector().collect({"processes": False, "services": []})
        self.assertEqual(value["identity"]["os"], "Linux")
        self.assertTrue(value["identity"]["hostname"])
        self.assertTrue(value["identity"]["kernel"])
        self.assertIn("Distribution metadata is unavailable; showing Linux.", value["warnings"])


if __name__ == "__main__":
    unittest.main()
