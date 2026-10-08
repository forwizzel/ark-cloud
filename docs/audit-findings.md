# Ark Cloud audit findings

- **Audit date:** 2026-10-07
- **Baseline commit:** `4269f55bbec0fdb81c6d05e7811b356d389530b1`
- **Status:** Initial audit; all findings below are open. This report does not implement fixes.

## Executive assessment

Ark Cloud has unusually deliberate filesystem and credential boundaries for an MVP: descriptor-relative confinement, immutable account IDs, versioned grants, no-clobber file publication, separate host credentials, and normalized Tailscale responses are substantive protections. Existing automated checks pass.

The biggest concerns are **authentication concurrency, PID identity verification, SELinux isolation during owner commands/tests, durable job dispatch/recovery, and gaps between documented guarantees and actual verification**. Passing tests currently miss several reproducible defects. The code also has significant complexity concentrated in a few modules, while CI omits much of the host-side implementation.

This document is the remediation baseline. Findings have stable IDs, evidence, impact, and closure criteria. Priorities reflect Ark Cloud's supported private, single-worker deployment; an advisory's upstream severity is not automatically the application's priority.

### Priority and evidence definitions

- **P1 — High:** Address first; an important security boundary or supported deployment can fail.
- **P2 — Medium:** Fix correctness, recovery, security hygiene, or verification gaps in the next remediation cycle.
- **P3 — Low:** Planned refactoring, documentation/UX cleanup, or an explicit product decision.
- **Reproduced:** An isolated fixture or read-only check demonstrated the issue. A controlled interleaving is evidence of a race, not a claim that it was observed on the live deployment.
- **Code-confirmed:** The relevant implementation demonstrably has the described behavior; deployment-specific effects may remain untested.
- **Risk / verification gap:** Evidence supports a concern, but the full failure or exploit has not been demonstrated. These entries should not be represented as proven exploits.

No critical-severity exploit was established. No claim of a complete penetration test, WCAG certification, or universally safe deployment is made.

## Scope and verification

Reviewed the active API/authentication/storage/System/Tailscale code, ORM models and migration strategy, host provisioning/ACL/copy/PTY/collection helpers, Tailscale controller/gateway, React workspaces and request/navigation/appearance utilities, CSS, Compose/images, CI, and the README plus all eight tracked guides under `docs/`. Tests were examined for coverage and exercised. Local `PRODUCT.md` and `DESIGN.md` were also reviewed; their untracked status matters in A31.

The live stack was inspected read-only for service health and development-server behavior. Account changes, storage changes, host controls, and failure injections used disposable databases, mock interfaces, and temporary directories/processes. No real power action, credential enrollment, account recovery command, or live storage mutation was performed. Ignored deployment credentials were not copied into this report.

### Executed checks

| Check | Result |
| --- | --- |
| `docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api pytest` | **169 passed** |
| Same Compose form ending in `ruff check .` | Passed |
| Same Compose form ending in `ruff format --check .` | Passed; 75 files |
| `npm test` from `apps/web` | **165 passed**, 16 files; jsdom emitted three unsupported document-navigation messages |
| `npm run lint`, `npm run format:check`, `npm run build` | All passed |
| `python3 -m unittest discover -s scripts -p 'test_*.py'` | 58 tests; 1 skipped because host interpreter lacked WebSockets |
| Same host suite with `.ark-system/venv/bin/python` | **58 passed**, including disposable real agent transport/PTY |
| Tailscale tests on host | 21 tests; 2 skipped for nginx and opt-in runtime smoke |
| Tailscale tests in a one-off controller container | 21 tests; only opt-in runtime smoke skipped; real nginx gateway test passed |
| Opt-in Tailscale runtime smoke in a separate image container with disposable tmpfs state and no network | **1 passed**; delayed token, token rotation, offline startup, secret-free shutdown |
| `bash -n scripts/ark` | Passed |
| `npm audit --json` | **2 high-severity affected packages**; A04 |
| `npm audit --omit=dev --json` | No findings; does not cover the deployed Vite toolchain |
| OSV version queries for the API container's 39 third-party Python distributions | `cryptography==46.0.5` matched advisories; A04 |
| Temporary targeted audit probes | 5 backend, 2 frontend, and 2 host probes confirmed defects; additional psutil cache check confirmed A02's mechanism |

Temporary repository probe files were removed. Reproduction descriptions below identify the behavior permanent regression tests should cover. Dependency results are a dated database snapshot, not an audit of container OS packages or every native library.

**Verification limits:** No fresh live-tailnet connection, physical Safari/Android or assistive-technology pass, destructive disk-failure test, SELinux-enforcing deployment reproduction, populated PostgreSQL upgrade/restore rehearsal, or container-image vulnerability scan was performed. Browser automation was unavailable (`agent-browser` was not installed); frontend reproductions used the actual components in jsdom. Existing browser claims in `docs/ui-ux-verification.md` were reviewed as historical evidence, not independently reproduced.

## Finding index

