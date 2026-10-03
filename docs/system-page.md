# System page upgrade plan

Status: approved implementation specification. Implementation and verification follow this document;
see [System host setup and operation](system-host.md) for the shipped enrollment workflow,
configured limits, and operational semantics. This document preserves the original design intent.

**Updated configuration requirement:** System connection and all capability configuration live in
**Administration → System**, not the operations page. **Connect System** automatically prepares,
enrolls, installs and verifies the agent using the deployment-owned host manager already prepared
for Local Files. Routine setup does not require running an enrollment script. CLI tools below are
owner recovery interfaces only; this requirement supersedes the original manual enrollment flow.

## 1. Purpose and approved scope

Replace **System Information** with **System**, a host workspace for understanding the machine, inspecting its vitals, and performing administrator operations.

The approved scope is:

- Identity and Compute lead the main System page.
- Temperatures, Memory, and Storage move to a System subpage named **Vitals**.
- An embedded, interactive host terminal appears underneath every other functional panel on the main page.
- Dedicated host controls include selected service management, process inspection and termination, restart, and shutdown.
- Signed-in users retain read-only system information access. Terminal access and host control are administrator-only.
- Host access is enrolled automatically from Administration under the deployment owner's host authority. The terminal uses that account's installed shell and permissions.

The visitor mode is **Operate**: help an operator identify the machine, understand its state, diagnose a problem, and act with clear feedback. Success depends on accurate scope, readable measurements, predictable navigation, and working host operations.

### Direction contract

- **Thesis:** identify the real machine first, diagnose resources in Vitals, and operate from
  clearly bounded host controls and a real shell.
- **Own-world:** inherit ArkCloud's coffee/parchment semantic tokens, IBM Plex typography,
  restrained panel boundaries, and Administration-style segmented navigation.
- **Story:** identify the host, read its state, inspect details, then deliberately connect or act.
- **First viewport:** segmented navigation and timestamp, a connection row, Identity/Compute
  side by side on desktop; controls follow and Terminal is the final functional panel.
- **Form:** the user-approved composition in this document; no random concept selection is needed
  for this pinned layout. Implementation is code-led.
- **Finish:** unreviewed and undocumented is unfinished; this build ends with the finish review,
  the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## 2. Existing implementation and integration boundary

The current implementation consists primarily of:

- `apps/web/src/SystemInformationPage.tsx`: a temperature panel followed by Compute, Memory, Storage, and Identity.
- `apps/web/src/App.tsx`: the System Information navigation label, heading, and `#system-information` route.
- `apps/api/app/integrations/system.py`: collection through the unprivileged API runtime using psutil and fixed kernel interfaces.
- `apps/api/app/schemas/system.py`: section availability and source metadata, identity, compute, memory, one filesystem, and temperature readings.
- `apps/api/app/api/dashboard.py`: `/system` and `/system/information` endpoints.

Hostname and OS are currently configured labels. Storage measures one configured container-visible path. Kernel-visible CPU, memory, and sensors are not a complete host inventory.

True host collection and shell execution require an enrolled host-side service. Follow the owner-enrollment pattern of `scripts/storage_manager.py`, but implement a **separate System agent**, with its own credentials, lifecycle, and capability policy. The storage manager remains focused on storage provisioning.

Preserve these deployment boundaries:

- The API remains unprivileged.
- Do not add host-root telemetry mounts, Docker socket access, privileged namespaces, or privileged containers.
- Keep the exposed web listener bound to `127.0.0.1`; remote access continues through Tailscale Serve.
- Browser requests use same-origin `/api/*`, including WebSocket attachment. Container service names never appear in browser configuration.
- PostgreSQL stores control-plane state, not terminal streams or file bodies.

## 3. Information architecture and navigation

Use **System** in primary navigation and the page heading. Provide segmented **Overview** and **Vitals** navigation, consistent with the Administration workspace.

| Route | Content |
| --- | --- |
| `#system` | Identity, Compute, administrator controls, terminal |
| `#system/vitals` | Temperatures, Memory, Storage |
| `#system-information` | Compatibility alias for System Overview |

Both routes must support direct loading, refresh, browser back/forward, and authenticated navigation. The System destination stays selected on Vitals. Keep the System heading consistent; the selected section supplies the secondary context.

Use labeled tab panels, arrow-key navigation, Home/End behavior, and visible focus treatment consistent with `AdministrationTabs.tsx`. Extract shared behavior only where it is useful without coupling unrelated route definitions.

