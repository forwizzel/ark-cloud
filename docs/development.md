# Development

## Prerequisites

- Docker Engine
- Docker Compose v2 or later
- Git

Node.js and Python are only needed for optional host-native checks. Compose supplies the
supported Node.js 22 and Python 3.14 environments.

## Start The Stack

```bash
cp .env.example .env
```

Edit `.env` and replace the development password in both `POSTGRES_PASSWORD` and
`ARK_DATABASE_URL`. Environment variables keep machine-specific configuration and secrets
out of source code.

`ARK_SYSTEM_HOSTNAME` and `ARK_SYSTEM_OS_NAME` are optional display labels for the API-runtime
metrics shown on the dashboard; unset, empty or whitespace-only values use **API runtime** and
**Linux**. Explicit labels are preserved. `ARK_SYSTEM_STORAGE_PATH` selects the filesystem for
runtime storage telemetry. These settings never identify or configure the physical host; connect
the host agent in **Administration → System** for detected hostname, distribution, kernel and
architecture. Configure Tailscale in **Administration → Tailscale**;
leave `ARK_TAILSCALE_API_KEY` blank for new installations. Existing environment API key and
tailnet values provide legacy read-only inventory only; `ARK_TAILSCALE_TAILNET=-` uses the
tailnet associated with the API key. UI saves supersede that fallback, and explicit Disconnect
disables it. Keep `ARK_BIND_ADDRESS=127.0.0.1` for the web port.

```bash
./scripts/ark up
```

Compose performs these steps in dependency order:

1. PostgreSQL starts and `pg_isready` reports that it accepts connections.
2. The API applies Alembic migrations, starts Uvicorn, and passes `/health`.
3. Vite starts and publishes the web page on the configured host address.
4. The dedicated Tailscale service runs in userspace and reconciles UI-managed node and Serve
   state. It needs no host Tailscale installation, TUN device, or host networking privileges.

Source directories are mounted into their containers. Vite provides frontend hot module
replacement, and Uvicorn's `--reload` restarts the development API when Python files
change. The `:Z` mount suffix gives each source directory a private SELinux label so the
containers can read the bind mounts on Fedora without disabling host security controls.
Vite writes its generated development cache to the container's `/tmp` directory, leaving
the source mount unchanged. The web container compares a lockfile hash at startup and runs
`npm ci` only when its named dependency volume does not match `package-lock.json`. Rebuild after
changing `package.json`, `package-lock.json`, or `pyproject.toml`:

```bash
./scripts/ark up
```

## Local Accounts

On a new install, start the stack with `./scripts/ark up`, then issue a one-time code from the
instance owner's terminal:

```bash
./scripts/ark bootstrap
```

Enter the code on <http://127.0.0.1:5173> and choose the first administrator username and
password (at least 12 characters). The code expires after 15 minutes; rerun the command to
replace an unused/expired code. Only an instance with no accounts can
issue a code. No default login exists and the setup page closes after the first account.

Users change their username or password under **Account**. They must supply their current
password. Password changes revoke every session, including the current browser; sign back in.
An administrator can create an invitation in **Administration → Users** and share its one-time
code privately. The invitee selects **Redeem invitation** on the sign-in screen to choose a
password. Invitations expire after 24 hours; an admin can issue a replacement code. Admins can
change roles, disable/enable accounts, or delete an account with an explicit username and admin
password confirmation. Deletion removes that user's account and storage permissions while
preserving files on the host. The last active administrator cannot be removed.

For local recovery when no admin can log in, use `./scripts/ark reset-password USERNAME` or
`./scripts/ark recover-admin USERNAME`. Both prompt for a new password without showing it in
command arguments or output, revoke sessions and outstanding invitations, and require terminal
access to the running stack. Recovery cannot restore a deleted database volume; restore a backup.

Existing single-user installs: **keep** `ARK_AUTH_USERNAME` and `ARK_AUTH_PASSWORD_HASH` in the
ignored `.env` for the first `./scripts/ark up` on v0.7. The migration imports that existing
Argon2id hash, assigns a stable account ID, and invalidates old sessions. Log in with the same
password and confirm the imported account is present,
then remove those two legacy values from `.env` if desired. Future username/password changes
are only made in the application. Do not delete the PostgreSQL volume during an upgrade.

