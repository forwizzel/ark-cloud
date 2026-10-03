#!/usr/bin/env python3
"""Owner-enrolled System host service. No inbound listener or container privileges."""

import argparse
import asyncio
import base64
import json
import os
import pwd
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
STATE = ROOT / ".ark-system"
CONFIG = STATE / "agent.json"
PYTHON = STATE / "venv/bin/python"
MAX_INPUT = 32768


def atomic(path, value):
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def compose(*args, input=None):
    command = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
    if (ROOT / "compose.storage.yaml").exists():
        command += ["-f", str(ROOT / "compose.storage.yaml")]
    result = subprocess.run(
        command + list(args),
        cwd=ROOT,
        input=input,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "ARK_BIND_ADDRESS": "127.0.0.1"},
    )
    if result.returncode:
        raise ValueError("Compose operation failed. Check the running stack and migrations.")
    return result.stdout.strip()


def install_service():
    directory = Path.home() / ".config/systemd/user"
    directory.mkdir(parents=True, exist_ok=True)

    def quote(value):
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'

    unit = (
        "[Unit]\nDescription=Ark Cloud System agent\nAfter=default.target\n\n"
        "[Service]\nType=simple\nExecStart="
        + quote(PYTHON)
        + " "
        + quote(Path(__file__).resolve())
        + " run\nRestart=on-failure\nRestartSec=5\nUMask=0077\nKillMode=control-group\n"
        "\n[Install]\nWantedBy=default.target\n"
    )
    (directory / "ark-system-agent.service").write_text(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", "ark-system-agent.service"], check=True
    )
    subprocess.run(["systemctl", "--user", "restart", "ark-system-agent.service"], check=True)