## 4. Overview composition

```text
System                                      Updated … · Refresh

[ Overview ] [ Vitals ]

Identity                         Compute
Hostname · OS · kernel           CPU model · topology · utilization
Architecture · uptime            Frequency · load · detected GPUs

Host controls                                      Administrators
Selected services                Processes
Status · start/stop/restart       Search · sort · CPU · memory · terminate
Restart host · Shut down host

Terminal                                           Administrators
Host account · shell · connection state       Connect · Expand · End
┌─────────────────────────────────────────────────────────────────┐
│ Interactive host shell                                          │
└─────────────────────────────────────────────────────────────────┘
```

### Identity

Make the host identity the strongest informational anchor. Show:

- Actual hostname and OS distribution/version.
- Kernel release and architecture.
- Boot time and readable uptime, including days when appropriate.
- Agent connection state and collection timestamp.

Put ArkCloud API/Python versions and integration diagnostics in secondary details, explicitly labeled as application runtime information rather than host identity.

### Compute

Show CPU model, physical/logical cores, socket count where detectable, overall utilization, current frequency, and 1/5/15-minute load averages. Provide per-core utilization as expandable detail rather than overwhelming the first viewport.

List detected GPUs with normalized vendor/model information. Device discovery does not imply utilization access. Add GPU measurements only when a collector supports them; unsupported measurement fields remain unavailable.

### Host controls

Administrators see selected services and processes below Identity and Compute. Read-only users see the information panels without host-operation controls or an interactive terminal.

Give power actions their own clearly labeled row, separated from routine service actions. Show the target hostname in confirmations and action feedback.

### Terminal placement

The terminal is the last functional panel on Overview. It follows the controls directly, with no artificial spacer or viewport-height requirement. A short explanatory/footer note may follow it.

Use a useful bounded default height with an expanded workspace mode. Connecting to the terminal is an explicit action; loading System must not start a shell.

## 5. Vitals composition and data

Vitals is the resource diagnosis surface. Place Temperatures first, followed by Memory and a full-width Storage ledger. Maintain a coherent reading order when panels stack.

| Area | Planned data and presentation |
| --- | --- |
| Temperatures | Current readings grouped by CPU, GPU, memory, motherboard, storage, and other sensors; hardware-reported high/critical thresholds when available |
| Memory | Total, used, available, cache/buffers, utilization, swap total/used, and swap activity where supported |
| Storage | Host-mounted filesystems with mount, filesystem type, capacity, used/available space, utilization, mount options, and device association |
| Storage detail | Available device I/O counters and clearly described interval-derived rates |

Sensor records need stable identifiers, group metadata, original source labels, and units. Group on normalized backend categories rather than frontend label-prefix guesses. Do not infer sensor placement or invent temperature thresholds.

Exclude pseudo-filesystems and duplicate bind-mount capacity entries from the default storage ledger using documented collector rules. Make relevant omitted mounts discoverable in details. Distinguish physical-device counters from filesystem capacity; do not claim exact per-filesystem I/O when only device-level counters exist.

Ark-managed storage locations can be identified where an existing stable mapping is available. Provisioning remains in Administration → Storage, with a link for administrators. Vitals is not a second provisioning workflow.

Use compact utilization instruments and readable ledgers. Avoid a separate decorative card for every field. Optional details must remain usable with many sensors, mounts, cores, and long device names.

## 6. Refresh, provenance, and failure states

Each response must identify its scope, source, collection time, section availability, and capabilities. Availability remains `available`, `partial`, or `unavailable`; connection state is a separate concept.

- Collect telemetry automatically while the relevant view is visible, with a manual refresh action.
- Pause browser polling when hidden; bound agent sampling and avoid overlapping collection runs.
- Separate relatively static inventory from frequently changing measurements.
- Display the collection time, not merely the time the browser received a response.
- Preserve the last successful values after a refresh failure and clearly mark them stale.
- Handle independently missing sections; sensor failure must not hide Identity or Memory.
- Represent missing data as unavailable, not zero, and never infer healthy status from missing readings.
- Keep graphs honest: short rolling history starts when collection begins and shows gaps after interruption. No implied history before enrollment or reconnect.

Initial suggested intervals are five seconds for visible dynamic telemetry and slower inventory refresh. Final intervals, idle limits, and history bounds should be named configuration constants, verified against collection cost and transport behavior.

