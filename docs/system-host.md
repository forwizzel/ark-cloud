# System host setup and operation

System has two sections: **Overview** (`#system`) and **Vitals** (`#system/vitals`). The old
`#system-information` link opens Overview. Identity and Compute lead Overview; administrator
service/process controls follow, and the embedded host terminal is the last functional panel.
Temperatures, Memory, and Storage live in Vitals.

## Connect and configure in Administration

Open **Administration → System** (`#administration/system`), choose access options, and press
**Connect System**. No enrollment command, credential copy, or manual script is required.
The regular System page is the operations workspace; all connection and capability settings live
in Administration.

The supported `./scripts/ark up` lifecycle already prepares and starts the deployment-owned host
manager used by Local Files. That manager now also handles narrowly typed System lifecycle jobs.
It discovers the account's installed shells and controllable services, prepares pinned dependencies,
enrolls the separate agent, installs its user service, and waits for authenticated host readings.
The UI shows preparing/connecting/verification progress and reports success only after readings arrive.

Host identity is detected from the enrolled Linux system: hostname, distribution metadata,
kernel release and architecture. No hostname, distribution or kernel version is assumed from
Ark Cloud branding. If distribution metadata is unavailable, the OS label is **Linux** and a
warning is reported while other host readings remain available. Dashboard environment labels
apply only to the separate API-runtime view and do not override these detected host values.

Select terminal access, an installed shell (or the host account default), process inspection and
termination, available power controls, and selected service actions. **Save changes** applies the
settings and reconnects the agent. Reconnection rotates its credential and ends existing terminal
sessions. Failed setup exposes **Retry connection**; it does not ask the user to run scripts.
Unsaved edits are preserved during status polling and guarded when leaving the settings page.

The host account is fixed by deployment ownership; the browser cannot choose another account,
an arbitrary executable, environment, or a host path. Its home is the terminal starting directory.
Enrollment creates private `.ark-system/` state, a dedicated Python virtual environment, and a
revocable credential whose hash is registered through Compose stdin. Credentials stay server-side.
The agent itself needs neither Docker privileges nor an inbound listener. The API remains unprivileged.

Setup uses the same Linux/systemd user-service deployment prerequisites as managed Local Files,
plus Python venv/pip and package download access for initial dependencies. Dependencies already at
the pinned versions are reused when applying settings. The System service is automatically restarted
with the account's service manager; user-service persistence across logout follows host deployment policy.

## Selected services and power permissions

Only selected units and their chosen actions are exposed. User units use `systemctl --user`
under the enrolled account. System units and power actions use noninteractive `sudo -n` with
fixed arguments. ArkCloud does not create sudoers rules or grant privileges automatically.

If enabling system units or power actions, the host owner must authorize the **exact** commands
through the host's sudo policy. Determine the installed path with `command -v systemctl`. For an
example account named `owner` and systemctl at `/usr/bin/systemctl`, narrowly scoped entries are:

```sudoers
owner ALL=(root) NOPASSWD: /usr/bin/systemctl --no-ask-password start example.service
owner ALL=(root) NOPASSWD: /usr/bin/systemctl --no-ask-password stop example.service
owner ALL=(root) NOPASSWD: /usr/bin/systemctl --no-ask-password restart example.service
owner ALL=(root) NOPASSWD: /usr/bin/systemctl --no-ask-password reboot
owner ALL=(root) NOPASSWD: /usr/bin/systemctl --no-ask-password poweroff
```

Use the host's reviewed sudoers editing/validation workflow. Substitute the real account, binary
path, and chosen unit; do not grant arbitrary systemctl arguments. The agent probes authorization
without executing the operation and removes unavailable dedicated actions from its effective
capabilities. Apply settings in Administration → System after modifying host authorization.
Execution still rechecks permissions and may fail if host policy changes afterward.

The terminal remains a shell for the enrolled account. Normal host sudo behavior applies inside
it; terminal access is not a file-grant-confined ArkCloud browsing session. Explicitly enabling
terminal delegates that account's shell access to ArkCloud administrators.

## Disconnect and recover

Use **Disconnect System** in Administration → System. The API immediately revokes the runtime
credential and ends active terminal sessions; the host manager stops and disables the user service.
Saved settings and host files remain intact. Press **Connect System** to reconnect, including after
a database restore. No agent command is needed in the normal recovery flow.

Provisioning jobs are separate from Local Files jobs and never recreate the API or touch content
mounts. The manager rechecks the administrator's session and host-approved choices before claiming
work. Its private lifecycle journal survives interruptions: verification retries do not reinstall or
rotate credentials, and unfinished setup can safely resume. Queued requests expire after ten minutes;
verification has the same overall deadline. Setup metadata and recent jobs are visible in Administration.

Owner-side diagnostic/recovery tools remain available for repairing a deployment whose host manager
cannot run. They are not instructions displayed by the UI:

