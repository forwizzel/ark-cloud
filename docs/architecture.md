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
                                          |      |       +--> Tailscale API
                                          |      +----------> psutil runtime metrics
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

PostgreSQL is the system of record. Phase 0 creates no domain tables because none are yet
needed. An empty Alembic baseline records the starting revision so every future schema
change can be reviewed, applied, and rolled back consistently. Compose runs migrations
before starting the API.

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

`SystemIntegration` and `TailscaleIntegration` implement this boundary. The dashboard route
aggregates normalized summaries and health records; it does not parse psutil or Tailscale
payloads. A failed or unconfigured adapter reports its own state without failing unrelated
integrations. Capabilities such as activity and search will be added only when required.

### System Integration

The API uses psutil without root privileges. It collects hostname and OS labels from
validated settings plus kernel, uptime, CPU, memory, and filesystem usage visible to the
API process. Metrics are explicitly marked `api-runtime-view`. CPU, memory, and uptime can
come from host-global kernel views, while storage can describe the container overlay or
backing filesystem. They are useful operational signals, not exact host or cgroup metrics.

Version 0.1 deliberately does not mount `/`, `/proc`, the Docker socket, or privileged host
namespaces into the API. A future dedicated Ark agent can expose a narrow authenticated
socket containing normalized host metrics. The API's System adapter can then change data
sources without changing routes or React components.

### Tailscale Integration

The Tailscale adapter calls `GET /api/v2/tailnet/{tailnet}/devices` at the fixed HTTPS
Tailscale API origin with a server-held access token and a five-second timeout. It refuses
redirects so the authorization header cannot be forwarded to another origin, limits response
size, maps only approved fields, and never returns raw third-party payloads. Device status
uses `connectedToControl` when Tailscale provides it. For older or partial responses without
that boolean, version 0.1 falls back to a `lastSeen` window of five minutes.

## Deferred Decisions

- Authentication requires a dedicated design review before remote use beyond trusted
  development access.
- Caddy and HTTPS belong to deployment work, not the local scaffold.
- Async database access is not justified by the Phase 0 workload. FastAPI safely runs the
  synchronous route in its worker thread pool.
- Redis, workers, queues, WebSockets, and microservices have no current use case.
