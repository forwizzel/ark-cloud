# Architecture

## Current Topology

Ark Cloud is a modular monolith: one browser application, one API application, and
one PostgreSQL database. This is the smallest architecture that cleanly separates user
experience, application logic, and persistence while leaving room for integrations.

```text
Browser (127.0.0.1:5173 locally; HTTPS via Tailscale Serve remotely)
   |
   | same-origin /api/*
   v
 Vite web container  -- /api/* proxy -->  FastAPI container
                                           |      |       |
                                           |      |       +--> owner-mounted host directories
                                           |      +----------> Tailscale API and psutil runtime metrics
                                           +-----------------> PostgreSQL
```

Compose creates two bridge networks:

- `app` connects the web client, API, and dedicated userspace Tailscale service.
- `data` connects only the API and PostgreSQL and is marked `internal`.

Docker's internal DNS resolves service names such as `api` and `db`. Container addresses
may change when containers restart, so configuration uses stable service names rather than
IP addresses. PostgreSQL needs no published host port because only the API consumes it.

## Responsibilities

### Web

The React application owns presentation and browser interaction. It requests `/api/*` from
its own origin: session state, the dashboard, Local Files, Administration, and System. Vite
removes the `/api` prefix and forwards requests to `http://api:8000` inside Docker. The
browser-facing `/api/health` uses the same proxy path. Browser code therefore knows nothing
about container addresses, and same-origin requests need no permissive CORS policy.

Appearance is entirely browser-side. Light/dark and high-contrast preferences follow device
settings until explicitly changed, then persist in localStorage. The selected palette is applied
before React loads; neither PostgreSQL nor the API stores appearance preferences.

### API

FastAPI owns normalized application behavior. Routes are thin and use explicit Pydantic
response schemas. SQLAlchemy owns connection pooling and database access; psycopg is the
PostgreSQL driver. `/health` runs `SELECT 1`, returns HTTP 200 only when the database is
reachable, and returns HTTP 503 when it is not.

The API advertises `/api` as its proxy root so generated OpenAPI documentation uses the
browser-visible paths while the internal route remains `GET /health`.

### Database

PostgreSQL is the system of record for Ark Cloud control-plane state, not user file content.
It stores local users, sessions, storage registrations and grants, provisioning jobs, account
starting-folder preferences, encrypted UI-saved Tailscale credentials and desired connection state;
the Tailscale encryption key is kept separately in the `tailscale_secrets` named volume.
The host filesystem is the source of truth for file content. An Alembic migration history tracks
schema changes; Compose applies migrations before
starting the API.

### Storage Boundaries

Ark Cloud uses separate storage boundaries for separate responsibilities:

- Local host directories are the content provider.
- PostgreSQL contains only Ark Cloud control-plane state and metadata needed by the
  application. It does not contain file bodies or act as a second file store.
- The API container overlay is operational storage only. Dedicated owner-configured bind mounts
  hold local user content; missing mounts never fall back to the overlay. Runtime disk usage describes
  the `api-runtime-view`, not exact host capacity or user-content storage.

## Configuration And Logs

Pydantic Settings reads `ARK_*` environment variables, converts their types, rejects
invalid enumerated values, and caches one validated settings object per process. Compose
loads local values from `.env`; Git ignores that file and tracks only `.env.example`.

Application-owned API events use JSON with fields such as level, timestamp, service, and
environment. Uvicorn access logs are disabled to keep filename-bearing request URLs out of logs;
Alembic retains its standard output. SQLAlchemy hides SQL parameter values from its logs.
Production logging can later unify the third-party formats without replacing application
instrumentation.

## Integration Boundary

Phase 1 introduces a small application-level integration contract:

```python
class Integration(Protocol):
    def health(self) -> IntegrationHealth: ...
    def summary(self) -> IntegrationSummary: ...
```

`SystemIntegration` and `TailscaleIntegration` implement this
boundary. The dashboard route aggregates normalized summaries and health records; it does not
parse psutil or Tailscale payloads. A failed or unconfigured adapter reports its own state without
failing unrelated integrations. Local file operations are a separate account-scoped filesystem
capability rather than an external metadata catalog.

### System Integration

The API uses psutil without root privileges. It collects hostname and OS labels from
validated settings plus kernel, uptime, CPU, memory, and filesystem usage visible to the
API process. Metrics are explicitly marked `api-runtime-view`. CPU, memory, and uptime can
come from host-global kernel views, while storage can describe the container overlay or
backing filesystem. They are useful operational signals, not exact host or cgroup metrics.

System configuration lives in Administration → System. Its Connect action queues a separately
persisted lifecycle job for the existing deployment host manager, which discovers approved
shells/services, prepares dependencies, enrolls and starts the agent, and waits for authenticated
readings. Settings/disconnect follow the same typed channel; no routine manual enrollment command
or API privilege elevation is required.

The API deliberately does not mount `/`, `/proc`, the Docker socket, or privileged host
namespaces into the API. The optional owner-enrolled System agent collects actual host metrics
and connects outward through the loopback web proxy. `/system/overview` and `/system/vitals`
provide host snapshots separately from the existing runtime adapter. See
[System host setup](system-host.md) for enrollment and transport limits.

