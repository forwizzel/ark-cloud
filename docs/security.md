# Security

## Current Security Posture

Version 0.9 is development software, not a production deployment. It supports local accounts,
administrator-managed invitations, and account-scoped local files. Tailscale reduces network
exposure but does not replace identity checks inside Ark Cloud. Do not publish this stack to the
Internet.

## Trust Boundaries

```text
User device | Tailscale or local host | Web proxy | API | PostgreSQL / authorized host files
```

- The browser is untrusted input even on a private network.
- The web container can reach the API but cannot join the database network.
- The API is the only application component allowed to reach PostgreSQL.
- PostgreSQL and the API have no host port mappings.
- `./scripts/ark up` forces the web port onto loopback (`127.0.0.1`).
- Default Compose includes a dedicated userspace Tailscale service for private Serve HTTPS.
  It requires no host installation, TUN device, host networking privileges, or Docker socket.
  Its controller authenticates to the API using a token in `tailscale_controller`; joined node
  identity resides in `tailscale_state`. It cannot reach the database network.
- Explicit host directory mounts are the local-content boundary. The owner-operated manifest and
  immutable account IDs scope access; Unix permissions and SELinux independently constrain the API.
  PostgreSQL never stores file bodies.
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
- Supported deployment startup provisions an owner-run helper and a pinned dedicated managed area.
  Browser administrators can prepare access only within owner-authorized areas. Automatic ACL
  preparation is descriptor-relative, rejects symlinks/nested mounts/special or multiply-linked
  files, and preserves existing named users' effective mask-limited rights. Original ACL and inode
  metadata are journaled privately; file content and existing labels are preserved. Final activation
  requires a successful running-API check. A failed registration stays blocked until repaired;
  duplicate connections resolve to that registration, and retries recompute access preparation.
- Appearance choices live only in browser localStorage; they contain no credentials and are not
  sent to the API.
- The optional System agent is separately enrolled under a non-root host account. Administrators
  connect/configure it in Administration → System through the deployment-owned host manager;
  routine setup requires no user script. The manager accepts only typed lifecycle jobs, rechecks
  requester authorization before applying, and limits shell/service choices to host-reported
  installed/permitted options. Account identity and the terminal home remain deployment-owned.
  Administrators receive that account's terminal access only when it is explicitly enabled. Dedicated
  service/power controls require owner-selected capabilities and narrow host authorization.
  The API remains unprivileged. WebSocket attachment validates session ownership, same-origin
  Origin (or the managed gateway proof), and a short-lived single-use grant. Agent credentials
  are separate from browser grants and hashed server-side. See [System host setup](system-host.md).
  Authorization guards revoke terminals within two seconds; terminal streams are not persisted.
  Job dispatch rechecks requester authorization, and a host-side journal prevents action replay.

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

UI-saved Tailscale API credentials are validated and encrypted before persistence in
PostgreSQL. Their encryption key is separate, in the persistent `tailscale_secrets` named
volume; no environment-provided encryption key is needed for UI setup. Credentials are sent
only to the fixed HTTPS Tailscale API origin server-side and excluded from normalized responses
and logs. Redirects are refused rather than forwarding the credential. Automatically minted
one-use auth keys join the managed node and are never returned to the browser.

The API key's user must have device-create rights for managed provisioning; an inventory-only
read scope is insufficient. Expiry may affect inventory or provisioning without disconnecting
an already-joined node's Serve endpoint. Replace the key in **Administration → Tailscale**.
Existing environment key/tailnet values are a legacy read-only inventory fallback only until
a UI save supersedes them or explicit Disconnect disables the fallback. Explicitly selecting
**Enable private access** with a legacy key validates it and adopts it into encrypted
UI-managed configuration before provisioning; startup never enables it automatically.

Back up PostgreSQL together with `tailscale_secrets`, `tailscale_controller`, and
`tailscale_state` for managed connection recovery. The database alone cannot decrypt saved
credentials without the separate encryption key. Protect all of these backups as secrets;
see [recovery details](development.md#back-up-and-recover-the-managed-node).

Environment variables are appropriate for local development, not a complete production
secret-management strategy. Docker secrets or a dedicated secret manager should be
evaluated before deployment.

## Network Exposure

The default port mapping is `127.0.0.1:5173:5173`, so the published host port is local-only.
**Administration → Tailscale → Connect** validates and saves the API key, then automatically
provisions a dedicated node and private Serve HTTPS to the web container. Saving requires no
environment changes or shell commands. If a tailnet requirement needs approval, the UI offers
only an approved HTTPS Tailscale vendor link and automatically resumes after approval.
Clients need the Tailscale app, a Tailscale account login authorized by tailnet grants, and
their Ark Cloud login. Ark does not enable Funnel or public Internet access.

**Disable remote access** stops the managed HTTPS endpoint while retaining credentials and
node identity. **Disconnect** removes credentials, logs out the managed node, and explicitly
disables environment fallback. Local loopback access remains available in both cases.
An existing manual host Serve endpoint is independent: it is neither adopted nor automatically
removed, and these UI actions do not stop it. Migration requires separately retiring the old
host endpoint after verifying the new managed address.

Keep `ARK_BIND_ADDRESS=127.0.0.1`; direct Tailscale-IP binding is not supported by the rootless
Docker environment. Serve supplies HTTPS for the private remote path; local access remains
HTTP on loopback. Inventory requests remain server-side and return normalized device data.

## Dependency And Runtime Practices

- Direct Python and npm dependencies and container image patch versions are pinned.
- `package-lock.json` locks the complete frontend dependency graph.
- The API runs as an unprivileged `arkcloud` user and the web image runs as the built-in
  unprivileged `node` user.
- SQLAlchemy hides statement parameters to reduce accidental secret or personal-data logs.
- Health endpoints report component state but no credentials or connection details.
- Database storage uses a named volume and is never part of the source tree.
- PostgreSQL stores encrypted credentials and other control-plane state, not file content.
- Database backups contain sensitive control-plane data. Encrypt and restrict them rather than
  treating them as ordinary user files.
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

## Accounts And Sessions

- Dashboard and integration routes require a local server-side session. The session cookie is
  HttpOnly and SameSite; authenticated mutations require a session-bound CSRF token. Signed-out
  setup and invitation redemption require a one-time secret and same-origin JSON request.
- Keep a random session secret in ignored `.env` or use the persistent database-generated secret;
  local account password hashes use Argon2id and are stored in PostgreSQL, not in
  source control. The managed Tailscale gateway supplies a trusted HTTPS proof for Secure cookies;
  arbitrary client-provided forwarded headers are not trusted. Other HTTPS reverse proxies must
  configure `ARK_COOKIE_SECURE=true` explicitly.
- Immutable user IDs bind sessions and private folders. Username changes do not change file
  ownership. Password changes, disabling accounts, and role changes revoke existing sessions.
- Account deletion removes control-plane permissions but never deletes host file content.

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