If `ARK_SESSION_SECRET` is blank, the first login/setup creates a persistent random signing key
in PostgreSQL. Existing installations may retain their configured `.env` secret; changing or
removing it invalidates sessions. Back up the database volume to retain accounts, invitations,
and the generated signing key across rebuilds or host moves. `./scripts/ark reset-data --confirm`
deletes all accounts and control-plane data.

## Inspect The Stack

```bash
./scripts/ark status
./scripts/ark logs api
./scripts/ark health
```

`./scripts/ark logs api` follows new API log lines until `Ctrl+C`. The health command follows
the same web-to-API proxy path used by the React application.

## Use Tailscale For Remote Access

Default Compose supplies Ark's own dedicated userspace Tailscale node. Keep the published web
port on `127.0.0.1`; the managed node proxies the web service over Docker's private network
with Tailscale Serve HTTPS. No host Tailscale installation or host networking privileges are
needed, including with rootless Docker.

### Connect From The UI

Create a Tailscale API key as a tailnet user with device-create rights. Sign in as an Ark
administrator, open **Administration → Tailscale**, enter the key, and press **Connect**.
Ark validates the credentials and saves them encrypted, then automatically mints a one-use
auth key, joins the dedicated node, and configures Serve HTTPS. Saving does not require
environment changes, terminal commands, or a restart.

If an unmet tailnet requirement requires vendor approval, the UI shows an HTTPS Tailscale
approval link. Complete approval there; Ark automatically resumes the pending connection.
Only approved HTTPS vendor links are exposed, not raw command output or upstream responses.

Use the resulting HTTPS URL from a client with the Tailscale app installed and signed in to
an account authorized by the tailnet's access policy. Ark account authentication is still
required. This is private Serve access; Funnel and public Internet access are not enabled.

### Disable Remote Access Or Disconnect

- **Disable remote access** stops the managed Serve endpoint but retains saved credentials
  and the joined node identity, allowing remote access to be enabled again.
- **Disconnect** removes saved credentials and logs out the managed node. It records an
  explicit disabled state so environment credentials do not silently reconnect the integration.
- Both preserve local access at <http://127.0.0.1:5173>. Neither controls an independent host
  Tailscale installation or its Serve endpoint.

API key expiration can stop inventory queries and new provisioning operations without
disconnecting an already-joined node or its existing Serve endpoint. Replace an expired key
through **Administration → Tailscale** rather than editing `.env`.

### Migrate Existing Configuration

Existing `ARK_TAILSCALE_API_KEY` and `ARK_TAILSCALE_TAILNET` values remain a read-only device
inventory fallback. They never automatically provision the managed node. Saving credentials
in the UI supersedes this fallback; explicit Disconnect disables it even if those variables
remain set. After a successful UI connection, the owner can remove the legacy environment
values during routine deployment maintenance. Alternatively, **Enable private access**
validates and adopts an existing legacy key into encrypted UI-managed settings; it is never
enabled automatically at startup.

A manually configured host Serve endpoint is not adopted or automatically removed. Connect
the dedicated node in the UI, verify its new HTTPS address from a tailnet client, and update
bookmarks or shared links. Retire the old endpoint separately using the host's Tailscale
administration once it is no longer needed. If it remains configured, it can still expose Ark
privately even after **Disable remote access** or **Disconnect** in Ark's UI.

### Back Up And Recover The Managed Node

Recovering the managed connection requires a consistent PostgreSQL backup together with
these persistent Compose named volumes:

| Volume | Recovery material |
| --- | --- |
| PostgreSQL database volume | Encrypted credentials and desired connection state, plus Ark accounts and control-plane data |
| `tailscale_secrets` | Credential encryption key, separate from PostgreSQL |
| `tailscale_controller` | Token authenticating the dedicated controller to the API |
| `tailscale_state` | Joined node identity and Tailscale state |

