# Ark Cloud

Ark Cloud is a self-hosted personal cloud control plane. It will provide one private,
normalized view over the systems and services running on Ark without replacing mature
specialized applications.

Version 0.2 includes the Phase 0 foundation, Phase 1 infrastructure integrations, and a Phase 2 Google Drive control-plane integration:

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
- Local session authentication and server-side status for the Google Drive storage provider

## Quick Start

Requirements: Docker Engine with Docker Compose.

```bash
cp .env.example .env
./scripts/ark up
```

Before the first start, replace the example database password in both
`POSTGRES_PASSWORD` and `ARK_DATABASE_URL`. The two values must match. Then open
<http://127.0.0.1:5173>.

`./scripts/ark up` builds and recreates the complete stack, applies migrations, and waits for
all health checks. It preserves named volumes, so changes to `.env` are applied without manually
choosing which containers to recreate. Use `./scripts/ark restart` for a fresh full restart and
`./scripts/ark down` for a safe shutdown.

```bash
./scripts/ark status
./scripts/ark health
./scripts/ark logs api
```

The lifecycle commands always force the web service onto loopback. Use Tailscale Serve for private
remote access. `./scripts/ark reset-data --confirm` is the only lifecycle helper that removes
named volumes and permanently deletes local PostgreSQL data.

The only published port is `127.0.0.1:5173`. In the mapping
`127.0.0.1:5173:5173`, the first address and port belong to Ark and the final port belongs
to the web container. PostgreSQL and the API have no host port; the web development server
proxies browser requests to them through Docker's private network.

To use the development UI from another device over Tailscale, keep `ARK_BIND_ADDRESS` set to
`127.0.0.1` and use Tailscale Serve on the Ark host. This keeps the Compose port off the host
network interfaces and works with the rootless Docker setup:

```bash
sudo tailscale serve --bg http://127.0.0.1:5173
tailscale serve status
```

Open the HTTPS URL shown by `tailscale serve status` from an authorized device on the tailnet.
Review Tailscale grants before enabling access. Do not use `0.0.0.0` or open router ports.

## Verify Health

```bash
curl http://127.0.0.1:5173/api/health
./scripts/ark status
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

Authenticated control-plane endpoints include:

- `GET /api/dashboard`: aggregated data used by the web dashboard
- `GET /api/system`: normalized runtime system metrics
- `GET /api/integrations`: health for every configured adapter
- `GET /api/tailscale/devices`: normalized Tailscale device status
- `GET /api/integrations/google-drive/status`: normalized Google Drive account and quota status

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
./scripts/ark up
```

The API calls Tailscale server-side when the dashboard requests device status. The token is
never sent to the browser. Verify the integration through the normalized endpoint:

```bash
curl http://127.0.0.1:5173/api/tailscale/devices
```

Tailscale access tokens expire after 1 to 90 days. The API sends the token only to the fixed
HTTPS Tailscale API origin and refuses redirects; it is never included in normalized API
responses or browser configuration. Use the shortest practical expiration. The security
guide documents the least-privilege path for continuous operation.

## Configure Google Drive

Google Drive is Ark Cloud's designated user-content storage provider and file-management system.
The current connection is optional at runtime and metadata-only: it shows the connected account
and storage quota, while all file operations remain in Drive. PostgreSQL stores Ark Cloud
control-plane state such as sessions and encrypted refresh tokens; it is not a user file store.
Follow the [Google Drive setup guide](docs/development.md#google-drive-setup) to create a Google
OAuth web client, then add its client ID, client secret, exact redirect URI, and a Fernet encryption
key only to the ignored `.env` file. Restart the stack, sign in, and use the dashboard's
**Connect Google Drive** action to authorize the account.

## Metric Scope

Version 0.2 reads metrics directly with `psutil` inside the unprivileged API container and
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

Ark Cloud is currently development software. It has a deliberately narrow local single-user
session boundary, not multi-user authorization or production hardening. Keep it private and do
not expose it to the public Internet.
