# Ark Cloud

Ark Cloud is a self-hosted personal cloud control plane. It will provide one private,
normalized view over the systems and services running on Ark without replacing mature
specialized applications.

Version 0.1 includes the Phase 0 foundation and the first Phase 1 control-plane features:

- React 19, TypeScript, and Vite web client
- FastAPI and SQLAlchemy API
- PostgreSQL 18 database
- Alembic migration baseline
- Docker Compose development environment
- Database-aware platform health and structured application logs
- Normalized integration abstraction
- Non-root CPU, memory, storage, uptime, OS, and kernel telemetry
- Optional server-side Tailscale device integration
- Responsive infrastructure dashboard with partial-failure states
- Backend and frontend tests, linting, formatting, and CI smoke tests

## Quick Start

Requirements: Docker Engine with Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Before the first start, replace the example database password in both
`POSTGRES_PASSWORD` and `ARK_DATABASE_URL`. The two values must match. Then open
<http://127.0.0.1:5173>.

`docker compose up` creates and starts the services. `--build` rebuilds the application
images when source or dependencies change. Press `Ctrl+C` to stop attached services, or
run `docker compose down` from another terminal.

The only published port is `127.0.0.1:5173`. In the mapping
`127.0.0.1:5173:5173`, the first address and port belong to Ark and the final port belongs
to the web container. PostgreSQL and the API have no host port; the web development server
proxies browser requests to them through Docker's private network.

To use the development UI from another device over Tailscale, first restrict its web port to
explicitly trusted devices with Tailscale grants. Then set `ARK_BIND_ADDRESS` in `.env` to
Ark's Tailscale IP and restart Compose. Do not use `0.0.0.0` unless access from every host
interface is intentional and protected by firewall rules.

## Verify Health

```bash
curl http://127.0.0.1:5173/api/health
docker compose ps
```

Expected response:

```json
{
  "status": "healthy",
  "service": "ark-cloud-api",
  "database": "connected"
}
```

OpenAPI JSON is available through the proxy at
<http://127.0.0.1:5173/api/openapi.json>, and interactive API documentation is at
<http://127.0.0.1:5173/api/docs>.

Phase 1 read-only endpoints are:

- `GET /api/dashboard`: aggregated data used by the web dashboard
- `GET /api/system`: normalized runtime system metrics
- `GET /api/integrations`: health for every configured adapter
- `GET /api/tailscale/devices`: normalized Tailscale device status

## Configure Tailscale

Tailscale is optional. Without credentials, its dashboard panel reports `Not configured`
while every other feature continues to work.

Create an API access token in the Tailscale admin console, then add it only to your ignored
`.env` file:

```dotenv
ARK_TAILSCALE_API_KEY=tskey-api-your-token
ARK_TAILSCALE_TAILNET=-
```

The shorthand tailnet ID `-` uses the tailnet associated with the token. Restart the API
after changing configuration:

```bash
docker compose up --build -d --wait
```

Tailscale access tokens expire after 1 to 90 days. The API sends the token only to the fixed
HTTPS Tailscale API origin and refuses redirects; it is never included in normalized API
responses or browser configuration. Use the shortest practical expiration. The security
guide documents the least-privilege path for continuous operation.

## Metric Scope

Version 0.1 reads metrics directly with `psutil` inside the unprivileged API container and
labels them `api-runtime-view`. CPU, memory, and uptime can reflect host-global kernel data,
while storage can reflect the container overlay or backing filesystem. These are useful
signals, but they are not exact host or cgroup measurements. No Docker socket, host root, or
privileged namespace is mounted. A narrow, authenticated local system agent is the planned
path to exact host telemetry.

## Quality Checks

With images built, run backend checks in the reproducible API container:

```bash
docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api pytest
docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api ruff check .
docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api ruff format --check .
```

Run frontend checks from `apps/web` after `npm install`:

```bash
npm test
npm run lint
npm run format:check
npm run build
```

`--rm` removes a one-off check container after it exits. `--no-deps` avoids starting
PostgreSQL because these unit tests use an isolated in-memory SQLite database; live
PostgreSQL connectivity is verified by the running stack.

## Repository Layout

```text
apps/api/          FastAPI application, migrations, and backend tests
apps/web/          React application and frontend test
docs/              Architecture, development, roadmap, and security notes
compose.yaml       Local service topology
.env.example       Safe configuration template
```

## Documentation

- [Architecture](docs/architecture.md)
- [Development](docs/development.md)
- [Roadmap](docs/roadmap.md)
- [Security](docs/security.md)

Ark Cloud is currently development software. Authentication is intentionally not invented
as part of the scaffold, so keep it private and do not expose it to the public Internet.
