"""Fixed-command, credential-isolated Tailscale reconciliation."""

import json
import re
import subprocess
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SOCKET = "/tmp/tailscaled.sock"
TARGET = "http://127.0.0.1:8080"
API = "http://api:8000/admin/tailscale/controller"
TOKEN = Path("/run/ark-tailscale/controller-token")
UNAUTHENTICATED = {"NeedsLogin", "NoState"}
MAX_CLI_OUTPUT = 1024 * 1024


class ControllerError(Exception):
    """Deliberately carries no upstream output or credentials."""


def command(*args, timeout=15):
    process = subprocess.Popen(
        ["tailscale", f"--socket={SOCKET}", *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    chunks = []
    overflow = threading.Event()

    def collect():
        size = 0
        while True:
            try:
                chunk = process.stdout.read1(65536)
            except (OSError, ValueError):
                overflow.set()
                with suppress(OSError):
                    process.terminate()
                return
            if not chunk:
                return
            size += len(chunk)
            if size > MAX_CLI_OUTPUT:
                overflow.set()
                with suppress(OSError):
                    process.terminate()
                return
            chunks.append(chunk)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Serve can wait indefinitely for HTTPS approval. Preserve its output
        # for URL extraction, but always cancel and reap the CLI process.
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        timed_out = True
    reader.join(timeout=2)
    if reader.is_alive() or overflow.is_set():
        # Never parse truncated output as a successful status or approval URL.
        if not reader.is_alive():
            process.stdout.close()
        return -2, ""
    process.stdout.close()
    output = b"".join(chunks).decode("utf-8", errors="replace")
    return -1 if timed_out else process.returncode, output


def json_command(*args):
    code, output = command(*args)
    if code:
        raise ControllerError()
    try:
        result = json.loads(output)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ControllerError() from None


def approval_url(output):
    for candidate in re.findall(r"https://[^\s<>\"']+", output):
        candidate = candidate.rstrip(".,);]")
        try:
            url = urlsplit(candidate)
            if (
                url.scheme == "https"
                and url.netloc in {"login.tailscale.com", "console.tailscale.com"}
                and url.path.startswith(("/a/", "/f/", "/admin/"))
                and not url.fragment
            ):
                return urlunsplit(url)
        except ValueError:
            pass
    return None


def identity(status):
    node = status.get("Self") or {}
    dns = node.get("DNSName", "").rstrip(".")
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net", dns):
        dns = None
    node_id = node.get("ID") or None
    return node_id if isinstance(node_id, str) else None, dns


def managed_handler(config, dns):
    return config.get("Web", {}).get(f"{dns}:443", {}).get("Handlers", {}).get("/")


def serving(config, dns):
    return bool(
        dns
        and config.get("TCP", {}).get("443", {}).get("HTTPS") is True
        and managed_handler(config, dns) == {"Proxy": TARGET}
        and not config.get("AllowFunnel", {}).get(f"{dns}:443", False)
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_token():
    token = TOKEN.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,4096}", token):
        raise ControllerError()
    return token


def api_request(path, payload=None):
    token = read_token()
    request = Request(
        API + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with build_opener(NoRedirect()).open(request, timeout=5) as response:
        data = response.read(65537)
        if len(data) > 65536:
            raise ControllerError()
        return json.loads(data) if data else None


class Controller:
    def __init__(self):
        self.disconnected = False

    def reconcile(self, work, status):
        revision = work.get("revision")
        if type(revision) is not int or revision < 0:
            raise ControllerError()
        report = dict(
            revision=revision,
            state="error",
            message="Tailscale operation failed.",
            node_id=None,
            dns_name=None,
            serve_url=None,
            approval_url=None,
        )

        def finish(state, message, current=status, url=None):
            report.update(state=state, message=message)
            report["node_id"], report["dns_name"] = identity(current)
            report["approval_url"] = url
            if state == "connected":
                report["serve_url"] = f"https://{report['dns_name']}"
            return report

        try:
            if (
                type(work.get("desired_enabled")) is not bool
                or type(work.get("disconnect")) is not bool
            ):
                raise ControllerError()
            backend = status.get("BackendState")
            _, dns = identity(status)
            config = json_command("serve", "status", "--json")
            if work["disconnect"] or not work["desired_enabled"] or self.disconnected:
                if managed_handler(config, dns) == {"Proxy": TARGET}:
                    code, _ = command(
                        "serve", "--bg", "--yes", "--https=443", "--set-path=/", "off"
                    )
                    if code:
                        raise ControllerError()
                    remaining = json_command("serve", "status", "--json")
                    if managed_handler(remaining, dns) == {"Proxy": TARGET}:
                        raise ControllerError()
                if work["disconnect"]:
                    if backend not in UNAUTHENTICATED:
                        code, _ = command("logout")
                        if code:
                            raise ControllerError()
                    self.disconnected = True
                    return finish("disconnected", "Node disconnected.", {})
                if not work["desired_enabled"]:
                    return finish("disabled", "Remote access disabled.")
                # A subsequent explicit enabled desire may reconnect only with
                # new credentials; a stale enabled poll must not undo logout.
                if not work.get("auth_key"):
                    return finish("disconnected", "Node disconnected.", {})
                self.disconnected = False

            hostname = work.get("hostname", "arkcloud")
            if not isinstance(hostname, str) or not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", hostname
            ):
                raise ControllerError()
            if backend in UNAUTHENTICATED:
                key = work.get("auth_key")
                if not key:
                    return finish("offline", "Waiting for node authentication.")
                if not isinstance(key, str) or len(key) > 4096 or "\n" in key:
                    raise ControllerError()
                # Never put the auth key in argv or daemon environment.
                with tempfile.NamedTemporaryFile(dir="/tmp", mode="w") as secret:
                    secret.write(key)
                    secret.flush()
                    code, output = command(
                        "up",
                        f"--auth-key=file:{secret.name}",
                        f"--hostname={hostname}",
                        "--accept-dns=false",
                        "--accept-routes=false",
                        "--timeout=10s",
                    )
                status = json_command("status", "--json")
                if code and status.get("BackendState") in UNAUTHENTICATED:
                    return finish("error", "Node authentication failed.", status)
            elif backend == "Stopped":
                code, _ = command(
                    "up", "--accept-dns=false", "--accept-routes=false", "--timeout=10s"
                )
                if code:
                    raise ControllerError()
                status = json_command("status", "--json")
            if status.get("BackendState") != "Running":
                url = approval_url(status.get("AuthURL", ""))
                return finish(
                    "approval_required" if url else "connecting",
                    "Waiting for node readiness.",
                    status,
                    url,
                )
            _, dns = identity(status)
            if not serving(config, dns):
                code, output = command(
                    "serve", "--bg", "--yes", "--https=443", "--set-path=/", TARGET
                )
                url = approval_url(output)
                if url:
                    return finish(
                        "approval_required", "Approve HTTPS access in Tailscale.", status, url
                    )
                if code:
                    return finish(
                        "connecting" if code == -1 else "error",
                        "HTTPS service is not ready.",
                        status,
                    )
            # Re-read both: CLI success alone is not evidence of readiness.
            status = json_command("status", "--json")
            _, dns = identity(status)
            config = json_command("serve", "status", "--json")
            if status.get("BackendState") == "Running" and serving(config, dns):
                return finish("connected", "Remote access is ready.", status)
            return finish("connecting", "Waiting for HTTPS service readiness.", status)
        except (ControllerError, ValueError, TypeError, AttributeError, OSError):
            return report

    def poll(self):
        status = json_command("status", "--json")
        needs_auth = status.get("BackendState") in UNAUTHENTICATED
        work = api_request("/work?needs_auth=" + str(needs_auth).lower())
        if not isinstance(work, dict):
            raise ControllerError()
        api_request("/report", self.reconcile(work, status))