When the agent is unconfigured, link administrators to Administration → System and show a concise read-only explanation for other users. Do not show enrollment commands or configuration forms on System. Existing API-runtime telemetry can remain available in an explicitly labeled runtime view. Never silently substitute container readings into host fields.

When the agent disconnects, retain the last host snapshot with its timestamp. Disable operations that require a live host. Distinguish not enrolled, connecting, connected, stale/offline, revoked, and incompatible agent version.

## 7. Host System agent

### Topology

```text
Browser ── same-origin /api ── FastAPI ── authenticated outbound agent connection ── Host
                                                                                  ├─ telemetry
                                                                                  ├─ typed actions
                                                                                  └─ shell PTYs
```

The host agent initiates its connection to the loopback web endpoint. It does not expose a new listening port. An authenticated persistent connection supports low-latency terminal transport and typed messages for snapshots, heartbeats, actions, and results.

Implement the agent as a Linux host service running under the enrolled account, preferably a systemd user service. Document prerequisites, dependency installation, supervision without systemd, and user-service persistence across logout where required.

### Enrollment and capabilities

The deployment host manager executes typed, administrator-requested lifecycle jobs for enrollment,
configuration and disconnect. Administration → System discovers installed shells and permitted
services, exposes capability choices, and reports verified connection progress. Owner-run lifecycle
commands under `./scripts/ark system` remain available for exceptional deployment recovery.
Enrollment must be repeatable without losing configuration unexpectedly.

Owner configuration pins:

- The account identity, installed shell path, and starting directory.
- Whether terminal sessions are enabled.
- Permitted service units, their system/user scope, and permitted actions.
- Whether restart/shutdown are enabled and which host authorization supports them.
- Process control availability under the account's permissions.

Use a separate revocable credential, stored in an owner-readable file and represented server-side by a credential hash. Never send it to browsers or include it in logs. Reuse established no-redirect credential handling and loopback validation patterns where applicable.

Report effective capabilities, not just requested configuration. An unavailable permission or dependency must produce an actionable capability state. The UI cannot expand host-owner policy.

### Collector behavior

Read host information locally through Linux interfaces and bounded library calls. Normalize payloads before transmission. Bound sensor, mount, process, and device counts, string sizes, collection duration, and output size.

Use nonblocking interval samples for CPU and I/O rates, with an explicit warm-up state. Device disappearance, hotplug, permissions, and unsupported counters are ordinary partial-data states.

Include a boot identity and agent connection generation to distinguish reconnects, host restarts, and obsolete messages. Version the protocol and reject unsupported versions with a clear diagnostic.

## 8. Terminal implementation and lifecycle

Use xterm.js with a fit/resize integration in the React client. It is a terminal emulator connected to a real host PTY; the host's graphical terminal application is not embedded.

The agent starts the configured installed shell as the enrolled account. Inherit a deliberate host-shell environment, set an appropriate terminal type, and honor the configured starting directory. Do not accept browser-selected executable paths, user identities, or environment overrides.

The shell has the enrolled account's ordinary permissions and installed tools. Dedicated service/power capabilities do not automatically turn the terminal into a root shell. Existing host sudo behavior remains host policy.

Required behaviors:

- Interactive tools, Ctrl+C, resize, scrolling, selection, and copy/paste.
- A header showing hostname, account, shell, and connection/session state.
- Explicit Connect, Expand/Restore, and End session actions.
- Terminal focus is opt-in; page loading must not capture typing.
- Preserve the active session across Overview/Vitals navigation within the workspace.
- Allow bounded reconnection after a brief transport interruption, using a bounded replay buffer and reporting truncation when needed.
- Bound input/output frames, scrollback/replay storage, session count, and idle lifetime. Apply flow control to fast output.
- End the shell process group and reap children on termination; do not leave orphan PTYs.
- End sessions on logout, account disablement, administrator-role loss, agent revocation/shutdown, and idle expiry.
- API restart closes active sessions; reconnecting to a new API instance must not resurrect orphaned shells.

Begin with one active terminal session per administrator browser workspace. Multi-session tabs and durable background sessions are later extensions.

Do not persist terminal input or output in PostgreSQL or application logs. Record session lifecycle metadata only. Do not enable terminal escape-sequence features that open external links or write to the clipboard without deliberate user interaction.

## 9. Dedicated host operations

### Selected services

Show owner-enabled units only, including display name, actual unit name in details, system/user scope, active state, and permitted actions. Support start, stop, and restart with visible pending/result states.