| ID | Priority | Finding | Evidence |
| --- | --- | --- | --- |
| A01 | P1 | Password reset can race with login and leave a valid old-password session | Reproduced |
| A02 | P1 | PID reuse check after `pidfd_open` reads a cached start time | Mechanism reproduced |
| A03 | P1 | Owner commands and unit checks can relabel live private SELinux mounts | Code-confirmed; conditional |
| A04 | P2 | Known dependency advisories, including deployed development tooling | Scanner-confirmed |
| A05 | P2 | Login throttling has a shared proxy identity and no aggregate work budget | Code-confirmed |
| A06 | P2 | Sensitive responses lack consistent no-store/redacted validation handling | Reproduced / code-confirmed |
| A07 | P2 | HTTP request and transfer resource budgets are incomplete | Risk |
| A08 | P2 | Expired sessions and storage history have no bounded lifecycle | Code-confirmed |
| A09 | P2 | Pending administrator invitations are incorrectly protected as the last admin | Reproduced |
| A10 | P2 | A persisted host job can be stranded before queue dispatch | Reproduced |
| A11 | P2 | Synchronous work in async control paths undermines transport/guard timing | Code-confirmed risk |
| A12 | P2 | System lifecycle apply can replay enrollment after a crash | Reproduced |
| A13 | P2 | A manager heartbeat is accepted as a fresh storage scan | Reproduced |
| A14 | P2 | Long host provisioning starves unrelated storage health reports | Code-confirmed |
| A15 | P2 | Renaming a location recursively prepares ACLs and restarts the API | Code-confirmed |
| A16 | P2 | Access readiness can disagree with actual host-source availability | Code-confirmed |
| A17 | P2 | Local Files does not synchronize its mounted state with route changes | Reproduced |
| A18 | P2 | Host operation identities and unresolved outcomes are not recoverable across UI reload | Code-confirmed |
| A19 | P2 | Session expiry leaves the UI signed in without a recovery path | Code-confirmed |
| A20 | P2 | Host section availability is dropped from the frontend contract | Code-confirmed |
| A21 | P2 | Fractional device-I/O rates produce an undefined byte unit | Reproduced |
| A22 | P2 | Useful non-`/dev/` filesystems are excluded as pseudo/duplicate mounts | Reproduced |
| A23 | P2 | Terminal browser buffers are not covered by end-to-end flow control | Risk |
| A24 | P2 | CI omits host helper and Tailscale controller/gateway suites | Code-confirmed |
| A25 | P2 | SQLite unit checks do not verify deployed PostgreSQL constraints/concurrency | Verification gap |
| A26 | P2 | Backup and restore guidance lacks an executable, verified recovery procedure | Verification gap |
| A27 | P2 | Dependency/build reproducibility is weaker than documentation claims | Code-confirmed |
| A28 | P2 | Important security events have no durable audit trail | Code-confirmed |
| A29 | P2 | Architecture/security/roadmap disagree about host controls and implementation | Documentation defect |
| A30 | P3 | Release/version identity is inconsistent | Documentation defect |
| A31 | P2 | Referenced product/design ground truth is ignored and absent from Git | Reproduced |
| A32 | P3 | Security-sensitive behavior is concentrated in oversized, coupled modules | Maintainability |
| A33 | P3 | API contracts and request/error handling are duplicated and weakly typed | Maintainability |
| A34 | P3 | Styling, appearance data, and formatting have multiple overlapping implementations | Maintainability |
| A35 | P2 | Browser verification evidence is not reproducible from the repository | Verification gap |
| A36 | P3 | Setup/manual deployment documentation contradicts lifecycle prerequisites | Documentation defect |
| A37 | P3 | Listings and administration polling do avoidable repeated work | Code-confirmed |
| A38 | P3 | Several UI/deployment semantics need explicit decisions and small corrections | Code-confirmed / decision |

## Security and authentication

### A01 — P1: Password reset does not serialize with session creation

**Evidence:** `apps/api/app/api/auth.py:170–194,236–249`; `apps/api/app/auth/service.py:56–73`; owner recovery in `apps/api/app/auth/cli.py:55–74`.

Login loads a user and verifies its hash, then creates a session without locking/reloading the account or checking a credential generation. A password change/recovery can commit its new hash and session revocations between those steps. The login then commits a new session authorized by the old password. The same family of stale-account races needs review around invitation redemption and account state changes.

**Reproduction:** In a disposable SQLite fixture, let `verify_password` successfully verify the old hash, then use a separate session to replace the hash and delete existing sessions before verification returns. Login returns 200; its cookie still authenticates `/auth/session`, although a new login with the old password correctly returns 401.

**Impact:** The documented “password changes revoke every session” recovery boundary is incomplete, particularly if an attacker already knows the old password.

**Close when:** Session issuance and credential/state changes share a transactional account lock or credential-generation check; login must not issue a usable session from an obsolete hash. Add controlled-interleaving tests and a real PostgreSQL concurrency regression.

### A02 — P1: The pidfd identity recheck is cached

**Evidence:** `scripts/system_agent.py:182–199`; `scripts/test_system_agent.py:22–40`.

`execute` checks `process.create_time()`, opens a pidfd, then calls `process.create_time()` again on the same `psutil.Process`. That method caches its result. If the original process exits and its PID is reused between the first check and pidfd acquisition, the second check does not verify the process now bound to the fd. The code can signal that replacement process if permissions allow.

**Reproduction of mechanism:** Read a real process's start time, mock the underlying psutil start-time read to return a different value, and read again. The same `Process` returns the old value; a fresh `Process` observes the new value. This confirmed the cache, without forcing PID reuse or signaling a live process.

**Close when:** Verify a fresh kernel identity after acquiring the pidfd, reject a changed process, and keep that fd as the signaling authority. Test PID reuse precisely between the initial identity check and fd acquisition, not only a wrong initial start time.

### A03 — P1: One-off containers can relabel live private mounts

**Evidence:** `scripts/ark:54–60,145–148`; `scripts/storage.py:138–161`; `compose.yaml:103,141`; `docs/local-storage.md:223–231`.

Account commands use `compose run --rm --no-deps api` with the storage override. The temporary API container mounts the same manifest and private content trees with `Z` as the live API. On a SELinux-confined Docker daemon, that can reassign the paths to the temporary container's MCS label and deny the live container access. The ordinary API unit-check form also shares the live `./apps/api:/app:Z` source bind, even though it correctly omits content mounts. This directly conflicts with the guide's instruction not to mount a private tree in parallel test/init containers.

**Impact:** A supported owner recovery command or test run can disrupt a running instance on the very deployment type the storage guides discuss. This was not reproduced on an enforcing daemon.

**Close when:** Account recovery executes in the existing container or a control-plane-only environment without live private binds. Isolated tests use image-owned/disposable source mounts or a separate checkout. Verify that account recovery and unit checks preserve live source/content access under actual SELinux confinement.

### A04 — P2: Dependency advisories require remediation and reachability tracking

**Evidence:** `apps/api/pyproject.toml:13`; `apps/web/package-lock.json:1717–1728,3326–3334`; `apps/web/package.json:39`; `compose.yaml:116–121`.

The complete npm audit reported two high-severity affected packages:

| Package | Installed | Chain | Advisory / fixed version |
| --- | --- | --- | --- |
| `brace-expansion` | 5.0.9 | ESLint → minimatch | [GHSA-q2hr-2g5m-vwhr](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr), [GHSA-qhr7-859c-m2p7](https://github.com/advisories/GHSA-qhr7-859c-m2p7), [GHSA-6j4f-fj2g-mc7p](https://github.com/advisories/GHSA-6j4f-fj2g-mc7p); all listed ranges cleared by 5.0.12 |
| `source-map-js` | 1.2.1 | Vite → PostCSS; also jsdom → css-tree | [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q); fixed in 1.2.2 |

`npm audit --omit=dev` is clean, but **Vite is the deployed web server**. Dev-dependency classification therefore does not establish absence from the running stack. No crafted source-map or brace-expansion exploit was attempted.

OSV queries for the actual API environment matched **`cryptography==46.0.5`** against six GHSA records, plus overlapping PYSEC aliases:

- [GHSA-537c-gmf6-5ccf](https://github.com/advisories/GHSA-537c-gmf6-5ccf): vulnerable OpenSSL bundled in wheels; fixed in 48.0.1.
- [GHSA-g6cj-pr64-35w5](https://github.com/advisories/GHSA-g6cj-pr64-35w5): PKCS#7 decryption oracle; fixed in 50.0.0.
- [GHSA-jwv3-5hgf-82ww](https://github.com/advisories/GHSA-jwv3-5hgf-82ww): X.509 chain-building resource exhaustion; fixed in 49.0.0.
- [GHSA-m2h6-j472-rp4c](https://github.com/advisories/GHSA-m2h6-j472-rp4c): X.509 wildcard/name-constraint bypass; fixed in 49.0.0.
- [GHSA-m959-cc7f-wv43](https://github.com/advisories/GHSA-m959-cc7f-wv43): incomplete DNS peer-name constraints; affected range fixed in 46.0.6.
- [GHSA-p423-j2cm-9vmq](https://github.com/advisories/GHSA-p423-j2cm-9vmq): non-contiguous Python buffer handling; fixed in 46.0.7.

Ark's active cryptography use is Fernet over contiguous encoded bytes in `apps/api/app/services/tailscale_control.py:12,56–68`. Review found no application use of PKCS#7 or cryptography's X.509 verifier, and does not establish that these advisories are exploitable through Ark's current endpoints. Upgrading remains appropriate; 50.0.0 is the highest minimum fix among the reviewed records.

**Close when:** Upgrade compatible affected versions, rebuild images, rerun complete audits and relevant checks, and record reachability/accepted exceptions. Add scheduled scanning of Python, the entire deployed npm graph, and image/native packages.

### A05 — P2: Throttling shares a proxy identity and can be bypassed as a work budget

**Evidence:** `apps/api/app/api/auth.py:139,180–193,308`; `apps/api/app/auth/service.py:114–146`; `apps/web/vite.config.ts:15–21`.

Throttle subjects use `request.client.host`, which is the proxy-facing connection identity in the supported Vite path, not a trustworthy per-browser identity. Eight failures for one username can therefore lock out legitimate users of that account across devices. Setup and invite redemption similarly share a proxy bucket. Conversely, varying usernames bypasses an aggregate Argon2 work limit, and parallel requests can pass the threshold before their failures are recorded. Authenticated current-password checks are not throttled.

**Close when:** Define account, deployment-wide, and trusted-client budgets; cap concurrent expensive verification and bound attempt cardinality. Test through the actual proxy. Any client-address extraction must validate the trusted gateway path rather than accepting arbitrary forwarded headers.

### A06 — P2: Sensitive response hygiene is inconsistent

**Evidence:** `apps/api/app/main.py:56–63`; `apps/api/app/schemas/auth.py`; `apps/api/app/api/auth.py:79–125,271–295,335–349`; contrast `apps/api/app/api/tailscale_admin.py:80–81`.

Only Tailscale admin validation errors receive a generic redacted response. Standard FastAPI auth validation responses can include complete submitted password/code values in their `input` fields. Auth/session/invitation responses also lack an explicit `Cache-Control: no-store`, as do other sensitive account/file-metadata responses. File bytes and Tailscale responses already set stronger cache controls.

**Reproduction:** Submit an overlong marked password to `/auth/login`: the 422 JSON echoes the entire marked value and has no no-store header. A successful login likewise has no no-store header. This proves reflection to the submitting client, not disclosure to another user or logging of that password.

**Close when:** Redact sensitive field inputs across validation paths and consistently mark authentication, grants, invitations, and private metadata non-cacheable. Verify headers and responses with representative invalid requests and cookie-backed GETs.

### A07 — P2: HTTP and transfer budgets need completion

**Evidence:** `apps/api/app/api/local_storage.py:47–49,120–162,193–225`; `apps/tailscale/nginx.conf:25–26,47–50`; `compose.yaml:80–83`; `apps/api/app/schemas/auth.py`.

Upload byte and idle limits are good, but small JSON endpoints have no transport-level body limit before FastAPI parses their bodies. Pydantic field bounds do not bound initial JSON buffering. The gateway permits unlimited body size for streaming, without a separate small-JSON policy. Transfer slots are deployment-global: one authorized account can occupy all four uploads or eight downloads. Downloads have no explicit application idle/total deadline; an upload supplying data every 59 seconds can hold a slot indefinitely. There is no cumulative user storage quota.

**Impact / qualification:** Resource exhaustion is plausible for an untrusted tailnet visitor or account. No large-body denial of service was executed, and absence of user quotas may be an intentional product boundary.

**Close when:** Bound small request bodies independently of streamed uploads, test slow-client cleanup through the proxy, and define per-account fairness and transfer lifetime budgets. Explicitly decide whether quotas remain deferred.

### A08 — P2: Persistent records are not consistently bounded

**Evidence:** `apps/api/app/auth/service.py:56–86`; `apps/api/app/models.py:199–210`; `apps/api/app/api/storage_admin.py:615–619,917–945`; `scripts/storage_permissions.py:97–119`.

Expired auth sessions are rejected but never pruned; `last_used_at` is initialized and never updated. Storage jobs have no retention/pruning policy, and inventory fetches every failed job, including dismissed/superseded failures. Dismissal changes metadata rather than bounding the query. ACL journals append original metadata on repairs and have no documented compact/archive lifecycle. System jobs/audits do have 30-day pruning, making the inconsistency conspicuous.

**Close when:** Add indexed expiry cleanup and a documented session-lifetime/activity model. Paginate/archive storage history and bound failed-job response size without losing unresolved recovery records. Define ACL journal preservation/compaction rules compatible with rollback and backups.

### A09 — P2: A pending admin cannot be removed on a single-admin instance

**Evidence:** `apps/api/app/api/auth.py:366–377,414–425`; `apps/api/tests/test_local_accounts.py:177–190`.

The last-admin check counts only active admins with a password, but applies its protection to any active admin target, including a pending invitation with no password. With one signed-in administrator, a second pending administrator cannot be demoted, disabled, or deleted. The existing test correctly prevents removing the real last admin but does not test the pending target.

**Reproduction:** Invite `pending.admin` as admin on the standard one-admin fixture; all three removal actions return 409.

**Close when:** Protect only a target that contributes to the active-login-capable admin count, or evaluate the remaining eligible admins after the proposed operation. Cover pending, expired, disabled, and redeemed invitations.

## Host operations, storage control, and recovery

### A10 — P2: Durable acceptance and in-memory dispatch are not reconciled

**Evidence:** `apps/api/app/services/system_control.py:176–210,242–267`; `apps/api/app/api/system_host.py:271–303`.

`create_job` commits an accepted job before calling `broker.send`. If the bounded queue is full, the request returns 503 while the accepted job remains in PostgreSQL. An idempotent retry returns that row without enqueueing it. Restart/reconnect also loses accepted queue entries; connection setup has no persisted-job dispatch reconciliation. The eventual deadline can expire the job, but it never executes as accepted.

**Reproduction:** Fill the 128-entry command queue, submit a permitted restart job, observe 503 and a persisted `accepted` row, drain the queue, then repeat the same idempotency key. It returns `accepted` with an empty queue.

**Close when:** Implement an explicit durable-to-broker delivery state/dispatcher that can requeue an authorized unexpired accepted job exactly once, or persist a normalized failure when delivery cannot be scheduled. Cover queue pressure, crash after commit, reconnect, and idempotent retry. Already dispatched ambiguous jobs must remain non-replayable.

### A11 — P2: Async transport/control paths perform blocking work

**Evidence:** `apps/api/app/api/system_host.py:147–159,243–247,277–302,326–340,364–390`; `apps/api/app/api/system_provision.py:138–185`; `apps/api/app/api/local_storage.py:195–207`; `scripts/system_terminal.py:48–69`; `scripts/system_agent.py:324,418,449–454`.

WebSocket handlers and async control routes directly execute synchronous SQLAlchemy transactions. Upload setup directly resolves storage and performs filesystem/database work before its threaded writes. Host terminal cleanup performs process enumeration, signals, and an unbounded `process.wait()` from the agent's event loop. A stalled database, filesystem, or process teardown can delay unrelated sockets, snapshots, and the two-second authorization guard.

**Impact / qualification:** The “within two seconds” revocation claim assumes a responsive event loop and database; it is not a hard guarantee. A long pause was not injected into the live stack.

**Close when:** Move blocking operations behind deliberate bounded off-loop boundaries, set appropriate database/teardown timeouts, and test event-loop responsiveness and terminal revocation under slow DB/host work. Preserve single-worker broker ownership when moving work across threads.

### A12 — P2: Lifecycle journaling can replay credential rotation

**Evidence:** `scripts/system_provision.py:188–229`; `scripts/system_agent.py:146–164`; `docs/system-host.md:79–83`.

The lifecycle journal records `phase=apply` before enrollment, and only switches to `verify` after `execute` finishes. A process death after enrollment/service restart but before the next durable journal write leaves `apply` on disk. Recovery executes enrollment again, rotates credentials again, and restarts the service again. The assertion that unfinished setup safely resumes without reinstalling/rotating needs qualification for this window.

**Reproduction:** Mock the host apply boundary, simulate process death during the first `verify` journal write, then resume `cycle`; the same job's apply executes twice.

**Close when:** Persist/reconcile substeps using the installed credential/configuration/service identity and job generation, making enrollment idempotent across every write boundary. Crash-inject before and after enrollment, config publication, service enable/restart, and verification.

### A13 — P2: Heartbeats masquerade as fresh storage scans

**Evidence:** `apps/api/app/services/storage_control.py:50–66,72–88`; `apps/api/app/api/storage_admin.py:948–951,988–1004`.

Freshness and explicit refresh completion use `StorageControl.last_seen_at`. Both `/storage-manager/work` and actual inventory reports update that field. A successful work poll can satisfy `wait_for_host_refresh` without a new source scan, and it can make an older `root_health` snapshot appear current. The guide promises that Refresh locations waits for a new host scan.

**Reproduction:** Start with an old snapshot; while refresh waits, update only `last_seen_at` as a work heartbeat would. Refresh succeeds and the old generation remains unchanged.

**Close when:** Track manager liveness separately from scan completion/observation time. Refresh waits for a scan newer than the request, and root availability expires against the scan timestamp. Test heartbeats without reports and source disappearance between those calls.

### A14 — P2: Long System/storage jobs starve unrelated location health

**Evidence:** `scripts/storage_manager.py:795–816`; `scripts/system_provision.py:213–229`; `scripts/system_agent.py:109–136`; `scripts/storage_permissions.py:88–125`; `apps/api/app/services/storage_control.py:54–62`.

One manager loop performs storage work and then System provisioning sequentially. Initial Python dependency installation alone can take up to 180 seconds. Recursive ACL preparation can take much longer and has no overall duration/entry budget. While these operations run, there is no independent storage-health heartbeat/scan; after 30 seconds, otherwise healthy locations fail closed as stale. System connection can thus disrupt Local Files even though it does not recreate the API or change content mounts.

**Close when:** Keep read-only source health reporting independent of long lifecycle/ACL work, or explicitly model applying operations without mislabeling unrelated roots. Test a slow System install and large tree preparation while accessing a separate healthy root.

### A15 — P2: A location label edit performs full provisioning

**Evidence:** `apps/web/src/StorageAdministration.tsx:750–760`; `apps/api/app/api/storage_admin.py:745,809–823`; `scripts/storage_manager.py:414–427,585–599`.

Save name submits `update`; the API forces automatic access preparation and blocks the root. The manager walks/re-prepares the tree's ACLs, writes mount configuration, and force-recreates the API. This interrupts transfers/terminals and can fail on newly added unsupported content for a metadata-only edit. It also grows permission journals unnecessarily.

**Close when:** Separate label metadata changes from access-mode/identity/mount changes. A name-only edit should avoid recursive ACL preparation and container recreation, with a regression proving content access and active sessions remain available.

### A16 — P2: Access readiness does not incorporate current source health

**Evidence:** `apps/api/app/api/storage_admin.py:388–442`; `apps/api/app/services/local_storage.py:225–240`; `apps/api/app/services/storage_control.py:50–69`.

The access editor calculates `effective_level` from grants/account/block state and tests folders through `LocalStorage(..., verification=True)`. Verification uses deployed manifest health, bypassing the manager's newer root health/freshness. A retained mount whose host path has moved, or a stale manager report, can show “Shared directory ready”/“Private folder ready” while ordinary file operations reject that location. This undermines the editor's advertised effective/ready status.

**Close when:** Distinguish saved grants from currently usable access and include the same source-health/scan-freshness checks as file operations, without opening a nested DB transaction under a held lock. Test retained mounts with current missing/stale host reports.

## Frontend behavior and telemetry

### A17 — P2: Mounted Local Files ignores later route changes

**Evidence:** `apps/web/src/LocalFiles.tsx:120–125,240–253,372–389,420,446–456`; `apps/web/src/App.tsx:131–139,462–467`.

The selected root is read from the hash only when state initializes. App rerenders the same `LocalFiles` component for another `#local-files/<root>` hash, but Local Files does not subscribe to that route. `FileBrowser` likewise reads `initialPath` only once; folder navigation and location selection use `replaceState`, so folder history is not navigable. URL and displayed content can diverge during hash/Back/Forward changes.

**Reproduction:** Mount at `#local-files/first` with two healthy roots, change the hash to `#local-files/second`, dispatch the route event and rerender. The selector and last file fetch remain on `first`.

**Close when:** Root/folder state derives from a single routed source of truth with draft/transfer guards. Test mounted root changes, folder query changes, refresh, deep links, and browser Back/Forward. Decide deliberately which folder transitions should create history entries.

### A18 — P2: Operation recovery depends on a currently mounted component

**Evidence:** `apps/web/src/SystemAdministration.tsx:124–131`; `apps/web/src/SystemControls.tsx:44–48,132–168,194–229`; `apps/api/app/api/system_host.py:84–95`; `apps/api/app/services/system_control.py:202–210`.

SystemAdministration generates a new idempotency key on every apply attempt, including retries after an uncertain response. SystemControls correctly preserves the key for an in-component retry, but the uncertain request, current job ID, acknowledgment of unknown outcomes, and previous jobs exist only in component state/refs. Leaving System or reloading loses them. The API exposes individual job reads, but no browser job-list/recovery endpoint. A persisted ambiguous host operation can therefore disappear from the user's workflow and another operation becomes available after reload.

**Close when:** Persist request identity until the server outcome is known, expose recent/active jobs with ownership and normalized unresolved states, and restore them after navigation/reload/API restart. Test a lost response before/after acceptance and a power operation followed by page reload. Keep actual host action replay forbidden.

### A19 — P2: Expired/revoked authentication has no application-level recovery

**Evidence:** `apps/web/src/App.tsx:152–176,218–239`; `apps/web/src/api.ts:117–125,265–272`; `apps/web/src/TailscaleAdministration.tsx:64–74`; `apps/web/src/storageAdminApi.ts:170–179`.

Session state is fetched at startup/retry, not refreshed on API 401s. After the default 24-hour expiry, password recovery, disablement, or role change, the shell can still display authenticated/admin UI while all work fails. Logout also returns an error when its already-expired session is rejected; its message incorrectly says the session remains active. Tailscale identifies expiry but tells the user to sign in without transitioning the application to sign-in.

**Close when:** Centralize definitive unauthorized handling and route to reauthentication with appropriate draft warnings and return-location state. An expired-session logout should recover to signed-out UI rather than trap the user. Test expiry/revocation while each workspace is open.

### A20 — P2: Host availability is silently omitted from client types/rendering

**Evidence:** `apps/api/app/schemas/system_host.py:114–134`; `apps/web/src/systemApi.ts:11–68`; `apps/web/src/SystemInformationPage.tsx:49–313,582–590`.

The API publishes section-level `available`/`partial`/`unavailable` state. `HostSnapshot` omits `availability`, and the panels render values and global warnings without using those states. Collector partial states do not always add warnings: missing CPU model/frequency or incomplete memory data can appear as an ordinary panel with dashes. The approved System spec explicitly separates availability from connection state.

**Close when:** Carry and render the actual section availability, explaining partial/unavailable data without inferring health from an empty list or connected agent. Test partial sections without warnings, failed sensors with successful compute, and first-sample warm-up.

### A21 — P2: Small nonzero I/O rates render an invalid unit

**Evidence:** `apps/web/src/systemApi.ts:152–157`; `apps/web/src/SystemInformationPage.tsx:299–304`; `scripts/system_collect.py:217–226`.

For values between zero and one, the byte formatter chooses a negative exponent and indexes the unit array at `-1`. Interval-derived rates can legitimately be fractional bytes/second.

**Reproduction:** `bytes(0.5)` returns text containing `undefined` instead of a byte unit.

**Close when:** Clamp the unit exponent at zero and define sensible fractional-rate precision. Test zero, sub-byte rates, exact boundaries, large counters, and unavailable values.

### A22 — P2: Filesystem collection excludes legitimate capacity data

**Evidence:** `scripts/system_collect.py:177–204`; `docs/system-host.md:145–148`; `apps/web/src/SystemInformationPage.tsx:253–256`.

The collector considers any device not beginning `/dev/` omitted, rather than identifying pseudo-filesystem types. This drops NFS exports, many FUSE mounts, and other useful host storage. The UI/guide describe omissions as pseudo-filesystems and duplicates, which is incomplete. Partition/count limits also truncate inventory without a dedicated truncation warning.

**Reproduction:** Feed a readable fixture mount with device `server:/export` and type `nfs4`; it goes into omitted mounts and no capacity row is collected.

**Close when:** Use documented filesystem-type and identity rules, preserve useful network/FUSE capacity readings, and explain excluded/truncated inventory explicitly. Test local, network, FUSE, pseudo, duplicate-bind, inaccessible, and oversized inventories.

### A23 — P2: Terminal flow control ends before the emulator

**Evidence:** `apps/web/src/SystemTerminal.tsx:213–219,250–262`; `apps/api/app/services/system_control.py:48–49,58`; `scripts/system_agent.py:253,314–327`.

Agent/broker queues and frame sizes are bounded, but browser reception calls `emulator.write` without consumption acknowledgments or a pending-byte limit. Browser WebSocket sends during a large paste likewise do not bound `bufferedAmount`. Fast output can be received faster than xterm parses it, leaving browser/emulator buffering outside the advertised bounds. The broker's queue-overflow response also ends a shell rather than providing a complete backpressure protocol.

**Qualification:** No browser memory-exhaustion reproduction was run; this is an end-to-end resource-control gap, not proof that all terminal output is unbounded.

**Close when:** Define bounded queued bytes across PTY, broker, browser socket, and emulator; use xterm write callbacks/acknowledgments and paste pacing. Test sustained fast output, slow rendering, hidden/expanded terminal, long paste, and disconnect cleanup.

## Verification, operations, and supply chain

### A24 — P2: CI excludes major trust-boundary implementations

**Evidence:** `.github/workflows/ci.yml:10–59`; `apps/api/pyproject.toml:30–44`; `scripts/test_*.py`; `apps/tailscale/test_*.py`.

CI runs API pytest/ruff from `apps/api`, frontend checks, and a basic base-Compose health probe. It does not execute the host storage/System/PTY tests, Tailscale controller/gateway/runtime tests, or host-script static checks. The Compose job bypasses the supported `scripts/ark up` host-manager setup and never provisions content or a System agent. A working health endpoint is not acceptance of these features.

**Close when:** Add disposable host-helper and controller jobs, real nginx/PTY transport checks, static checks for host scripts, and a supported lifecycle smoke fixture. Explicitly opt into the offline runtime smoke with isolated volumes; never point it at live credentials/state.

### A25 — P2: Unit-test database semantics differ substantially from deployment

**Evidence:** `apps/api/tests/conftest.py:8,21–37`; `apps/api/app/core/database.py:15–29`; `apps/api/alembic/versions/0007_local_accounts.py:64–81,127–143`; `.github/workflows/ci.yml:17–18,54–55`.

The general API fixture creates current ORM tables in in-memory SQLite, with a shared StaticPool and no general `PRAGMA foreign_keys=ON`. It does not run migrations. PostgreSQL advisory locks, `FOR UPDATE`, cascade behavior, and real concurrent transactions are therefore outside normal route-test coverage. The Compose smoke verifies an empty-database migration/startup, not populated upgrades or authorization races. Some isolated migration tests do enable FKs, which is useful but not a substitute.

**Close when:** Keep fast SQLite checks, enable their meaningful FK semantics, and add PostgreSQL tests for account deletion cascades, last-admin races, login/reset, grant revocation/upload publication, job claiming, and concurrent first-row initialization. Test populated upgrade chains and schema parity with current models.

### A26 — P2: Recovery guidance is descriptive rather than executable and proven

**Evidence:** `README.md:184–197`; `docs/development.md:162–177`; `docs/local-storage.md:312–328`; `docs/system-host.md:102–103`; `docs/roadmap.md:62–65`.

The docs correctly identify content, PostgreSQL/UUIDs, ACLs/xattrs, storage configuration, and Tailscale secret/controller/identity volumes. They do not supply a complete tested backup/restore runbook with actual database dump/restore commands, safe destination selection, consistency/verification steps, and recovery of host-service configuration and `.ark-system` state. System disconnect/re-enroll is discussed separately, but not integrated into a unified restore procedure. Automated restoration evidence is absent; the roadmap acknowledges this.

**Close when:** Provide and run a disposable end-to-end recovery rehearsal covering content hashes, private/shared access, old/new account identity, missing encryption key, host-manager re-enrollment, System journal handling, and Tailscale identity. Record the expected recovery boundaries and how to avoid carrying stale jobs/host identities into a replacement deployment.

### A27 — P2: Pins do not make the whole build reproducible

**Evidence:** `apps/api/pyproject.toml:10–28`; `apps/api/Dockerfile:1,13`; `apps/tailscale/Dockerfile:1–5`; `apps/web/package.json:18–19`; `.github/workflows/ci.yml:20–25,36–42`; `docs/security.md:124–141`.

There is no Python transitive lock/hash set. System enrollment independently installs pinned psutil/WebSockets with pip. The Tailscale base image is digest-pinned, but its added Alpine packages are resolved at build time; API/web/PostgreSQL image tags are not digest-pinned. Two direct xterm dependencies use caret ranges despite the docs' exact-direct-pin claim, although the npm lockfile currently locks their concrete versions. CI actions are version-tagged, not immutable-SHA-pinned. No automated update/audit process is present.

**Close when:** Define reproducibility/update policy, lock supported Python graphs, pin or deliberately track image/package provenance, reconcile direct-dependency wording, and make security updates routine. Separate dependency locking from advisory scanning; both are needed.

### A28 — P2: Audit coverage misses account/security control changes

**Evidence:** `apps/api/app/api/auth.py`; `apps/api/app/api/storage_admin.py:496–513,672–690`; `apps/api/app/api/tailscale_admin.py:190–287`; `apps/api/app/services/system_control.py:28–38`; `apps/api/app/core/logging.py:10–22`.

System lifecycle/jobs and storage grants/settings have metadata records; file mutations have structured logs. Login successes/failures, invitations/reissues, account role/activation/deletion, password/username changes, and Tailscale credential/desire changes have no equivalent durable security audit trail. This makes incident/recovery analysis difficult when administrators control host-account operations. Log rotation/retention is also left to deployment instructions rather than provided Compose configuration.

**Close when:** Record bounded, redacted actor/action/target/result metadata for security control changes and owner recovery, with explicit retention/access policy. Never record passwords, invitation tokens, keys, file paths unnecessarily, or terminal streams. Test redaction and representative events.

## Documentation and maintainability

### A29 — P2: Documentation disagrees about active trust boundaries/features

**Evidence and corrections needed:**

- `docs/architecture.md:202–210` says queues/WebSockets have no current use case, while `:139–143` describes the shipped broker, WebSockets, and persisted jobs. Replace the obsolete deferred-decision statement.
- `docs/roadmap.md:69–76` still proposes considering a host agent and excludes process-control APIs, despite the implemented System agent/process controls and `README.md:36–38`. Clarify owner-enabled controls versus unrestricted host access.
- `docs/security.md:181–183` says no process data is collected or stored without explicitly limiting that statement to the retired container-only view. The agent collects process snapshots and termination jobs persist PID/start-time payloads. Scope the statement accurately.
- `docs/local-storage.md:102–104` advertises UI host access-mode and advanced SELinux/ACL controls, but `apps/web/src/StorageAdministration.tsx:718–877` only exposes name, base relocation, checks, reviewed identity, and disconnect; it passes the existing `read_only`/`selinux` values back unchanged. Document the actual UI or ship the advertised controls.
- `docs/system-host.md:118–121` / `docs/security.md:62` describe two-second terminal revocation without the responsiveness qualifications in A11; the lifecycle resume wording needs A12's correction.
- `apps/api/app/api/auth.py:426` still describes cascaded Drive metadata/credentials after the integration was removed.

**Close when:** Guides and source comments agree on current behavior, scope guarantees precisely, and identify plans/history as such. Keep the no-host-root/no-Docker-socket/API-unprivileged boundaries explicit.

### A30 — P3: The release version has multiple incompatible identities

**Evidence:** `README.md:12,133–139` announces v1.0 MVP; `apps/api/pyproject.toml:7`, `apps/api/app/main.py:43`, and `apps/web/package.json:4` are 0.9.0; `docs/security.md:5` and `docs/local-storage.md:1` describe 0.9; `docs/architecture.md:184` names v0.9; `apps/api/app/integrations/tailscale.py:124` identifies `ark-cloud/0.1`.

**Impact:** Operators cannot reliably relate documentation, installed runtime metadata, integration requests, and the current milestone.

**Close when:** Choose the intended release identity, centralize runtime version derivation, update current guides/User-Agent, and preserve older phase references only as explicitly historical context.

### A31 — P2: Referenced product/design context is not in the repository

**Evidence:** `.gitignore:34–37`; `docs/system-page.md:319–321`; local `PRODUCT.md` / `DESIGN.md`. `git ls-files PRODUCT.md DESIGN.md` returned no files.

The local files contain active product constraints and executable-token/design guidance, and tracked documents refer to them. They are ignored and untracked, so a clean clone/CI/contributor cannot read the same ground truth. This is a reproducibility problem, not merely a broken local link.

**Close when:** Track the intended shared product/design documentation or move its authoritative content into tracked guides and update references. Verify references from a clean checkout.

### A32 — P3: Oversized modules blur important boundaries

**Evidence:** `apps/api/app/api/storage_admin.py` (1,268 lines); `scripts/storage_manager.py` (823); `apps/web/src/LocalFiles.tsx` (1,194); `apps/web/src/App.tsx` (1,159); `apps/web/src/StorageAdministration.tsx` (879); `apps/web/src/AccountPage.tsx` (753).

The storage router contains schemas, request validation, setup ownership, job presentation, claims, history, grant mutations, and runtime filesystem verification. The host manager mixes approval checks, ACL preparation, copy/recovery, Compose control, polling, and service installation. Frontend modules combine routed state, async work, focus, edits, and presentation. System provisioning imports auth/storage router internals; host/API schemas and helpers are manually duplicated. Broad exception handling and state dictionaries make recovery transitions hard to inspect.

**Close when:** Refactor along real boundaries: typed contracts, transactional services, explicit lifecycle state machines, host execution/verification, routed frontend controllers, and focused presentation. Preserve regression coverage and keep thin API routes. Avoid refactoring away descriptor confinement or adding arbitrary host command surfaces.

### A33 — P3: Contracts/request handling can drift unnoticed

**Evidence:** `apps/api/app/api/auth.py:252–276`; `apps/api/app/api/storage_admin.py` unmodeled dict responses and `Report.result`; `apps/web/src/api.ts:117–125`; `apps/web/src/systemApi.ts:127–149`; `apps/web/src/storageAdminApi.ts:147–181`; `apps/web/src/tailscaleAdminApi.ts:39–63`; `apps/web/src/localStorageApi.ts:29–42`.

Several substantial endpoints return unmodeled dictionaries, contrary to the docs' blanket claim of explicit response schemas. Client types are hand-maintained assertions over JSON, not generated or runtime-validated contracts. Request wrappers differ in error normalization, status preservation, empty/unreadable-response handling, caching, and authorization recovery. Some assume `detail` is a string even though FastAPI commonly returns a validation array; users receive `[object Object]`-style errors. A20 is a concrete consequence of contract drift.

**Close when:** Add typed schemas for the control-plane responses, generate or systematically align client contracts, and centralize request/error/auth handling while preserving intentional secret redaction. Test structured 422s, non-JSON proxy errors, missing fields, and 204 responses.

### A34 — P3: Styling/formatting has accumulated overlapping implementations

**Evidence:** `apps/web/src/styles.css` (1,707 lines), `apps/web/src/redesign.css` (1,312); import order in `apps/web/src/main.tsx:3–11`; appearance metadata in `apps/web/index.html:33–68` and `apps/web/src/AppearanceControls.tsx:5–55`; byte/time formatting in `apps/web/src/App.tsx:1090–1125`, `apps/web/src/LocalFiles.tsx:71–79`, and `apps/web/src/systemApi.ts:152–173`.

Base styles, a later redesign layer, and surface styles repeatedly override shared controls/layout. Palette IDs/initial colors are maintained in HTML, runtime code, CSS, and local design documentation. Formatting helpers differ in precision/ranges, with A21 already demonstrating a defect. The build emits about **83 kB CSS** and **374 kB initial JS** before compression; that is a measurement, not proof of unacceptable performance. xterm is appropriately dynamically imported.

**Close when:** Consolidate shared structural/control rules and appearance metadata, retain one semantic token authority, and reuse tested measurement/date helpers. Measure loading/rendering on representative devices before setting performance targets. Keep existing high-contrast/focus/reduced-motion behavior intact.

### A35 — P2: Browser verification cannot be reproduced from tracked assets

**Evidence:** `docs/ui-ux-verification.md:18–35,57–69`; `.github/workflows/ci.yml`; `apps/web/package.json:6–12`.

The guide records extensive synthetic Chromium/axe matrices, but their fixtures, runner, reports, and screenshots are temporary `/tmp/opencode/*` artifacts. There is no tracked browser-test command/dependency/harness to rerun that matrix in a fresh clone. The ordinary frontend suite is jsdom, which cannot prove modal focus containment, geometry, actual history/navigation, WebSocket proxying, or physical-device behavior. The guide does correctly disclose synthetic/physical-device limitations.

**Close when:** Check in a bounded reproducible browser/axe harness and fixtures for core navigation, dialogs, terminal focus, viewport/theme states, and contract errors. Add actual HTTP/WebSocket-through-proxy acceptance separately from synthetic layout fixtures. Record stable evidence/artifact locations and a physical-device/assistive-technology checklist.

### A36 — P3: Manual/setup prerequisites are not consistently documented

**Evidence:** `docs/development.md:3–10`; `README.md:49–60`; `scripts/ark:86–101`; `scripts/storage_bootstrap.py:18–25`; `docs/local-storage.md:146–159`; `scripts/storage_setup.py:170–185,332–343`.

Development says host Python/Node are only optional, but supported `ark up` unconditionally invokes host Python, requires ACL utilities and a working systemd user bus, and provisions the helper. README mentions a manual no-systemd path, yet the standard `ark up` still fails its bootstrap requirement, and the storage guide lacks one clearly identified complete manual startup/enrollment procedure. `ARK_STORAGE_MANAGED_AREA` is read from the host process environment rather than forwarded from Compose, but no consistent example explains how to set it.

**Close when:** Publish one accurate prerequisites list and a complete owner-supervised deployment path, or explicitly limit supported automatic lifecycle to systemd. Explain export/invocation of host-only settings and user-service persistence across logout/reboot.

### A37 — P3: Bounded features still perform repeated expensive work

**Evidence:** `apps/api/app/services/local_storage.py:355–395`; `apps/api/app/api/storage_admin.py:538–655`; `apps/api/app/services/storage_access.py:61–78`; `apps/web/src/StorageAdministration.tsx:90–112`; `apps/web/src/SystemInformationPage.tsx:409–488`.

Each 100-item page rescans/stats/sorts up to 10,000 entries; a full listing repeats that work up to 100 times. Storage inventory loops roots while querying active jobs and recent history repeatedly, and grant/file authorization opens separate DB sessions multiple times per root. Administration polls every three seconds even when the browser document is hidden. Overview and Vitals return the same complete host payload/history, and snapshot inventory is retransmitted with every sample. These are avoidable costs in a small single-worker service.

**Close when:** Measure realistic 32-root/10,000-entry/large-account workloads, reuse per-request queries/authorization state, pause hidden-page polling, and design revision-safe pagination or caches with explicit invalidation. Preserve permission/freshness rechecks and avoid holding DB locks across slow filesystem work.

### A38 — P3: Small semantics/configuration decisions need closure

**Evidence and follow-up decisions:**

1. **Upload-limit units:** `apps/web/src/StorageAdministration.tsx:661–669` has `min="0.000001"` MiB, which is more than one byte; an effective one-byte policy displays a value below the input's minimum. The docs/API promise a 1-byte minimum. Use an exact unit/rounding scheme and test minimum values.
2. **Queued storage authorization:** `apps/api/app/models.py:115–126` stores a requester ID but no auth session; `apps/api/app/api/storage_admin.py:958–979,1014–1019` rechecks account/admin state, not logout/password-change session revocation. System jobs do bind `auth_id`. Decide and document whether queued storage changes are durable account intent after logout, or require a live submitting session. Already-started recovery must remain durable.
3. **Service/power policy:** `scripts/system_capabilities.py:29` exposes power only when both reboot and poweroff are authorized; schema/UI have one `power` flag. This cannot express restart-only delegation. Decide whether that is intentional and align owner docs/UI with it.
4. **Telemetry warm-up:** `scripts/system_collect.py:241–250` applies collector-wide warm-up to every process, although a newly discovered process has not yet had an interval CPU measurement. Use per-process warm-up if the first reading should be unavailable rather than zero.
5. **Session settings:** `apps/api/app/core/config.py:20–22` has no useful minimum-length/range validation for a configured signing secret or session age. Owner-controlled configuration is trusted, but invalid/weak values should fail with actionable setup errors rather than surprising runtime behavior.
6. **Deployment surface:** `compose.yaml:80–83,116–121` deliberately serves reload-enabled API/Vite source. Read-only checks returned 200 for `/src/App.tsx`, `/package.json`, and `/@fs/app/src/api.ts`. This is expected development behavior and exposes no identified secret in those paths, but authenticated app routes do not protect the development-server surface. Keep this boundary explicit and create separate production packaging before expanding deployment scope.
7. **Browser security headers:** Application HTML has no configured CSP/frame-ancestor policy, and there is no consistent application-wide nosniff/referrer policy in `apps/web/vite.config.ts` or the gateway. Download-specific protections are already present. Establish a supported browser-header baseline compatible with bundled assets, WebSockets, and development HMR; test framing and third-party resource behavior rather than assuming private network access supplies those protections.
8. **Dependency-install failure:** The web startup shell in `compose.yaml:116–121` proceeds to `exec npm run dev` if the conditional `npm ci` fails; it has no fail-fast shell setting. The web health check tests only the root HTML response. Fail startup explicitly on install/hash publication errors and verify representative JS/assets before calling a changed dependency environment healthy.

**Close when:** Each item is either corrected with a relevant regression or recorded as a deliberate supported limitation. Do not silently generalize the current private single-worker deployment into a hardened public service.

## Remediation order

1. **Repair security boundaries:** A01–A03; add the missing controlled-interleaving/PID/SELinux regression coverage.
2. **Repair durable control/recovery:** A09–A16, A18; make accepted versus dispatched versus unknown outcomes and scan freshness explicit.
3. **Repair user-facing correctness:** A17, A19–A22; verify deep links/history, expired authentication, partial telemetry, and low-rate formatting.
4. **Make the baseline enforceable:** A04–A08, A23–A28, A31, A35; dependency updates, budgets, retention, audit events, CI and recovery/browser acceptance.
5. **Reconcile docs and simplify:** A29–A30, A32–A34, A36–A38; perform behavior-preserving refactors after the critical regression floor exists.

## Closure policy and strengths to preserve

For every fixed finding, record the implementation commit, meaningful verification, and updated docs here or in a linked issue. A code edit alone does not close an integration-dependent claim. For accepted risks/limitations, record the deployment assumptions and revisit trigger rather than deleting the finding. Recheck dependencies against current advisory databases when updating them.

The audit did **not** establish a browser path-traversal/symlink escape, administrator bypass of another user's private file grants, raw Tailscale credential disclosure, arbitrary browser-selected host executable, public Funnel enablement, or a need for privileged API/Docker-socket mounts. The confinement, one-use attachment grants, secret handling, single-worker limits, no-active-file-preview posture, bounded normalized upstream handling, and explicit trust in the host owner should survive remediation. Host shell access already deliberately delegates the enrolled account's authority; it is not an Ark file-grant sandbox.
