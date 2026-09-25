# Architecture

## Phase 0 Context

Ark Cloud starts as a modular monolith: one browser application, one API application, and
one PostgreSQL database. This is the smallest architecture that cleanly separates user
experience, application logic, and persistence while leaving room for integrations.

```text
Browser
   |
   | http://Ark:5173
   v
Vite web container  -- /api/* proxy -->  FastAPI container
                                          |      |       |
                                          |      |       +--> Google Drive API
                                          |      +----------> Tailscale API and psutil runtime metrics
                                          +-----------------> PostgreSQL
```

Compose creates two bridge networks:

- `app` connects the web client and API.
- `data` connects only the API and PostgreSQL and is marked `internal`.

Docker's internal DNS resolves service names such as `api` and `db`. Container addresses
may change when containers restart, so configuration uses stable service names rather than
IP addresses. PostgreSQL needs no published host port because only the API consumes it.

## Responsibilities

### Web

The React application owns presentation and browser interaction. It requests
`/api/health` from its own origin. Vite removes the `/api` prefix and forwards the request
to `http://api:8000/health` inside Docker. Browser code therefore knows nothing about
container addresses, and the same-origin request needs no permissive CORS policy.

### API

FastAPI owns normalized application behavior. Routes are thin and use explicit Pydantic
response schemas. SQLAlchemy owns connection pooling and database access; psycopg is the
PostgreSQL driver. `/health` runs `SELECT 1`, returns HTTP 200 only when the database is
reachable, and returns HTTP 503 when it is not.

The API advertises `/api` as its proxy root so generated OpenAPI documentation uses the
browser-visible paths while the internal route remains `GET /health`.

### Database

PostgreSQL is the system of record for Ark Cloud control-plane state, not user file content.
It stores local sessions, OAuth state, encrypted Google refresh tokens, and normalized cached
integration status. Google Drive is the source of truth for user files. An empty Alembic baseline
records the starting revision so every schema change can be reviewed, applied, and rolled back
consistently. Compose runs migrations before starting the API.

### Storage Boundaries

Ark Cloud uses separate storage boundaries for separate responsibilities:

- Google Drive is the designated user-content storage and file-management system.
- PostgreSQL contains only Ark Cloud control-plane state and derived metadata needed by the
  application. It does not contain file bodies or act as a second file store.
- The API container filesystem is operational storage only. Its reported disk usage describes the
  `api-runtime-view`, not Google Drive capacity or user-content storage.

Version 0.3 exposes normalized Drive connection/quota status and a searchable index of selected My
Drive metadata. Establishing Drive as the content source of truth does not grant Ark Cloud
permission to retrieve or modify file content.

## Configuration And Logs

Pydantic Settings reads `ARK_*` environment variables, converts their types, rejects
invalid enumerated values, and caches one validated settings object per process. Compose
loads local values from `.env`; Git ignores that file and tracks only `.env.example`.

Application-owned API events use JSON with fields such as level, timestamp, service, and
environment. Uvicorn access logs and Alembic migration output retain their standard
development formats. SQLAlchemy is configured to hide SQL parameter values from its logs.
Production logging can later unify the third-party formats without replacing application
instrumentation.

## Integration Boundary

Phase 1 introduces a small application-level integration contract:

```python
class Integration(Protocol):
    def health(self) -> IntegrationHealth: ...
    def summary(self) -> IntegrationSummary: ...
```

`SystemIntegration`, `TailscaleIntegration`, and `GoogleDriveIntegration` implement this
boundary. The dashboard route aggregates normalized summaries and health records; it does not
parse psutil, Tailscale, or Google payloads. Drive status is scoped to the authenticated local
principal. A failed or unconfigured adapter reports its own state without failing unrelated
integrations. Search is implemented as a principal-scoped Drive metadata capability; activity will
be added only when required.

### System Integration

The API uses psutil without root privileges. It collects hostname and OS labels from
validated settings plus kernel, uptime, CPU, memory, and filesystem usage visible to the
API process. Metrics are explicitly marked `api-runtime-view`. CPU, memory, and uptime can
come from host-global kernel views, while storage can describe the container overlay or
backing filesystem. They are useful operational signals, not exact host or cgroup metrics.

