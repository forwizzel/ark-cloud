# Ark Cloud

Ark Cloud is a self-hosted personal cloud for accessing files on your host and reviewing its
systems and services from a private browser session.

Version 0.9 focuses on local host storage with private remote access, local account management,
infrastructure status, detailed system information, and an accessible interface:

- React 19, TypeScript, and Vite web client
- FastAPI and SQLAlchemy API
- PostgreSQL 18 database
- Alembic migration baseline
- Docker Compose development environment
- Database-aware platform health and structured application logs
- Normalized integration abstraction
- Non-root CPU, memory, storage, uptime, OS, and kernel telemetry
- Optional UI-managed dedicated Tailscale node, private Serve HTTPS, and device inventory
- Responsive infrastructure dashboard with partial-failure states
- Backend and frontend tests, linting, formatting, and CI smoke tests
- Local session authentication with account-scoped storage access
- In-app local username/password changes, administrator-managed invitations, and local recovery
- Private local account folders and owner-assigned existing host directories
- Administrator UI for connecting host folders, assignments, access checks, base relocation and upload policy
- Explicit, account-persisted Local Files starting-folder preferences
- Local browsing, streaming uploads/downloads, folders, rename, within-location moves, and deletion
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
Tailscale is optional; local access works without it.

After creating your administrator, Ark opens the **Administration** landing page. Open **Storage →
Add location**, choose a new or existing server folder, its private/shared purpose and accounts,
then press **Connect**. Ark configures narrow filesystem access and verifies the running API
automatically. Normal deployment startup enables the owner-run helper and provisions a dedicated
`~/Ark-Locations` area for additional locations; existing `Ark-Files` and registered paths are preserved.
Locations, access/configuration/activity, Settings, Diagnostics and Users occupy separate pages.

Linux, Python 3.10+, a local Docker daemon, systemd user services and `setfacl` (Fedora's `acl`
package) are needed. The helper runs as the deployment owner; the API remains unprivileged.
Without systemd, use `storage setup --no-install` and supervise `storage manager run` as that owner.
Failed connections have a **Repair connection** action that resumes the same registration and
re-evaluates permissions. Selecting a registered directory never creates a duplicate location.
Set the maximum file size in Administration without restarting. **Set as starting folder** in
Local Files is a separate account preference; opening a location does not change it.

Each location offers **Manage → Access**: choose **No access**, **Read-only**, or **Read & write**
for accounts by username. `Ark-Files` keeps each account's private folder isolated. To share the
same files with selected accounts, add a separate **Shared files** location and select its users.
Existing access is preserved during upgrade; later accounts require an explicit grant. Permission
changes take effect without restarting containers and preserve files when access is revoked.

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

The lifecycle commands always force the web service onto loopback. Use UI-managed Tailscale Serve for private
remote access. `./scripts/ark reset-data --confirm` is the only lifecycle helper that removes
named volumes and permanently deletes local PostgreSQL data, managed Tailscale identity, and secrets.

The only published port is `127.0.0.1:5173`. In the mapping
`127.0.0.1:5173:5173`, the first address and port belong to Ark and the final port belongs
to the web container. PostgreSQL and the API have no host port; the web development server
proxies browser requests to them through Docker's private network.

For private remote access, open **Administration → Tailscale**, enter a Tailscale API key,
and press **Connect**. Default Compose runs a dedicated userspace Tailscale service; no host
Tailscale installation or host networking privileges are needed. Ark creates its own node and
configures private Serve HTTPS while `ARK_BIND_ADDRESS` stays `127.0.0.1`.
Open the HTTPS URL shown in the UI from a device running the Tailscale app and signed in to
an authorized Tailscale account. See [Configure Tailscale](#configure-tailscale) below.

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
- `GET /api/storage/roots`: authorized local storage locations
- `GET /api/storage/{id}/items`: bounded local directory listing
- `/api/storage/{id}/*`: authenticated local file operations
- `GET /api/admin/storage`: administrator storage configuration and job status
- `GET /api/admin/tailscale`: administrator private-access configuration and status

## Configure Tailscale

Tailscale is optional; local access works without a connection.

1. Create an API key in the Tailscale admin console using an account with device-create rights
   in the intended tailnet.
2. Open **Administration → Tailscale**, enter the API key, and press **Connect**. Ark validates
   the credentials, persists them encrypted, mints a one-use auth key, joins a dedicated node,
   and configures Tailscale Serve HTTPS automatically. Saving needs no `.env` edits, shell
   commands, or stack restart.
3. If a tailnet requirement needs approval, follow the HTTPS Tailscale approval link shown in
   the UI. Ark resumes automatically after approval. No manual auth-key creation or Serve
   command is required.
4. Open the displayed HTTPS address from an authorized tailnet device. Clients still need
   the Tailscale app and account login, followed by their Ark Cloud login. Serve is private;
   Ark does not enable Funnel or public access.

**Disable remote access** stops the managed Serve endpoint while retaining the connection,
credentials, and node identity. **Disconnect** removes the saved credentials and logs out
the managed node; it also explicitly disables legacy environment fallback. Both leave
<http://127.0.0.1:5173> available locally.

Existing `ARK_TAILSCALE_API_KEY` / `ARK_TAILSCALE_TAILNET` configuration remains a read-only
inventory fallback until credentials are saved in the UI or an explicit Disconnect disables
it. It does not provision a node. An API key's expiry can interrupt inventory or provisioning
without disconnecting an already-joined node's Serve endpoint; replace the key in the UI.

Existing host-installed Tailscale Serve is independent: Ark neither adopts nor removes it.
An old manual host endpoint remains outside UI control until the owner retires it. See
[migration and recovery](docs/development.md#use-tailscale-for-remote-access) for details,
including backups of PostgreSQL and the `tailscale_secrets`, `tailscale_controller`, and
`tailscale_state` named volumes.

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

Ark Cloud is currently development software with local accounts and account-scoped storage
permissions. Keep it private and do not expose it to the public Internet.
