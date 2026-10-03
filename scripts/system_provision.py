"""Typed System lifecycle jobs handled by the deployment's existing host manager."""

import json
import os
import pwd
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import storage
import system_agent
from system_capabilities import capabilities

JOURNAL = storage.CONFIG / "system-provision-journal.json"
UTC = timezone.utc
_inventory = None
_inventory_at = 0


def inventory(refresh=False):
    global _inventory, _inventory_at
    if _inventory is not None and not refresh and time.monotonic() - _inventory_at < 60:
        return _inventory
    account = pwd.getpwuid(os.getuid())
    shells = set()
    try:
        with open("/etc/shells", encoding="utf-8") as source:
            for line in source.read(8192).splitlines():
                path = line.strip()
                if path.startswith("/") and Path(path).is_file() and os.access(path, os.X_OK):
                    shells.add(str(Path(path).resolve()))
    except OSError:
        pass
    default = str(Path(account.pw_shell).resolve())
    if Path(default).is_file() and os.access(default, os.X_OK):
        shells.add(default)
    services = []
    started = time.monotonic()
    for scope in ("user", "system"):
        if not shutil.which("systemctl"):
            break
        try:
            result = subprocess.run(
                [
                    "systemctl",
                    *(["--user"] if scope == "user" else []),
                    "list-unit-files",
                    "--type=service",
                    "--no-legend",
                    "--no-pager",
                ],
                text=True,
                capture_output=True,
                timeout=3,
            )
            if result.returncode:
                continue
            for line in result.stdout[:65536].splitlines():
                unit = line.partition(" ")[0]
                if (
                    not re.fullmatch(r"[a-zA-Z0-9_.@:-]+\.service", unit)
                    or unit.endswith("@.service")
                    or unit in {"ark-storage-manager.service", "ark-system-agent.service"}
                ):
                    continue
                if len(services) >= 128 or time.monotonic() - started > 8:
                    break
                policy = {
                    "terminal": False,
                    "power": False,
                    "processes": True,
                    "shell": default,
                    "account": account.pw_name,
                    "services": [
                        {"unit": unit, "scope": scope, "actions": ["start", "stop", "restart"]}
                    ],
                }
                enabled = capabilities(policy)["services"][0]
                if enabled["actions"]:
                    services.append(enabled)
        except (OSError, subprocess.SubprocessError):
            continue
    power = capabilities(
        {
            "terminal": False,
            "power": True,
            "processes": True,
            "shell": default,
            "account": account.pw_name,
            "services": [],
        }
    )["power"]
    supported = bool(os.getuid() != 0 and shells and shutil.which("systemctl"))
    _inventory = {
        "supported": supported,
        "account": account.pw_name,
        "default_shell": default,
        "shells": sorted(shells)[:32],
        "services": services,
        "power": power,
        "message": ""
        if supported
        else "Host management needs an ordinary account with an installed shell "
        "and user service support.",
    }
    _inventory_at = time.monotonic()
    return _inventory


def api(config, route, body=None):
    from storage_manager import HTTP

    request = urllib.request.Request(
        config["url"] + "/api/system-manager/" + route,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + config["token"], "Content-Type": "application/json"},
    )
    with HTTP.open(request, timeout=15) as response:
        return json.load(response)


def approved(configuration, available):
    if not available["supported"]:
        raise ValueError("Host management is unavailable under this account.")
    if configuration["shell"] and configuration["shell"] not in available["shells"]:
        raise ValueError("The selected installed shell is no longer available.")
    if configuration["power"] and not available["power"]:
        raise ValueError("Host authorization for power controls is unavailable.")
    for service in configuration["services"]:
        if not service["actions"] or not any(
            service["unit"] == item["unit"]
            and service["scope"] == item["scope"]
            and set(service["actions"]) <= set(item["actions"])
            for item in available["services"]
        ):
            raise ValueError("The selected service actions are no longer available.")


def execute(job, available):
    if job["payload"]["action"] == "disconnect":
        result = subprocess.run(
            ["systemctl", "--user", "disable", "--now", "ark-system-agent.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        if result.returncode:
            raise ValueError(
                "The host agent service could not be stopped. Retry after host services recover."
            )
        return
    configuration = job["payload"]["configuration"]
    approved(configuration, available)
    args = SimpleNamespace(
        terminal=configuration["terminal"],
        power=configuration["power"],
        processes=configuration["processes"],
        shell=configuration["shell"] or available["default_shell"],
        directory=None,
        service=[],
        install=True,
    )
    system_agent.enroll(args, service_policy=configuration["services"], announce=False)


def cycle(config):
    available = inventory()
    api(config, "report", {"inventory": available})
    if JOURNAL.exists():
        pending = json.loads(JOURNAL.read_text())
    else:
        job = api(config, "work")["job"]
        if not job:
            return
        created = (
            datetime.fromisoformat(job["created_at"])
            if job.get("created_at")
            else datetime.now(UTC)
        )
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        pending = {"job": job, "phase": "claim", "started": created.timestamp()}
        storage.atomic_write(JOURNAL, json.dumps(pending))
    job = pending["job"]
    if pending["phase"] == "claim":
        claim = api(
            config,
            "report",
            {
                "inventory": available,
                "job_id": job["id"],
                "state": "applying",
                "message": "Preparing the host agent and installed dependencies.",
            },
        )
        if not claim.get("accepted"):
            JOURNAL.unlink(missing_ok=True)
            return
        pending["phase"] = "apply"
        storage.atomic_write(JOURNAL, json.dumps(pending))
    if pending["phase"] in {"apply", "verify"} and time.time() - pending["started"] > 600:
        pending.update(
            phase="failed",
            message="The System request expired before setup was verified. Retry the connection.",
        )
        storage.atomic_write(JOURNAL, json.dumps(pending))
    if pending["phase"] == "apply":
        try:
            with storage.configuration_lock():
                execute(job, available)
            pending.update(
                phase="verify",
                message="Waiting for host readings."
                if job["payload"]["action"] == "connect"
                else "System disconnected.",
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            pending.update(
                phase="failed",
                message="System setup could not complete. Check host service availability "
                "and package download access, then retry.",
            )
        storage.atomic_write(JOURNAL, json.dumps(pending))
    if pending["phase"] == "verify" and time.time() - pending["started"] > 600:
        pending.update(
            phase="failed",
            message="The host agent did not report readings in time. Retry the connection.",
        )
        storage.atomic_write(JOURNAL, json.dumps(pending))
    state = "failed" if pending["phase"] == "failed" else "completed"
    try:
        report = api(
            config,
            "report",
            {
                "inventory": available,
                "job_id": job["id"],
                "state": state,
                "message": pending["message"]
                if state == "failed" or job["payload"]["action"] == "disconnect"
                else "System connected. Host readings are available.",
            },
        )
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 409 and pending["phase"] == "verify":
            api(
                config,
                "report",
                {
                    "inventory": available,
                    "job_id": job["id"],
                    "state": "verifying",
                    "message": "Waiting for the host agent to report readings.",
                },
            )
            return
        if error.code in {403, 404, 422}:
            JOURNAL.unlink(missing_ok=True)
        raise
    if report.get("accepted") or state in {"completed", "failed"}:
        JOURNAL.unlink(missing_ok=True)