def enroll(args, *, service_policy=None, announce=True):
    if sys.platform != "linux" or os.getuid() == 0:
        raise ValueError(
            "Enroll as the Linux host account that will own terminal sessions, not root."
        )
    shell = str(Path(args.shell or pwd.getpwuid(os.getuid()).pw_shell).resolve())
    if not Path(shell).is_file() or not os.access(shell, os.X_OK):
        raise ValueError("Choose an installed executable shell.")
    directory = str(Path(args.directory or Path.home()).resolve())
    if not Path(directory).is_dir():
        raise ValueError("The terminal starting directory must exist.")
    services = []
    for value in args.service:
        scope, separator, unit = value.partition(":")
        if (
            not separator
            or scope not in {"user", "system"}
            or not re.fullmatch(r"[a-zA-Z0-9_.@:-]+\.service", unit)
        ):
            raise ValueError("Services use user:NAME.service or system:NAME.service.")
        services.append({"scope": scope, "unit": unit, "actions": ["start", "stop", "restart"]})
    if len(services) > 32:
        raise ValueError("Enroll at most 32 selected services.")
    if service_policy is not None:
        services = service_policy
    STATE.mkdir(mode=0o700, exist_ok=True)
    os.chmod(STATE, 0o700)
    if not PYTHON.exists():
        subprocess.run([sys.executable, "-m", "venv", str(STATE / "venv")], check=True, timeout=60)
    installed = subprocess.run(
        [
            str(PYTHON),
            "-c",
            "from importlib.metadata import version; assert version('psutil') == '7.2.2'; "
            "assert version('websockets') == '16.0'",
        ],
        capture_output=True,
        timeout=15,
    )
    if installed.returncode:
        subprocess.run(
            [
                str(PYTHON),
                "-m",
                "pip",
                "--disable-pip-version-check",
                "install",
                "--no-input",
                "psutil==7.2.2",
                "websockets==16.0",
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
    port = int(compose("port", "web", "5173").rsplit(":", 1)[1])
    policy = {
        "terminal": args.terminal,
        "power": args.power,
        "processes": getattr(args, "processes", True),
        "shell": shell,
        "account": pwd.getpwuid(os.getuid()).pw_name,
        "services": services,
    }
    config = {
        "token": secrets.token_urlsafe(48),
        "url": f"ws://127.0.0.1:{port}/api/system-agent/connect",
        "policy": policy,
        "directory": directory,
        "uid": os.getuid(),
    }
    compose(
        "exec",
        "-T",
        "api",
        "python",
        "-m",
        "app.services.system_agent_cli",
        input=json.dumps({"token": config["token"], "policy": policy}),
    )
    atomic(CONFIG, config)
    if args.install:
        install_service()
    if announce:
        print("System agent enrolled. Manage its connection in Administration → System.")


def validate_config(config):
    url = urlsplit(config["url"])
    if url.scheme != "ws" or url.hostname != "127.0.0.1" or url.path != "/api/system-agent/connect":
        raise ValueError("The agent must connect to ArkCloud's loopback web endpoint.")
    if config["uid"] != os.getuid():
        raise ValueError("Run the agent as its enrolled host account.")


def execute(payload, config, protected):
    import psutil

    policy = config["policy"]
    action = payload["action"]
    if action == "terminate":
        if not policy["processes"] or payload["pid"] in protected or payload["pid"] <= 1:
            raise ValueError("This process is protected.")
        process = psutil.Process(payload["pid"])
        if process.create_time() != payload["started_at"]:
            raise ValueError("Process identity changed. Refresh the list.")
        if hasattr(os, "pidfd_open"):
            import signal

            fd = os.pidfd_open(process.pid)
            try:
                if process.create_time() != payload["started_at"]:
                    raise ValueError("Process identity changed. Refresh the list.")
                signal.pidfd_send_signal(fd, signal.SIGTERM)
            finally:
                os.close(fd)
        else:
            process.terminate()
        return "Termination requested."
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise ValueError("systemctl is not installed.")
    if action == "service":
        if not any(
            s["unit"] == payload["unit"]
            and s["scope"] == payload["scope"]
            and payload["operation"] in s["actions"]
            for s in policy["services"]
        ):
            raise ValueError("This service action is not enrolled.")
        command = [
            systemctl,
            *(["--user"] if payload["scope"] == "user" else []),
            "--no-ask-password",
            payload["operation"],
            payload["unit"],
        ]
        if payload["scope"] == "system":
            command = ["sudo", "-n", *command]
    elif action in {"restart", "shutdown"} and policy["power"]:
        command = [
            "sudo",
            "-n",
            systemctl,
            "--no-ask-password",
            "reboot" if action == "restart" else "poweroff",
        ]
    else:
        raise ValueError("This host operation is not enabled.")
    result = subprocess.run(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20
    )
    if result.returncode:
        raise ValueError(
            "Host authorization or operation failed. Review the enrolled unit and host privileges."
        )
    return (
        "Request accepted; host disconnection is expected."
        if action in {"restart", "shutdown"}
        else "Service operation completed."
    )


async def connection(config):
    from system_capabilities import capabilities
    from system_collect import text
    from system_terminal import HostTerminal
    from websockets.asyncio.client import connect

    validate_config(config)
    terminals, readers = {}, {}
    outbound = asyncio.Queue(maxsize=64)
    effective = await asyncio.to_thread(capabilities, config["policy"])
    async with connect(
        config["url"],
        additional_headers={"Authorization": "Bearer " + config["token"]},
        max_size=65536,
        max_queue=16,
        proxy=None,
        open_timeout=10,
    ) as ws:
        journal = sqlite3.connect(STATE / "jobs.sqlite")
        journal.execute(
            "CREATE TABLE IF NOT EXISTS jobs "
            "(id TEXT PRIMARY KEY, state TEXT, message TEXT, created REAL)"
        )
        journal.execute("DELETE FROM jobs WHERE created < ?", (time.time() - 30 * 86400,))
        journal.commit()
        sampler = await asyncio.create_subprocess_exec(
            sys.executable,
            str(ROOT / "scripts/system_collect.py"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=2_000_000,
        )
        sampler.stdin.write((json.dumps(effective) + "\n").encode())
        await sampler.stdin.drain()
        sampler.stdin.close()

        async def writer():
            while True:
                await asyncio.wait_for(ws.send(json.dumps(await outbound.get())), 10)

        async def snapshots():
            while True:
                line = await asyncio.wait_for(sampler.stdout.readline(), timeout=12)
                if not line:
                    raise ValueError("Host collector exited")
                snapshot = json.loads(line)
                snapshot["capabilities"] = effective
                await outbound.put({"type": "snapshot", "snapshot": snapshot})

        async def terminal_output(identifier):
            terminal = terminals[identifier]
            loop = asyncio.get_running_loop()
            try:
                while True:
                    future = loop.create_future()

                    def ready(future=future):
                        if not future.done():
                            future.set_result(None)

                    loop.add_reader(terminal.fd, ready)
                    try:
                        await future
                        data = os.read(terminal.fd, 8192)
                    finally:
                        loop.remove_reader(terminal.fd)
                    if not data:
                        break
                    await outbound.put(
                        {
                            "type": "terminal_output",
                            "id": identifier,
                            "data": base64.b64encode(data).decode(),
                        }
                    )
            except OSError:
                pass
            finally:
                terminal.close()
                terminals.pop(identifier, None)
                readers.pop(identifier, None)
            await outbound.put({"type": "terminal_exit", "id": identifier})

        job_tasks = {}

        async def perform_job(frame):
            identifier = frame["id"]
            previous = journal.execute(
                "SELECT state, message FROM jobs WHERE id=?", (identifier,)
            ).fetchone()
            if previous:
                state, message = previous
            elif datetime.fromisoformat(frame["deadline"]) <= datetime.now(UTC):
                state, message = "expired", "Operation expired before host execution."
            elif frame["boot_id"] != text("/proc/sys/kernel/random/boot_id", 64):
                state, message = "expired", "Host boot identity changed."
            else:
                # Commit before execution: a crash must not cause automatic replay.
                journal.execute(
                    "INSERT INTO jobs VALUES (?, 'unknown', 'Execution outcome is unknown.', ?)",
                    (identifier, time.time()),
                )
                journal.commit()
                try:
                    protected = {os.getpid(), sampler.pid, *[t.pid for t in terminals.values()]}
                    import psutil

                    with suppress(psutil.Error):
                        protected.update(
                            p.pid for p in psutil.Process(os.getpid()).children(recursive=True)
                        )
                    for terminal in terminals.values():
                        with suppress(psutil.Error):
                            protected.update(
                                p.pid for p in psutil.Process(terminal.pid).children(recursive=True)
                            )
                    message = await asyncio.to_thread(execute, frame["payload"], config, protected)
                    state = (
                        "unknown"
                        if frame["payload"]["action"] in {"restart", "shutdown"}
                        else "succeeded"
                    )
                except (OSError, ValueError, subprocess.SubprocessError, psutil.Error):
                    state, message = (
                        "failed",
                        "Operation failed or permission denied. "
                        "Check host authorization and refresh the target.",
                    )
                journal.execute(
                    "UPDATE jobs SET state=?, message=? WHERE id=?", (state, message, identifier)
                )
                journal.commit()
            await outbound.put(
                {"type": "job_result", "id": identifier, "state": state, "message": message}
            )

        async def receive():
            async for raw in ws:
                frame = json.loads(raw)
                kind, identifier = frame["type"], frame["id"]
                if kind == "job":
                    if identifier in job_tasks and not job_tasks[identifier].done():
                        continue
                    for key in list(job_tasks):
                        if job_tasks[key].done():
                            job_tasks.pop(key).result()
                    if len([task for task in job_tasks.values() if not task.done()]) >= 16:
                        await outbound.put(
                            {
                                "type": "job_result",
                                "id": identifier,
                                "state": "failed",
                                "message": "Host action queue is full. Try again shortly.",
                            }
                        )
                        continue
                    job_tasks[identifier] = asyncio.create_task(perform_job(frame))
                elif kind == "terminal_start":
                    if (
                        not config["policy"]["terminal"]
                        or len([t for t in terminals.values() if not t.closed]) >= 8
                    ):
                        await outbound.put({"type": "terminal_exit", "id": identifier})
                        continue
                    terminals[identifier] = HostTerminal(
                        config["policy"]["shell"], config["directory"]
                    )
                    readers[identifier] = asyncio.create_task(terminal_output(identifier))
                elif identifier in terminals:
                    terminal = terminals[identifier]
                    if kind == "terminal_end":
                        readers[identifier].cancel()
                        terminal.close()
                        terminals.pop(identifier, None)
                    elif kind == "terminal_resize" and not terminal.closed:
                        terminal.resize(int(frame["cols"]), int(frame["rows"]))
                    elif kind == "terminal_input" and not terminal.closed:
                        data = base64.b64decode(frame["data"], validate=True)
                        if len(data) > MAX_INPUT:
                            raise ValueError("Input too large")
                        # Write without blocking telemetry or dropping partial writes.
                        while data:
                            try:
                                count = os.write(terminal.fd, data)
                                data = data[count:]
                            except BlockingIOError:
                                await asyncio.sleep(0.01)

        tasks = [
            asyncio.create_task(writer()),
            asyncio.create_task(snapshots()),
            asyncio.create_task(receive()),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in [*tasks, *readers.values(), *job_tasks.values()]:
                task.cancel()
            await asyncio.gather(
                *tasks, *readers.values(), *job_tasks.values(), return_exceptions=True
            )
            for terminal in terminals.values():
                terminal.close()
            journal.close()
            with suppress(ProcessLookupError):
                sampler.kill()
            await sampler.wait()


async def run():
    import fcntl

    from websockets.exceptions import WebSocketException

    lock = (STATE / "agent.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    while True:
        try:
            config = json.loads(CONFIG.read_text())
            await connection(config)
        except (OSError, ValueError, WebSocketException, TimeoutError):
            print(
                "System agent disconnected; retrying in five seconds.", file=sys.stderr, flush=True
            )
        await asyncio.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    enrollment = sub.add_parser("enroll")
    enrollment.add_argument("--terminal", action="store_true")
    enrollment.add_argument("--power", action="store_true")
    enrollment.add_argument("--service", action="append", default=[])
    enrollment.add_argument("--shell")
    enrollment.add_argument("--directory")
    enrollment.add_argument("--install", action="store_true")
    for name in ("run", "status", "check", "revoke"):
        sub.add_parser(name)
    args = parser.parse_args()
    if args.command == "enroll":
        enroll(args)
    elif args.command == "run":
        if Path(sys.executable).absolute() != PYTHON.absolute():
            os.execv(str(PYTHON), [str(PYTHON), str(Path(__file__).resolve()), "run"])
        os.umask(0o077)
        asyncio.run(run())
    elif args.command == "revoke":
        compose(
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "app.services.system_agent_cli",
            input=json.dumps({"token": "", "policy": {}}),
        )
        print("System agent credential revoked. Re-enroll to reconnect.")
    else:
        config = json.loads(CONFIG.read_text())
        validate_config(config)
        print(
            f"Enrolled account: {config['policy']['account']}; shell: {config['policy']['shell']}"
        )
        subprocess.run(
            ["systemctl", "--user", "is-active", "ark-system-agent.service"], check=False
        )
        if args.command == "check":
            subprocess.run(
                [
                    str(PYTHON),
                    "-c",
                    "import psutil, websockets; print('Host dependencies available.')",
                ],
                check=True,
            )
            print(
                "Inspect System in ArkCloud for connection, readings "
                "and effective operation results."
            )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"ark system: {error}")
