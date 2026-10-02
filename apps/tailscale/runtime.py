"""Supervise unprivileged daemon, gateway and controller without a shell."""

import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path

from controller import SOCKET, Controller, read_token

GATEWAY_CONFIG = Path("/tmp/nginx.conf")
GATEWAY_READY = Path("/tmp/gateway-ready")
GATEWAY_TEMPLATE = Path("/etc/nginx/nginx.conf")


def render_gateway(token):
    # Validate here as well so callers can never inject nginx directives.
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,4096}", token):
        raise ValueError("Invalid controller token")
    template = GATEWAY_TEMPLATE.read_text()
    if template.count("__ARK_REMOTE_TOKEN__") != 1:
        raise ValueError("Invalid gateway template")
    with tempfile.NamedTemporaryFile(mode="w", dir=GATEWAY_CONFIG.parent, delete=False) as config:
        try:
            config.write(template.replace("__ARK_REMOTE_TOKEN__", token))
            config.flush()
            os.chmod(config.name, 0o600)
            os.replace(config.name, GATEWAY_CONFIG)
        finally:
            Path(config.name).unlink(missing_ok=True)


def start_gateway():
    # nginx parse errors can quote configuration lines containing the token.
    # Never expose nginx output, including errors from startup or reload.
    return subprocess.Popen(
        ["nginx", "-c", str(GATEWAY_CONFIG), "-e", "/dev/null", "-g", "daemon off;"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    os.umask(0o077)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    children = []
    gateway = None
    gateway_token = None
    GATEWAY_READY.unlink(missing_ok=True)
    try:
        children.append(
            subprocess.Popen(
                [
                    "tailscaled",
                    "--tun=userspace-networking",
                    "--state=/var/lib/tailscale/tailscaled.state",
                    f"--socket={SOCKET}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        controller = Controller()
        while not stop.is_set():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Controller child exited")
            # Each pass is bounded; API initialization may create or rotate the
            # token later. Stay healthy offline without starting an unsafe proxy.
            with suppress(Exception):
                token = read_token()
                if token != gateway_token:
                    render_gateway(token)
                    if gateway is None:
                        gateway = start_gateway()
                        children.append(gateway)
                        GATEWAY_READY.touch(mode=0o600)
                    else:
                        gateway.send_signal(signal.SIGHUP)
                    gateway_token = token
                # API HTTPErrors and all other upstream failures are suppressed
                # without logging their text, headers, body or credentials.
                if gateway is not None:
                    controller.poll()
            Path("/tmp/controller-heartbeat").write_text(str(time.monotonic()))
            stop.wait(5)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