Use fixed executable/argument structures or an equivalent typed system interface. Never pass a browser-supplied command string to a shell. Validate the allowlist in both API and agent. System services require explicit host authorization; user services use the enrolled account's permissions.

Prevent conflicting concurrent operations on a unit. If an operation stops the agent or its transport dependency, explain the expected connection loss and report an unknown outcome until it can be reconciled.

### Processes

Provide administrator-only process detail with PID, owner, executable name, CPU, memory, state, and start time. Use search, bounded/paginated results, and sortable resource columns. Full command lines and environment variables are not needed in the default payload.

Default termination sends SIGTERM after confirmation naming the process and owner. Revalidate PID plus start time immediately before signaling to avoid PID reuse. Where available, use Linux pidfds for stronger identity binding.

Report already-exited processes, changed identity, and permission denial separately. Force-kill is not part of the initial default workflow. Protect the agent and its own active terminal infrastructure from routine process-list termination.

### Restart and shutdown

These actions require explicit owner-enabled capabilities and host authorization. Confirmation names the host and explains service interruption; no extra confirmation is required for ordinary terminal commands.

- Deduplicate submitted actions with idempotency keys.
- Give jobs a short execution deadline; expired offline jobs never execute upon later reconnection.
- Persist acceptance/dispatch before an operation can sever the transport.
- Distinguish requested, accepted, dispatched, failed, expired, and unknown outcome.
- Never mark success solely because a command was sent.
- Verify a completed restart through reconnection with a changed boot identity.
- For shutdown, report the accepted request and subsequent disconnection without claiming independent proof of power-off.

## 10. API and transport contracts

The following endpoint families are proposed; names should be finalized consistently with existing API conventions during implementation. Browser paths include `/api`; FastAPI routes omit that proxy prefix.

| Family | Purpose | Access |
| --- | --- | --- |
| `GET /system/overview` | Host Identity, Compute, provenance, capability summary | Signed-in users |
| `GET /system/vitals` | Temperatures, Memory, Storage, timestamps | Signed-in users |
| `GET /admin/system/status` | Enrollment and detailed capability diagnostics | Administrators |
| `GET /admin/system/services` | Selected service status and allowed actions | Administrators |
| `GET /admin/system/processes` | Bounded process detail | Administrators |
| `POST /admin/system/jobs` | Typed service, process, and power operations | Administrators + CSRF |
| `GET /admin/system/jobs/{id}` | Job state and normalized result | Administrators |
| `POST /admin/system/terminal/sessions` | Create session and single-use attachment grant | Administrators + CSRF |
| Terminal attachment WebSocket | PTY input/output and resize protocol | Bound authenticated session + grant |
| Terminal termination endpoint | Explicitly end the session | Owning administrator + CSRF |
| Agent connection endpoint | Heartbeat, snapshots, actions, results, PTY relay | Agent credential |
| Enrollment/revocation interfaces | Owner enrollment and administrator revocation | Separate owner/admin authorization |

Retain existing `/system`, `/system/information`, and dashboard runtime contracts during migration unless consumers are updated deliberately. New host data must not change the meaning of existing runtime metrics implicitly.

Schemas should separate static inventory, dynamic measurements, effective capabilities, action jobs, and terminal lifecycle. Common fields include protocol/schema version, host/boot identity, collection time, availability, source/scope, and normalized warnings.

Jobs use a discriminated action union rather than an arbitrary command field. Process actions include process identity; service actions reference configured units. Normalize errors and bound all payloads; do not forward raw subprocess output as an API response.

### Browser and WebSocket authorization

Existing HTTP dependencies are request-based and cannot simply be attached to WebSockets. Implement explicit WebSocket session lookup and origin validation.

- Create attachment grants through authenticated, CSRF-protected POST requests.
- Bind each short-lived, single-use grant to the administrator session and terminal session.
- Prefer transmitting grants in an initial bounded handshake rather than a logged URL.
- Validate the browser's same-origin Origin through the supported proxy path before accepting input.
- Verify authentication and ownership on attachment and during long-lived operation.
- Propagate logout/revocation immediately where possible, with bounded periodic revalidation as a backstop.
- Authenticate agents separately; agent credentials never authorize browser sessions.

Enable WebSocket proxying in `apps/web/vite.config.ts` while retaining `/api` rewriting. Verify browser-origin handling through both local access and Tailscale Serve; proxy origin rewriting must not undermine validation.

## 11. Persistence and action reliability

Add an Alembic revision for control-plane schema changes. Planned persisted records include:

- System-agent enrollment, credential hash, protocol version, capability policy metadata, last-seen state, and revocation.
- Typed action jobs with requester, target identity, idempotency key, deadline, dispatch state, normalized result, and timestamps.
- Audit metadata for enrollment/revocation, terminal connect/end, and host actions.

Keep latest snapshots, short rolling histories, terminal transport, and bounded replay buffers in memory for the current single-API deployment. Document that restart loses live history and terminal sessions. If multi-worker deployment is added, an explicit shared broker is required; do not assume process-local routing works across replicas.

Use a durable agent-side action journal for dispatch deduplication across reconnects. Retrying a result report must not repeat a power action or process signal. Reconcile accepted jobs after disconnect; an unrecoverable ambiguity is an unknown outcome rather than automatic replay.

Bound audit/job retention and redact credentials, terminal content, environment values, and raw subprocess output from logs.

## 12. Visual and accessibility requirements

Inherit `DESIGN.md` and semantic tokens in `apps/web/src/redesign.css`:

- Coffee/parchment palette, IBM Plex Sans, and IBM Plex Mono for terminal/code/measurements.
- Existing panel corners, restrained boundaries, and outlined secondary actions.
- Operational state expressed with text plus semantic tone, never color alone.
- Compact, content-sized panels with clear alignment and label/value hierarchy.
- Desktop Identity/Compute and control pairs stack on narrow screens; Storage and Terminal remain full-width work surfaces.
- Long hostnames, units, mounts, and executable names wrap or expose accessible detail without breaking layout.
- Keyboard-operable tabs, controls, confirmation dialogs, and terminal escape/focus behavior.
- Status announcements for connection and action changes without announcing every telemetry update.
- Visible focus, adequate target sizes, reduced-motion support, and locale-aware measurement/date formatting.
- Review light, dark, high-contrast light, and high-contrast dark appearances.

Terminal resizing must react to panel expansion and viewport changes without resetting the session. Provide a clear way to move focus back to the page and a useful explanation if the mobile input experience is limited.

## 13. Implementation phases

### Phase 1 — Host-agent foundation

1. Define versioned schemas and effective capability policy.
2. Add enrollment/credential persistence and owner enrollment tooling.
3. Implement the host agent, outbound connection, heartbeat, and reconnect behavior.
4. Implement bounded inventory and telemetry collectors.
5. Add systemd installation, lifecycle/check commands, and setup documentation.

Acceptance: a separately enrolled host produces accurate, scoped snapshots without new listener ports or elevated API privileges. Revocation stops its access.

### Phase 2 — Backend read/control plane

1. Add dedicated system routes, schemas, and services.
2. Implement host snapshot caching and explicit runtime fallback presentation.
3. Add typed jobs, authorization, deadlines, idempotency, agent journal, and audit metadata.
4. Implement selected-service, process, and power operations.
5. Verify privilege failures and reconnect reconciliation.

Acceptance: read-only users cannot access sensitive process/service detail or execute operations. Actions respect owner policy, expire correctly, and never blindly replay after interruption.

### Phase 3 — System and Vitals UI

1. Replace the System Information label and add hash routes/compatibility alias.
2. Build Overview/Vitals navigation and focused page components.
3. Lead Overview with Identity and Compute.
4. Move and expand Temperatures, Memory, and Storage in Vitals.
5. Build administrator services/process controls and action feedback.
6. Implement loading, empty, partial, offline, stale, revoked, and retry states.

Acceptance: navigation and data scope remain understandable at desktop and mobile sizes; unavailable sections do not collapse the rest of the workspace.

### Phase 4 — Terminal transport and UI

1. Add xterm.js and fit integration with locked dependency updates.
2. Implement PTY lifecycle and framed input/output/resize transport.
3. Implement session creation, grants, attachment, reconnection, cleanup, and revocation.
4. Enable same-origin WebSocket proxy support.
5. Place Terminal last on Overview, with connect/end and expanded mode.

Acceptance: interactive host tools work, resize is correct, fast output stays bounded, and logout/revocation leave no usable session or orphaned PTY.

### Phase 5 — Integrated verification and documentation

1. Run focused collector, authorization, job, PTY, and frontend checks.
2. Run required backend/frontend lint, format, test, and build checks.
3. Verify the integrated Compose path through loopback and Tailscale Serve.
4. Review desktop/mobile layouts and all four theme variants in a bounded visual pass.
5. Update architecture, security, development/setup, and product/design context to describe shipped behavior.

