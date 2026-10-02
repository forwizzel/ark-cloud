# Ark Cloud

**Your files. Your server. Private access from wherever you are.**

Ark Cloud is a self-hosted personal cloud with a browser-based file workspace, local accounts,
and optional private remote access through Tailscale. Keep file content on your own Linux
server, choose who can access it, and manage storage and accounts from one interface.

**v1.0 · MVP** brings together local file management, private and shared storage, UI-managed
Tailscale access, and a dashboard for service health and runtime system information.

[Get started](#get-started) · [Features](#features) · [Remote access](#private-remote-access) ·
[Documentation](#documentation) · [Report an issue](https://github.com/forwizzel/ark-cloud/issues)

## Features

- **A file workspace in your browser.** Browse, upload, download, create folders, rename,
  move items within a location, and delete files or empty folders. Choose a starting folder
  that is saved to your account.
- **Private folders and shared locations.** Give each account an isolated private folder,
  or share a host directory with selected users. Set access to **No access**, **Read-only**,
  or **Read & write** per account.
- **Storage administration without leaving the app.** Connect new or existing host folders
  within owner-approved areas, manage access, adjust the upload limit, inspect activity,
  and repair failed connections.
- **Private HTTPS access through Tailscale.** Connect from Administration to provision a
  dedicated Tailscale node and Serve endpoint. No host Tailscale installation is required.
- **Local accounts you control.** Create the first administrator with a one-time setup code,
  invite users, manage roles, and change usernames and passwords. Terminal recovery is available
  if an administrator cannot sign in.
- **Service health and system information.** Check database and integration status, view
  Tailscale devices, and inspect CPU, memory, storage, uptime, and available sensor metadata.
- **An adaptable interface.** Responsive layouts, keyboard access, light and dark themes,
  high-contrast options, and reduced-motion support.

File content lives in host directories, not PostgreSQL. The database stores accounts,
permissions, settings, and other control-plane state.

## Get started

### Requirements

Use a Linux host with:

- Git, Bash, and `curl`.
- Docker Engine and Docker Compose v2, with access to a local Docker daemon.
- Python 3.10+ for the host storage helpers.
- `setfacl` from your distribution's `acl` package and systemd user services for automatic
  storage-manager setup.

The storage manager runs as the deployment owner and prepares access only within approved
host areas. The API container remains unprivileged. For hosts without systemd, see the
[manual storage-manager setup](docs/local-storage.md).

### 1. Clone and configure

```bash
git clone https://github.com/forwizzel/ark-cloud.git
cd ark-cloud
cp .env.example .env
```

Edit `.env` before starting:

- Replace the example password in **both** `POSTGRES_PASSWORD` and `ARK_DATABASE_URL` with
  the same randomly generated password. URL-encode reserved characters in the URL's password.
- Keep `ARK_BIND_ADDRESS=127.0.0.1`.
- Leave `ARK_TAILSCALE_API_KEY` blank; remote access is configured in the app.
- Optionally adjust `ARK_SYSTEM_HOSTNAME` and `ARK_SYSTEM_OS_NAME` to label your instance.

### 2. Start Ark Cloud

```bash
./scripts/ark up
./scripts/ark bootstrap
```

The first command builds the images, applies database migrations, starts the services, and
waits for health checks. It also sets up the owner-run storage helper and a dedicated
`~/Ark-Locations` area for additional storage locations.

The second command prints a one-time setup code that expires after 15 minutes. Open
**<http://127.0.0.1:5173> on the server**, enter the code, and create your first administrator
account with a password of at least 12 characters. There is no default login.

### 3. Connect your storage

After setup, open **Administration → Storage → Add location**:

1. Choose a new or existing server folder within an owner-approved area.
2. Select private or shared storage and the accounts that should have access.
3. Press **Connect**. Ark prepares filesystem access and checks the running API's mounts.

Open **Local Files** to start working with your files. Use **Set as starting folder** to save
your preferred opening location. Administrators can invite more users under
**Administration → Users** and adjust location permissions under **Manage → Access**.

For existing directories, SELinux, rootless Docker, custom approved areas, and recovery,
see [Local storage](docs/local-storage.md).

## Private remote access

Local access works without Tailscale. To reach Ark from another device:

1. Create a Tailscale API key using an account with device-create rights in your tailnet.
2. Open **Administration → Tailscale**, enter the key, and press **Connect**.
3. Complete any Tailscale approval requested by the UI. Ark resumes setup automatically.
4. Open the displayed HTTPS URL from a device running Tailscale and authorized by your
   tailnet's access policy, then sign in with your Ark Cloud account.

Ark stores the API credentials encrypted and manages its own userspace Tailscale node.
Setup requires no `.env` edits, manual Serve commands, or stack restart.

- **Disable remote access** stops the managed HTTPS endpoint while retaining credentials
  and node identity for re-enabling it later.
- **Disconnect** removes saved credentials and logs out the managed node.
- Both preserve local access. An independently configured host Tailscale endpoint is managed
  separately and is not stopped by these controls.

See [Tailscale setup and recovery](docs/development.md#use-tailscale-for-remote-access) for
credential expiry, existing configurations, and backups.

## Deployment scope

**The source repository can be public; your running Ark Cloud instance should remain private.**
v1.0 is an MVP for localhost and authorized Tailscale access. Public Internet hosting is outside
the supported deployment model. Ark uses private Tailscale Serve, not public Tailscale Funnel.

The supplied Compose stack currently runs Vite and a reload-enabled API. The v1.0 milestone
marks the MVP feature set; it does not establish hardened public-hosting support. The only
published host port defaults to `127.0.0.1:5173`; the API and PostgreSQL have no host ports.

Storage access is enforced by the application within owner-provisioned mounts. Administrators
do not automatically bypass file grants or another account's private-folder boundary. Revoking
access, deleting an account, or disconnecting a location preserves the files on the host.

System metrics describe the **unprivileged API runtime view**, not exact host or cgroup
telemetry. Some kernel readings can reflect host-wide information; storage readings can reflect
the container filesystem. GPU and sensor details appear only when available. Telemetry does
not require host-root mounts, Docker socket access, or privileged containers.

Read [Security](docs/security.md) for trust boundaries and production-hardening considerations,
and [Roadmap](docs/roadmap.md) for validation work, planned improvements, and feature boundaries.

## Running your instance

| Command | Purpose |
| --- | --- |
| `./scripts/ark up` | Build and recreate the stack, apply migrations, and wait for health checks |
| `./scripts/ark status` | Show service status |
| `./scripts/ark health` | Check API health through the browser-facing proxy |
| `./scripts/ark logs api` | Follow API logs |
| `./scripts/ark restart` | Perform a fresh full restart while preserving volumes |
| `./scripts/ark down` | Stop and remove containers and networks while preserving volumes |
| `./scripts/ark reset-password USERNAME` | Reset a local password using a hidden terminal prompt |
| `./scripts/ark recover-admin USERNAME` | Restore administrator access from the owner's terminal |

Normal lifecycle commands preserve database and Tailscale volumes. After updating the source
or changing `.env`, run `./scripts/ark up` to rebuild and apply the changes.

### Backups

Back up host file content together with the storage configuration and PostgreSQL state.
Private folders are tied to immutable account IDs, so files alone are not a complete
account-and-permissions backup.

For managed Tailscale recovery, also preserve the `tailscale_secrets`, `tailscale_controller`,
and `tailscale_state` named volumes. Protect these backups as secrets. See
[managed-node recovery](docs/development.md#back-up-and-recover-the-managed-node) and
[local-storage recovery](docs/local-storage.md).

`./scripts/ark reset-data --confirm` permanently deletes Compose-managed named volumes,
including accounts, database state, and managed Tailscale identity and secrets. It is a reset
operation, not a routine shutdown; host file content remains on disk.

## Development and contributions

Ark Cloud uses React 19, TypeScript, and Vite for the client; Python 3.14, FastAPI, SQLAlchemy,
and Alembic for the API; and PostgreSQL 18 for persistence. Compose provides the integrated
environment with Node.js 22.

For bugs or feature requests, [open an issue](https://github.com/forwizzel/ark-cloud/issues)
with the expected behavior, what happened, and relevant reproduction steps. Remove credentials
and private filenames from logs before sharing them. For code changes, start with the
[development guide](docs/development.md) and [architecture](docs/architecture.md).

### Quality checks

With the API image built, run backend checks in the container:

```bash
docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api pytest
docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api ruff check .
docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api ruff format --check .
```

For frontend checks, run these commands from `apps/web` with Node.js 22:

```bash
npm ci
npm test
npm run lint
npm run format:check
npm run build
```

Host storage helper checks use disposable directories without Docker:

```bash
python3 -m unittest discover -s scripts -p 'test_storage*.py'
```

The API's interactive documentation is available at <http://127.0.0.1:5173/api/docs>, with
OpenAPI JSON at <http://127.0.0.1:5173/api/openapi.json>. Browser requests use same-origin
`/api/*` routes through the web proxy.

### Repository layout

```text
apps/api/          FastAPI application, migrations, and backend tests
apps/web/          React application and frontend tests
docs/              Deployment, architecture, storage, roadmap, and security guides
graphics/          Ark Cloud branding assets
scripts/           Stack lifecycle, account recovery, and host storage helpers
compose.yaml       Integrated service topology
.env.example       Configuration template
```

## Documentation

| Guide | What you'll find |
| --- | --- |
| [Development](docs/development.md) | Setup details, accounts, recovery, Tailscale, and checks |
| [Local storage](docs/local-storage.md) | Host provisioning, access rules, SELinux, and storage recovery |
| [Architecture](docs/architecture.md) | Components, data flow, and system boundaries |
| [Security](docs/security.md) | Authentication, secrets, network exposure, and trust boundaries |
| [Roadmap](docs/roadmap.md) | Delivered capabilities, next priorities, and supported scope |