The legacy runtime information contract is backed by `GET /system/information` (browser
path `/api/system/information`). The existing `/system` and dashboard summaries remain compact.
Detailed information is collected on demand and divided into identity, compute, memory, storage,
and optional sensor sections. Each section reports availability and source; configured hostname/OS
labels are not measurements, host boot uptime and kernel CPU/memory views may reflect the host,
and storage usage refers only to the configured path. The CPU model is read from the bounded
container-visible `/proc/cpuinfo` interface when available.

Compute optionally detects up to eight GPUs using PCI IDs visible in `/sys/class/drm`. A matching
NVIDIA driver model under `/proc/driver/nvidia/gpus` provides a friendly name where available;
otherwise the adapter reports vendor and PCI ID. GPU visibility does not imply device access or
utilization telemetry. Temperature readings from psutil have normalized labels (CPU package,
memory module, ACPI thermal zone, and recognized motherboard sensor locations) and retain their
source identifiers; unknown sensors use a generic label, not a guessed physical location. Unavailable
GPU and sensor data do not fail the page. System loads independently of the dashboard. Its new
administrator process view comes from the enrolled host agent, not container process inspection.
The API brokers real host PTYs using authenticated same-origin WebSockets, single-use attachment
grants and bounded in-memory queues. Typed service/process/power jobs are persisted in PostgreSQL;
the agent journals execution before acting to prevent replay. Host information remains readable
without administrator privileges; detailed processes, services and terminal access are restricted.
The broker supports one API worker; active sessions and rolling history do not survive API restart.
Phase 5 introduced no host content mounts;
Phase 8's explicit content mounts do not expand telemetry collection or provide Docker socket access.

### Tailscale Integration

The Tailscale adapter calls `GET /api/v2/tailnet/{tailnet}/devices` at the fixed HTTPS
Tailscale API origin with a server-held access token and a five-second timeout. It refuses
redirects so the authorization header cannot be forwarded to another origin, limits response
size, maps only approved fields, and never returns raw third-party payloads. Device status
uses `connectedToControl` when Tailscale provides it. For older or partial responses without
that boolean, Ark Cloud falls back to a `lastSeen` window of five minutes.

Default Compose also runs a dedicated userspace Tailscale service. It requires no host
installation, TUN device, privileged networking, or Docker socket. The service configures
private Serve HTTPS to the web container over the `app` network; the host's published web
port remains `127.0.0.1:5173`. Funnel is not enabled.

Administrators connect through **Administration → Tailscale** with an API key whose user has
device-create rights. The API validates and encrypts persisted credentials, mints a one-use
auth key, and lets the dedicated controller reconcile joining the node and enabling Serve.
No environment edit or command is needed to save. An unmet tailnet requirement exposes only
an approved HTTPS vendor approval link; reconciliation resumes automatically after approval.
The browser receives normalized state, not saved credentials or raw upstream/command output.

The controller token persists in `tailscale_controller`, while node identity persists in
`tailscale_state`. Together with `tailscale_secrets` and PostgreSQL, these volumes form the
managed connection's recovery set; see [backup and recovery](development.md#back-up-and-recover-the-managed-node).

Disabling remote access stops managed Serve while preserving credentials and node identity.
Disconnect removes saved credentials, logs out the managed node, and explicitly disables
legacy environment fallback. Both preserve local loopback access. Existing environment key
and tailnet settings support read-only inventory only until a UI save or explicit Disconnect.
API key expiry can impair inventory/provisioning without disconnecting an already-joined
Serve endpoint; administrators replace it in the UI.

Independent host Serve installations are neither adopted nor removed. Their endpoints remain
outside UI control and must be retired separately during migration. Tailscale clients still
need the app and an authorized account login; the network boundary does not replace Ark Cloud
application authentication.

## Local Storage (v0.9)

`app/services/local_storage.py` reads a bounded, read-only host manifest. A managed mount gives each
immutable user ID a private directory; shared mounts require explicit account grants.
PostgreSQL persists registrations, grants, jobs, and preferences. `scripts/storage.py` provisions a new directory or registers an
existing one, records device/inode identity, and generates `compose.storage.yaml`. Lifecycle helpers
load the override; isolated API unit checks use base Compose without content mounts.

The `/storage` API streams file bytes and uses Linux `openat2` for no-symlink/no-mount-crossing
resolution. `renameat2(RENAME_NOREPLACE)` publishes uploads and moves without clobbering targets.
Lists are bounded to 10,000 entries, returned 100 at a time with directory-revision validation.
Writes carry current item revisions, serialize their final mutations within the supported single
API process, and retain descriptors instead of reopening unchecked paths. Deletion removes only
files or empty folders. Local Files loads independently of dashboard availability.
See [Local storage](local-storage.md) for deployment, trust assumptions, limits, and recovery.

## Deferred Decisions

- Version 0.7 stores local users and Argon2id password hashes in PostgreSQL. Stable user IDs scope
  sessions and private folders; usernames can change without changing ownership. The first
  administrator uses a one-time locally generated code, and admins invite additional users.
  Each account manages its own credentials in the app. A terminal-only owner CLI handles recovery.
- A general-purpose reverse proxy such as Caddy and production HTTPS remain deployment work;
  Tailscale Serve provides HTTPS for private remote development.
- Async database access is not justified by the current workload. FastAPI safely runs synchronous
  routes in its worker thread pool.
- Redis, workers, queues, WebSockets, and microservices have no current use case.