Acceptance: the documented owner setup is reproducible and every advertised capability has working success and failure handling.

## 14. Expected code areas

- `apps/web/src/App.tsx`: navigation, headings, role/session props, and route handling.
- `apps/web/src/SystemInformationPage.tsx`: replacement by focused System workspace components.
- New frontend System Overview, Vitals, service/process, terminal, navigation, and route modules as needed.
- `apps/web/src/api.ts`: typed reads, jobs, and terminal lifecycle calls.
- `apps/web/src/redesign.css` and existing style files: surface-specific composition using existing tokens.
- `apps/web/vite.config.ts`: WebSocket forwarding.
- `apps/web/package.json` and lockfile: terminal dependencies.
- `apps/api/app/schemas/system.py` and new control/terminal schemas.
- Dedicated API routes and services for host read/control, agent transport, and terminal brokerage.
- API database models and an Alembic revision for enrollment, jobs, and audit metadata.
- New host-agent/enrollment modules under `scripts`, plus `scripts/ark` lifecycle integration.
- Existing System tests and new focused agent/control/terminal tests.

Finalize filenames against repository conventions during implementation. Avoid turning the page component, host agent, or API router into a single monolithic module.

## 15. Verification matrix

| Area | Meaningful checks |
| --- | --- |
| Collection | Fixture-backed OS/kernel data, missing permissions, sensor thresholds, mount filtering, hotplug, CPU/I/O warm-up, finite/range validation, count bounds |
| Authorization | Unauthenticated/non-admin rejection, read-only response filtering, CSRF, origin rejection, single-use/expired grants, session ownership |
| Revocation | Logout, disabled account, role removal, expired session, revoked agent, terminal teardown |
| Jobs | Deadline expiry, duplicate requests/results, conflicting actions, interrupted dispatch, agent restart, unknown outcome reconciliation |
| Processes | PID reuse, already-exited targets, permission denial, protected agent targets |
| Services/power | Allowlist enforcement, scoped unit operations, missing privileges, transport loss, changed boot identity |
| PTY | Real disposable shell interaction, Ctrl+C, resize, EOF, shell exit, process-group cleanup, backpressure, bounded replay and reconnect |
| Frontend | Direct routes and legacy alias, tab keys, role-based controls, stale/partial data, confirmations, lifecycle feedback, preserved terminal across subpages |
| Integrated deployment | Same-origin HTTP/WebSocket through Vite and Tailscale Serve, API restart, agent reconnect, unchanged loopback exposure |
| Visual/accessibility | Desktop/mobile, long/many records, both themes and high contrast, keyboard focus and dialogs, terminal focus escape |

Run backend checks using the repository's SQLite unit-test Compose form: `docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api pytest`, and the equivalent commands ending in `ruff check .` and `ruff format --check .`.

Run frontend checks from `apps/web`: `npm test`, `npm run lint`, `npm run format:check`, and `npm run build`. Add host-agent unit tests runnable without Docker, using disposable trees/processes and mocked host-control interfaces. Real restart/shutdown must not run in automated tests; verify dispatch using mocks and conduct any real host acceptance explicitly in a suitable environment.

Rebuild after dependency changes using the supported lifecycle helper. Integrated API requests go through `http://127.0.0.1:5173/api/...`.

## 16. Completion criteria and implementation decisions

The upgrade is complete when:

- System replaces System Information in visible navigation and headings.
- Overview and Vitals are directly navigable, with the legacy route supported.
- Real host Identity and Compute lead Overview; resource details live in Vitals.
- Enrolled host telemetry is accurately scoped, partial failure is visible, and stale data never appears live.
- Owner-enabled services, processes, restart, and shutdown work with accurate job feedback.
- The embedded terminal uses the enrolled host shell and appears below all other Overview panels.
- Read-only users retain useful information access without gaining host control or sensitive administrator detail.
- Session revocation, job deduplication, and PTY cleanup pass meaningful tests.
- Setup, privileges, recovery, limitations, and runtime-versus-host scope are documented.
- Integrated transport and responsive/theme verification are complete.

Implementation must finalize and document exact sample intervals, terminal limits, grant/reconnect lifetimes, job deadlines/retention, the host dependency strategy, and system-service/power authorization setup. These are engineering configuration decisions within the approved architecture, not additional UI scope.

Long-term telemetry retention, automatic privilege escalation, arbitrary service enrollment through the browser, force-kill workflows, multiple terminal tabs, durable background shells, and multi-host management are outside this initial upgrade.
