# Security

## Current Security Posture

Version 0.9 is development software, not a production deployment. It supports local accounts,
administrator-managed invitations, private local files, and principal-scoped Drive data. Tailscale reduces network
exposure but does not replace identity checks inside Ark Cloud. Do not publish this stack to the
Internet.

## Trust Boundaries

```text
User device | Tailscale or local host | Web proxy | API | PostgreSQL / Google Drive
```

- The browser is untrusted input even on a private network.
- The web container can reach the API but cannot join the database network.
- The API is the only application component allowed to reach PostgreSQL.
- PostgreSQL and the API have no host port mappings.
- `./scripts/ark up` forces the web port onto loopback (`127.0.0.1`).
- Explicit host directory mounts are the local-content boundary. The owner-operated manifest and
  immutable account IDs scope access; Unix permissions and SELinux independently constrain the API.
  Google Drive is optional and metadata-only. PostgreSQL never stores file bodies.
- An optional host-owner-enrolled storage manager accepts typed storage jobs through the loopback
  proxy and controls only this deployment's storage configuration within explicitly approved areas.
  Enrollment delegates those operations to application administrators; it is separate from file
  ownership. Host-manager credentials stay in a mode-0600 host file and are hashed in PostgreSQL.
  No Docker socket or host control channel is mounted into the API. Queued jobs recheck administrator
  authorization before a durable claim; already-started changes are reconciled after interruptions.
- Account storage grants are administered with session-bound CSRF and location-registration/revision
  checks. Private grants address only the caller's immutable-ID folder; shared grants address the
  entire registered shared tree. Administrator status alone does not bypass file grants or private
  folder confinement. Read-only grants reject every file mutation. Grant changes serialize with
  file publication, and uploads recheck grant versions before publishing, including revoke/regrant.
  Revocation blocks new operations; a download whose descriptor was already authorized may finish.
  Retired registrations cannot be reused to inherit old grants or silently change a private base
  into shared storage. File bodies stay outside PostgreSQL; grant and audit metadata are backed up
  with the control plane.
- Appearance choices live only in browser localStorage; they contain no credentials and are not
  sent to the API.

The API validates response shapes with Pydantic and validates request bodies, paths, and query
parameters through explicit route schemas.

## Secrets

- `.env` is ignored by Git; `.env.example` contains placeholders only.
- Never commit passwords, API keys, Tailscale credentials, tokens, SSH keys, or production
  database URLs.
- Use a unique, randomly generated database password outside local development.
- Ensure the password embedded in `ARK_DATABASE_URL` is URL-encoded if it contains reserved
  URL characters.
- Do not pass third-party integration secrets to the browser when the API can hold them.
- Rotate a credential immediately if it appears in Git history or logs.

The optional Tailscale access token is stored as a Pydantic `SecretStr`, sent only to the
fixed HTTPS Tailscale API origin in a server-side `Authorization` header, and excluded from
normalized responses and logs. Redirects are refused rather than forwarding the credential.
Use the shortest practical expiration and revoke unused tokens. OAuth client credentials
with a narrow `devices:core:read` scope should replace manually rotated access tokens when
the integration needs continuous operation.

Environment variables are appropriate for local development, not a complete production
secret-management strategy. Docker secrets or a dedicated secret manager should be
evaluated before deployment.

## Network Exposure

The default port mapping is `127.0.0.1:5173:5173`, so only applications on Ark can connect.
For private remote development, keep that loopback binding and use Tailscale Serve to proxy the
port through the tailnet:

```bash
sudo tailscale serve --bg http://127.0.0.1:5173
```

This is the supported approach for the rootless Docker development environment. Direct binding
to Ark's `100.x.y.z` Tailscale address can fail because the rootless Docker networking namespace
does not own the host interface. Avoid `0.0.0.0`, which listens on every host interface, and do
not open router ports.

When configured, Tailscale requests are initiated server-side for an authenticated dashboard
session. Normalized device inventory is visible to the configured local user. Keep the loopback
default or use restrictive Tailscale grants so only explicitly trusted devices can reach the web
port.

HTTPS is deferred until a reverse proxy is introduced. Plain HTTP is acceptable only for
loopback or a deliberately reviewed private development path. Sensitive features require
HTTPS even within a private network.

## Dependency And Runtime Practices

- Direct Python and npm dependencies and container image patch versions are pinned.
- `package-lock.json` locks the complete frontend dependency graph.
- The API runs as an unprivileged `arkcloud` user and the web image runs as the built-in
  unprivileged `node` user.