Restrict and encrypt backups of all four. Restore them together for recovery on a replacement
host; a database-only backup cannot decrypt the saved API key without `tailscale_secrets`,
and missing identity state cannot preserve the original joined node. Normal `up`, `restart`,
and `down` preserve these volumes. `reset-data --confirm` removes them along with PostgreSQL.

## Stop Or Reset

```bash
./scripts/ark down
```

This removes containers and networks but preserves PostgreSQL and the Tailscale named volumes.
To delete local database data, managed Tailscale identity, and secrets and start fresh, use
the destructive command:

```bash
./scripts/ark reset-data --confirm
```

The `--confirm` flag is required because this permanently removes Compose-managed named volumes.
Do not use it when the local data must be retained. `./scripts/ark restart` is the normal fresh
restart and preserves volumes.

## Tests And Static Checks

Backend:

```bash
docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api pytest
docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api ruff check .
docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api ruff format --check .
```

The backend unit tests override database health at the route boundary and separately prove
that the database check executes a real query. psutil is mocked for deterministic System
tests, and the Tailscale HTTP opener is replaced with local response doubles. Tests never
contact a real tailnet. The running Compose health check provides PostgreSQL integration
verification.

System is available after signing in at `#system`, with resource details at `#system/vitals`.
`#system-information` remains a compatibility alias. See [System host setup](system-host.md) for
the UI-managed host agent, WebSocket transport, typed host jobs, and terminal checks.
Administration → System handles connection and capability settings through the deployment-owned
host manager already prepared for Local Files. Routine agent enrollment needs no separate script.
Run host checks with `python3 -m unittest discover -s scripts -p 'test_system*.py'`.
The API
exposes authenticated `GET /api/system/information` through the web proxy. Its detailed runtime
view shows CPU/memory/storage, optional GPU names from kernel-visible DRM/driver metadata, and
temperature readings with readable labels and original sensor identifiers. Missing GPU or sensors
are normal unavailable states; a kernel-visible GPU is not necessarily accessible to the API.
The page can load independently of dashboard integrations. These container readings remain a
separate runtime disclosure when no host snapshot exists. The container-only process endpoint
and listing were removed. Backend tests cover sensor naming, GPU model and PCI-ID fallback,
missing devices, authentication, and partial collection failures.

Frontend:

```bash
cd apps/web
npm install
npm test
npm run lint
npm run format:check
npm run build
```

`npm install` uses exact direct dependency versions and updates `package-lock.json`; CI and
container builds use `npm ci` for a lockfile-exact installation.

## Database Migrations

Create a migration only when a real schema change is needed. Migration generation is a
one-off development operation that runs as container root so it can write through bind
mounts under either rootless or rootful Docker; `chown --reference` gives generated files
the same host ownership as the existing migration environment:

```bash
docker compose run --rm --no-deps --user root api sh -c \
  'alembic revision -m "describe the change" && chown --reference=alembic/env.py alembic/versions/*.py'
docker compose exec api alembic upgrade head
```

Review generated migrations before applying them. Alembic provides an ordered history so
development, tests, and future deployments agree on the schema instead of mutating it
implicitly at application startup.

## API Documentation

- Swagger UI: <http://127.0.0.1:5173/api/docs>
- OpenAPI schema: <http://127.0.0.1:5173/api/openapi.json>

These URLs pass through Vite because the API intentionally has no host port.

## Local Storage

Provisioning, SELinux mount requirements, file-operation limits, and recovery are documented in
[Local storage](local-storage.md). File content remains in owner-approved host directories;
PostgreSQL stores only control-plane state. The managed Tailscale gateway automatically marks
remote HTTPS session cookies Secure while local loopback HTTP remains available for recovery.

## Retired Integration Cleanup

The removal migration permanently drops the former Google Drive credentials, cached catalog,
workspace preferences, and synchronization history, and removes OAuth state from sessions.
It preserves local accounts, sessions, host-storage configuration, grants, and Tailscale state.
Historical migration revisions remain in the upgrade chain so existing installations can upgrade.
The retired integration's routes and environment settings are no longer supported. Restoring its
deleted database data requires a pre-removal backup; it cannot be recovered by downgrading.
