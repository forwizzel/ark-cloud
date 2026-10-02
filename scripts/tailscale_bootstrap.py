"""One-shot volume ownership initializer, run as root in the API image."""

import os
import pwd
from pathlib import Path


def initialize(api_uid: int, api_gid: int) -> None:
    # The shared directory's setgid bit gives API-created tokens the controller
    # group. The API must create controller-token with mode 0640 (not 0600).
    for name, uid, gid, mode in (
        ("/run/ark-secrets", api_uid, api_gid, 0o700),
        ("/run/ark-tailscale", api_uid, 10001, 0o2770),
        ("/var/lib/tailscale", 10001, 10001, 0o700),
    ):
        path = Path(name)
        path.mkdir(exist_ok=True)
        os.chown(path, uid, gid)
        os.chmod(path, mode)


if __name__ == "__main__":
    account = pwd.getpwnam("arkcloud")
    initialize(account.pw_uid, account.pw_gid)
