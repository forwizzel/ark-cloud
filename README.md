# Ark Cloud

Ark Cloud is a self-hosted personal cloud for accessing files on your host and reviewing its
systems and services from a private browser session.

Version 0.9 adds local host file storage alongside local account management, infrastructure integrations,
metadata-only Google Drive workspace, detailed system information, and updated interface:

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
- In-app local username/password changes, administrator-managed invitations, and local recovery
- Owned My Drive folder browsing, filtered search, recent and starred views
- Saved searches, pinned folders, advisory storage insights, and sync-observed activity
- Observable synchronization with history, retries, and expired-change-token recovery
- Private local account folders and owner-assigned existing host directories
- Administrator UI for connecting host folders, assignments, access checks, base relocation and upload policy
- Explicit, account-persisted Local Files starting-folder preferences
- Local browsing, streaming uploads/downloads, folders, rename, within-location moves, and deletion
- Direct Google Drive links for every catalog result; Ark Cloud never proxies Drive file content
- Dedicated System Information page with sensor, compute, identity, and storage details scoped to
  the API runtime view
- Light/dark and high-contrast appearance controls, with browser-local preferences

## Quick Start

Requirements: Docker Engine with Docker Compose.

```bash
cp .env.example .env
./scripts/ark up
```

Before the first start, replace the example database password in both
`POSTGRES_PASSWORD` and `ARK_DATABASE_URL`. The two values must match. After `./scripts/ark up`,
run `./scripts/ark bootstrap` to receive a 15-minute setup code. Open
<http://127.0.0.1:5173> and create the first administrator in the browser using that code.
Username and password changes are available under **Account**; admins invite and manage local
users under **Administration → Users**. See [Local accounts](docs/development.md#local-accounts) for upgrading and recovery.
Google Drive and Tailscale are optional.

After creating your administrator, Ark opens **Administration → Local Storage**. Choose
**Create my cloud storage** in the setup wizard. From the ArkCloud repository on the host,
run this as the account that runs the deployment:

```bash
./scripts/ark storage setup
```

Ark creates `~/Ark-Files` for you, configures isolated private account folders, installs the host
helper, applies mounts and verifies access. Return to the wizard and choose **Open my files**.
You do not need to create a directory or complete a second UI configuration step. Existing
unregistered folders are never overwritten; use **Connect an existing folder** for those, or
`./scripts/ark storage setup --path /a/new/directory` to create a different new base.

Linux, Python 3.10+, a local Docker daemon, systemd user services and `setfacl` (Fedora's `acl`
package) are needed. The helper runs as the deployment owner; the API remains unprivileged.
Without systemd, use `storage setup --no-install` and supervise `storage manager run` as that owner.
Setup resumes recorded work; repeating it verifies the existing base without replacing files.
Set the maximum file size in Administration without restarting. **Set as starting folder** in
Local Files is a separate account preference; opening a location does not change it. No Google
credentials are required.

The retained storage CLI remains available for owner recovery and installations without a manager;
see [Local storage](docs/local-storage.md) for its reference and advanced host details.

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
- `GET /api/system/information`: detailed runtime information with per-section scope and availability
- `GET /api/integrations`: health for every configured adapter
- `GET /api/tailscale/devices`: normalized Tailscale device status
- `GET /api/integrations/google-drive/status`: normalized Google Drive account and quota status
- `GET /api/integrations/google-drive/items`: filtered, sorted Drive metadata workspace listing
- `GET /api/integrations/google-drive/folders/{id}`: normalized folder and breadcrumb metadata
- `GET /api/integrations/google-drive/insights`: advisory quota, type, large-file, and stale-file data
- `GET /api/integrations/google-drive/saved-searches`: principal-scoped local search preferences
- `GET /api/integrations/google-drive/pinned-locations`: principal-scoped local folder shortcuts
- `GET /api/integrations/google-drive/catalog/status`: normalized sync state and progress
- `GET /api/integrations/google-drive/catalog/syncs`: bounded synchronization history
- `POST /api/integrations/google-drive/catalog/sync`: CSRF-protected metadata sync or recovery
- `GET /api/integrations/google-drive/activity`: activity observed during catalog synchronization
- `GET /api/search?q=...`: filtered, paginated, principal-scoped catalog search

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

Google Drive is an optional external metadata workspace; local host storage is the default file provider.
The connection is optional at runtime and metadata-only: it shows the connected account and quota,
then catalogs selected metadata for files owned by that account in My Drive. The first catalog sync
runs after OAuth connection; later syncs consume Drive's changes feed and can be started from the
Drive Workspace. Ark Cloud can browse folders, filter metadata, save local workspace preferences,
and report advisory storage insights. All file operations remain in Drive. PostgreSQL stores Ark
Cloud control-plane state, encrypted refresh tokens, and the derived metadata index; it is not a
user file store.
Follow the [Google Drive setup guide](docs/development.md#google-drive-setup) to create a Google
OAuth web client, then add its client ID, client secret, exact redirect URI, and a Fernet encryption
key only to the ignored `.env` file. Restart the stack, sign in, and use the dashboard's
**Connect Google Drive** action to authorize the account.

## Metric Scope

Ark Cloud reads metrics with `psutil` inside the unprivileged API container and labels them
`api-runtime-view`. The dedicated **System Information** page separates configured identity
labels, kernel views, configured-path storage, optional GPU detection, and temperatures labeled
by sensor purpose with their original identifiers shown as context. GPU models may be visible
through DRM and NVIDIA driver metadata even without device access; missing GPUs or sensors show
as unavailable. CPU, memory, and uptime can reflect host-global kernel data, while storage can
reflect the container overlay or backing filesystem. These signals are not exact host or cgroup
measurements. No Docker socket, host root, or privileged namespace is mounted. A narrow,
authenticated local system agent is the planned path to exact host telemetry.

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
apps/web/          React application and frontend tests
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