- SQLAlchemy hides statement parameters to reduce accidental secret or personal-data logs.
- Health endpoints report component state but no credentials or connection details.
- Database storage uses a named volume and is never part of the source tree.
- PostgreSQL stores encrypted credentials and other control-plane state, not Drive file content.
- Database backups contain sensitive control-plane data. Encrypt and restrict them rather than
  treating them as ordinary user files in Drive.
- System collection does not mount the Docker socket, host root filesystem, privileged
  namespaces, or require root.

Run dependency audits regularly and review base image updates. A Python transitive lock file
should be introduced before production packaging; exact direct pins are sufficient for this
initial development image but do not lock every transitive package.

## Before Production Use

- Complete production threat modeling and multi-user authorization review.
- Add session rotation and expiry cleanup and strict security headers; review login throttling
  under multi-replica deployments.
- Terminate HTTPS at a reviewed reverse proxy.
- Separate development and production images and remove reload behavior.
- Use production secret storage and least-privilege database roles.
- Add audit events, backup encryption, restoration tests, dependency scanning, and recovery
  documentation.
- Review CORS before adding any cross-origin client; keep explicit origins rather than `*`.

## Google Drive And Sessions

- Dashboard and integration routes require a local server-side session. The session cookie is
  HttpOnly and SameSite; authenticated mutations require a session-bound CSRF token. Signed-out
  setup and invitation redemption require a one-time secret and same-origin JSON request.
- Keep a random session secret in ignored `.env` or use the persistent database-generated secret;
  local account password hashes use Argon2id and are stored in PostgreSQL, not in
  source control. Set `ARK_COOKIE_SECURE=true` whenever access is served over HTTPS.
- Google OAuth client credentials and Fernet encryption key remain server-side. Refresh tokens are
  encrypted before database storage and are never returned to the browser or written to logs.
- The OAuth callback validates a short-lived state value bound to the local session, completes the
  bounded token exchange and initial metadata sync, then redirects so authorization parameters do
  not remain in the browser URL.
- Google Drive is the source of truth for Drive content. Ark Cloud requests
  `drive.metadata.readonly` for account/quota health and a principal-scoped catalog of files owned
  by the account in My Drive. The database stores selected normalized metadata, folder edges,
  saved searches, pinned folder IDs, sync history, and bounded sync-observed activity. It never
  stores file content, descriptions, owners, permissions, access tokens, or raw Google responses.
- Initial catalog synchronization runs after OAuth connection. Manual updates require the local
  session's CSRF token. Saved-search and pin mutations also require CSRF. Browsing, search, reports,
  activity, preferences, and synchronization records require authentication, and every database
  query is scoped to the authenticated principal.
- Folder names, filenames, saved query terms, pins, insights, and activity are sensitive personal
  metadata. They are excluded from routine logs, but they are present in PostgreSQL backups and
  require the same access controls as other control-plane data.
- Pagination cursors contain only encoded catalog position, revision, filter signature, and
  principal-binding data. They grant no access and are always validated before a principal-scoped
  query.
- Drive search results contain direct Google Drive links. Ark Cloud never proxies Drive content or performs
  upload, download, rename, move, export, or delete operations.

## Runtime Information

Local storage uses a distinct content boundary described in [Local storage](local-storage.md).
It does not expand the scope or privileges of system telemetry. Local file routes enforce sessions,
CSRF on writes, root/account authorization, Linux `openat2` confinement, and no-clobber publication.
Downloads are attachments with no-sniff/sandbox/no-store headers; no active previews are rendered.
Raw Uvicorn access logging is disabled because URLs contain private filenames. Bounded structured
mutation events contain only action, root ID, and principal ID. Configure log rotation on the host.
The API process has filesystem access to all mounted roots: user separation is application-enforced,
not a separate Unix identity per Ark account. Host owners and processes with write access to these
trees are trusted. A compromised API process can access its mounts and control-plane credentials.

- Detailed system information requires the same authenticated local session as the dashboard. It
  is a read-only request and requires no CSRF token. The container-only process endpoint and view
  were removed; no process data is collected or stored.
- CPU model, optional GPU metadata, and sensor readings use bounded reads of container-visible
  `/proc/cpuinfo`, `/sys/class/drm`, and (when available) `/proc/driver/nvidia/gpus`. No GPU device
  access, driver commands, or arbitrary filesystem paths are exposed. GPU names and sensor identifiers
  are operational metadata and should not be written to routine logs.
- Section-level provenance and warnings prevent host-global values from being presented as precise
  host/container measurements. The API remains unprivileged: no host-root or `/proc` mount, Docker
  socket, or privileged namespace is required for Phase 5.
