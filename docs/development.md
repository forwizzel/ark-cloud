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

`ARK_SYSTEM_HOSTNAME`, `ARK_SYSTEM_OS_NAME`, and `ARK_SYSTEM_STORAGE_PATH` label the runtime
metrics shown on the dashboard. Optional `ARK_TAILSCALE_API_KEY` and
`ARK_TAILSCALE_TAILNET` values enable the Tailscale adapter. Leave the key blank when the
integration is not needed. `ARK_TAILSCALE_TAILNET=-` uses the tailnet associated with the
API token. Keep `ARK_BIND_ADDRESS=127.0.0.1`; it is the secure default for the web port.

```bash
./scripts/ark up
```

Compose performs these steps in dependency order:

1. PostgreSQL starts and `pg_isready` reports that it accepts connections.
2. The API applies Alembic migrations, starts Uvicorn, and passes `/health`.
3. Vite starts and publishes the web page on the configured host address.

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

## Local Sign-In

The starter `.env.example` leaves authentication credentials blank. After the first `./scripts/ark up`
has built the API image, generate an Argon2id password hash and a random session secret inside it:

```bash
docker compose run --rm --no-deps api python -c 'from argon2 import PasswordHasher; import getpass; print(PasswordHasher().hash(getpass.getpass()))'
docker compose run --rm --no-deps api python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

The first command prompts for the password without printing it; copy only its hash into
`ARK_AUTH_PASSWORD_HASH`. Set `ARK_AUTH_USERNAME` to the name you will sign in with and copy the
second output into `ARK_SESSION_SECRET`. Keep all three values in ignored `.env`, rerun
`./scripts/ark up`, and sign in at <http://127.0.0.1:5173>. `--rm` cleans up each one-off
container and `--no-deps` avoids starting PostgreSQL for these generators.

## Inspect The Stack

```bash
./scripts/ark status
./scripts/ark logs api
./scripts/ark health
```

`./scripts/ark logs api` follows new API log lines until `Ctrl+C`. The health command follows
the same web-to-API proxy path used by the React application.

## Use Tailscale For Remote Access

The Tailscale device integration and remote browser access are separate features. The API
integration uses `ARK_TAILSCALE_API_KEY` and `ARK_TAILSCALE_TAILNET` to query device status.
Remote browser access does not require exposing the Compose port on the Tailscale interface.

With the default loopback binding, publish Ark Cloud through Tailscale Serve on the Ark host:

```bash
sudo tailscale serve --bg http://127.0.0.1:5173
```

Open the HTTPS hostname reported by `tailscale serve status` from a trusted tailnet device.
Rootless Docker cannot reliably bind the published port directly to a `100.x.y.z` Tailscale
address, and binding to `0.0.0.0` would expose the port on every host interface.

## Stop Or Reset

```bash
./scripts/ark down
```

This removes containers and networks but preserves the named PostgreSQL volume. To delete
all local database data and start from an empty database, use the destructive command:

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

System Information is available after signing in at `#system-information`. The API
exposes authenticated `GET /api/system/information` through the web proxy. Its detailed runtime
view shows CPU/memory/storage, optional GPU names from kernel-visible DRM/driver metadata, and
temperature readings with readable labels and original sensor identifiers. Missing GPU or sensors
are normal unavailable states; a kernel-visible GPU is not necessarily accessible to the API.
The page can load independently of dashboard integrations. The container-only process endpoint
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

## Google Drive Setup

Google Drive is Ark Cloud's designated user-content storage provider. The integration requests only
the `https://www.googleapis.com/auth/drive.metadata.readonly` scope for normalized account/quota status
and selected metadata for files owned by the connected account in My Drive. Ark Cloud does not
upload, download, export, change, or proxy Drive file content. PostgreSQL stores sessions, encrypted
tokens, synchronization state, and the derived metadata search index rather than user file content.

Generate the Drive token-encryption key inside the API image (after the first stack build):

```bash
docker compose run --rm --no-deps api python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Use the generated value for `ARK_GOOGLE_TOKEN_ENCRYPTION_KEY` in ignored `.env`. The OAuth client
secret and Fernet key remain only in `.env`. The Google refresh token is encrypted before PostgreSQL
storage; it is not an environment variable.

1. In Google Cloud, create or select a project, configure the OAuth consent screen, and enable the
   Google Drive API.
2. Create an OAuth client of type **Web application**. Add the exact redirect URI from
   `ARK_GOOGLE_REDIRECT_URI`; the default is
   `http://127.0.0.1:5173/api/integrations/google-drive/oauth/callback`.
3. If the consent screen is in Testing, add the Google account that will connect Drive as a test
   user.
4. Configure [local sign-in](#local-sign-in), then set `ARK_GOOGLE_CLIENT_ID`,
   `ARK_GOOGLE_CLIENT_SECRET`, and `ARK_GOOGLE_TOKEN_ENCRYPTION_KEY` in ignored `.env`.
   Retain the redirect URI exactly as registered in Google Cloud.
5. Run `./scripts/ark up`, sign in locally, and select **Connect Google Drive** in the dashboard.

The OAuth callback runs the initial My Drive catalog synchronization. If that metadata sync fails,
the Drive connection remains available and **Drive Workspace** offers **Retry sync**. Later
syncs use Google's changes feed and its persisted page token instead of enumerating the full catalog.
Search matches normalized filenames and opens results directly in Google Drive. Shared drives and
scheduled/background synchronization are not supported.

Automated tests use local response doubles and must never use a real Google account.

For local HTTP development retain `ARK_COOKIE_SECURE=false`. Set it to `true` before using an HTTPS
reverse proxy. Google Drive remains the user-content source of truth: Ark Cloud exposes normalized
connection, quota, catalog, and search data and opens Drive for all file operations.