Version 0.2 deliberately does not mount `/`, `/proc`, the Docker socket, or privileged host
namespaces into the API. A future dedicated Ark agent can expose a narrow authenticated
socket containing normalized host metrics. The API's System adapter can then change data
sources without changing routes or React components.

Phase 5 adds an authenticated Runtime Information page backed by `GET /system/information` (browser
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
GPU and sensor data do not fail the page. The page loads independently of the dashboard, and there is
no container-only process view
or process endpoint. No host filesystem or Docker socket is mounted.

### Tailscale Integration

The Tailscale adapter calls `GET /api/v2/tailnet/{tailnet}/devices` at the fixed HTTPS
Tailscale API origin with a server-held access token and a five-second timeout. It refuses
redirects so the authorization header cannot be forwarded to another origin, limits response
size, maps only approved fields, and never returns raw third-party payloads. Device status
uses `connectedToControl` when Tailscale provides it. For older or partial responses without
that boolean, Ark Cloud falls back to a `lastSeen` window of five minutes.

This server-side integration is independent of browser network access. The web container is
published on loopback by default, while Tailscale Serve can proxy that local port to authorized
tailnet devices. The development environment uses rootless Docker, so publishing the port
directly on the host's `100.x.y.z` Tailscale address is not supported. Tailscale provides a
network boundary only; it does not replace Ark Cloud application authentication.

## Deferred Decisions

- Multi-user authentication and authorization require a dedicated design review. Version 0.2 has
  a deliberately narrow local single-user session boundary.
- Caddy and HTTPS belong to deployment work, not the local scaffold.
- Async database access is not justified by the Phase 0 workload. FastAPI safely runs the
  synchronous route in its worker thread pool.
- Redis, workers, queues, WebSockets, and microservices have no current use case.

## Google Drive Integration

Google Drive is Ark Cloud's primary user-content storage provider and remains the file-management
system. The API uses a server-side OAuth web flow to request metadata-only access, encrypts its
refresh token before PostgreSQL storage, and caches normalized account/quota status. Browser
clients receive no Google credentials or raw upstream responses. Ark Cloud does not upload,
download, export, modify, or proxy Drive file content.

### Drive Catalog And Search

After a successful OAuth connection, the API synchronously catalogs selected metadata for files
owned by the connected account in My Drive. The initial sync captures a Drive change token,
enumerates bounded pages of metadata, reconciles changes that occurred during enumeration, and
atomically replaces the principal's catalog. Later user-triggered syncs consume the My Drive changes
feed to upsert or remove individual records. A failed or time-limited sync preserves the last usable
catalog and records a normalized error for the dashboard.

PostgreSQL stores only Drive file IDs, names, MIME types, sizes, Drive timestamps, starred state,
normalized parent relationships, derived Drive links, indexing timestamps, and synchronization
state. It also stores principal-scoped local preferences such as saved searches and pinned folder
IDs. It does not store file bodies, previews, descriptions, owners, permissions, or raw Google
payloads.

### Drive Workspace

Version 0.4 resolves Drive's opaque root folder ID during synchronization and normalizes it to a
local `root` sentinel. A parent-edge table supports folder listings and bounded breadcrumbs without
database-specific JSON queries. Workspace listings support metadata filters and deterministic
sorting. Opaque pagination cursors bind the filter set and authenticated principal to a catalog
revision, so a concurrent synchronization causes the next page to restart rather than mixing two
catalog snapshots.

Manual synchronization remains synchronous and bounded. Each attempt records its mode, phase,
progress, result, and normalized error. Incremental changes atomically update the catalog, parent
edges, activity, change token, and revision. An expired change token switches the same attempt to
one full recovery scan; failure preserves the prior usable catalog. Activity is bounded metadata
observed during synchronization, not a complete or real-time Google Drive audit log.

Saved searches and pins are local control-plane state. Storage reports are derived from indexed
metadata and are explicitly advisory because Google-native files may not report a size and account
quota can include data outside the catalog. Results and reports link directly to Google Drive.

Scheduled synchronization remains deferred because it needs durable job ownership, locking,
shutdown recovery, backoff, and quota controls. Shared files and shared drives remain excluded
pending explicit visibility and per-drive cursor rules. Write actions remain excluded pending OAuth
scope, confirmation, audit, conflict, and recovery reviews. Version 0.4 introduces no scheduler,
background worker, Drive write scope, or content proxy.