```sh
./scripts/ark system status
./scripts/ark system check
./scripts/ark system revoke
systemctl --user status ark-system-agent.service
journalctl --user -u ark-system-agent.service
```

Status/check report local service/dependency state. The legacy revoke command invalidates the
runtime credential, while the UI Disconnect action additionally stops/disables the service.
An owner-supervised deployment can still use the legacy enrollment/run interface for recovery.

The agent connects outward to the loopback web proxy and retries every five seconds. Stack
recreation interrupts active terminals. It reconnects automatically when the web/API returns;
no host telemetry mount or exposed API port is needed. Preserve `.ark-system/` as sensitive local
state, not source code. Its SQLite action journal prevents automatic replay after interruption.

## Sessions and action semantics

- Only administrators can connect a terminal or use controls. Other signed-in users get host
  information, without process/service/account/shell details.
- Connecting is explicit. xterm.js runs the enrolled shell in a real host PTY; it does not open
  a graphical desktop terminal. Select the terminal to type; Ctrl+Shift+Escape returns focus to
  page controls. Plain Escape remains available to shell tools such as Vim. xterm screen-reader
  support is enabled for accessible output.
- One terminal per ArkCloud authentication session, at most eight per host. It survives switching
  Overview/Vitals, with an expanded workspace option.
- Browser transport interruptions can reattach within 30 seconds. Replay is bounded to 64 output
  frames; recent output may repeat and older output may be omitted. A failed reattach offers a new
  Connect attempt after reporting the ended session.
- Idle input expiry is 15 minutes. Logout, expired/revoked authentication, disabled accounts,
  role removal, agent revocation, and agent/API shutdown end the session. Authorization guards run
  every two seconds. Closing/navigating away from the workspace requests session termination;
  the detached-session timeout is the backstop if that request cannot be delivered.
- End session terminates the shell, foreground process group, and discoverable descendants.
  The systemd service also uses control-group cleanup on service shutdown.
- Process Terminate sends SIGTERM, rechecking PID/start time and using pidfds when available.
  Agent/terminal infrastructure is protected; permissions may prevent signaling other accounts.
- Service and power operations require confirmation. Jobs have 30-second deadlines, idempotency
  keys, and a durable pre-execution agent journal. A request does not prove a completed action.
- Restart is verified after reconnection with a changed boot identity. Shutdown can report an
  accepted request and disconnection, but cannot independently prove the host powered off.
  Ambiguous execution outcomes are not automatically retried.

## Telemetry and retention

Dynamic host samples are collected every five seconds; selected-service status is refreshed every
15 seconds. Authorization capability probes occur on agent connection. The browser polls visible
views every five seconds and pauses when hidden. Inventory currently travels with each bounded
snapshot; there is no separate durable inventory store.

The API retains 120 samples in memory (about ten minutes); Vitals exposes the most recent 30 in a
readable sample table. API restart clears this history and host snapshots. Offline values are
marked stale after 15 seconds without reports. When no host snapshot exists, container measurements
are available in a separately labeled **API runtime readings** disclosure, never substituted for
host measurements. Existing dashboard and `/system/information` semantics remain unchanged.

CPU/device rates need an interval sample; missing readings are unavailable rather than fabricated
zeroes. Temperature thresholds come from hardware. GPUs are identified through visible DRM PCI
metadata, without a utilization claim. The filesystem ledger excludes pseudo-filesystems and
duplicate device identities; omitted paths are disclosed. Device-level I/O is not per-filesystem I/O.
Collector limits are 128 sensors, mounts and I/O devices, 1,024 cores, 16 GPUs, 32 selected services,
and 2,048 visible processes. Permission/hardware limitations can produce partial readings.

Jobs and audit metadata are retained for 30 days and pruned during operation. Terminal input/output
are never persisted or logged. Agent logs contain connection summaries, not shell content or raw
host command output. PostgreSQL stores enrollment, owner policy, action jobs, and audit metadata.

The broker is deliberately **single API worker**. Multiple workers/replicas need an explicit shared
broker before they can route active agent/terminal sessions correctly. There are no durable
background shells, long-term telemetry graphs, force-kill controls, or multi-host management.

## Checks

Host tests require psutil and run without Docker. The disposable agent transport test also needs
websockets; the enrolled virtual environment supplies both dependencies:

```sh
python3 -m unittest discover -s scripts -p 'test_system*.py'
# After enrollment, run the complete suite with the agent's interpreter:
.ark-system/venv/bin/python -m unittest discover -s scripts -p 'test_system*.py'
```

API host protocol tests use the standard SQLite Compose test form. Real restart/shutdown actions
are not part of automated tests. Browser WebSockets use `/api/system/terminal/*` through Vite;
managed Tailscale Serve origin validation requires the authenticated gateway proof, not an
untrusted forwarded host header.
