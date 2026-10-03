"""Read-only authorization probes. Never execute a control action to test permission."""

import copy
import shutil
import subprocess


def capabilities(policy):
    effective = copy.deepcopy(policy)
    systemctl = shutil.which("systemctl")
    sudo = shutil.which("sudo")

    def authorized(*arguments):
        if not systemctl or not sudo:
            return False
        try:
            return (
                subprocess.run(
                    [sudo, "-n", "-l", systemctl, "--no-ask-password", *arguments],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                ).returncode
                == 0
            )
        except (OSError, subprocess.SubprocessError):
            return False

    effective["power"] = bool(policy["power"] and authorized("reboot") and authorized("poweroff"))
    for service in effective["services"]:
        if not systemctl:
            service["actions"] = []
        elif service["scope"] == "system":
            service["actions"] = [
                action for action in service["actions"] if authorized(action, service["unit"])
            ]
    return effective
