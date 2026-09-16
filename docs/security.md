# Security

## Current Security Posture

Version 0.1 is a development scaffold, not a production deployment. It has no application
authentication or authorization. Tailscale reduces network exposure but does not replace
identity checks inside Ark Cloud. Do not publish this stack to the Internet.

## Trust Boundaries

```text
User device | Tailscale or local host | Web proxy | API | Data network | PostgreSQL
```

- The browser is untrusted input even on a private network.
- The web container can reach the API but cannot join the database network.
- The API is the only application component allowed to reach PostgreSQL.
- PostgreSQL and the API have no host port mappings.
- The web port binds to loopback unless `ARK_BIND_ADDRESS` is explicitly changed.

The API validates its response shape with Pydantic. Future request bodies, paths, and query
parameters must receive equivalent explicit validation.

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

When the integration is configured, authenticated Tailscale requests are initiated by
unauthenticated dashboard clients and normalized device inventory is visible to every client
that can reach Ark Cloud. Until application authentication and rate limiting exist, keep the
loopback default or use restrictive Tailscale grants so only explicitly trusted devices can
reach the web port.

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
- System collection does not mount the Docker socket, host root filesystem, privileged
  namespaces, or require root.

Run dependency audits regularly and review base image updates. A Python transitive lock file
should be introduced before production packaging; exact direct pins are sufficient for this
initial development image but do not lock every transitive package.

## Before Production Use

- Complete threat modeling and authentication architecture review.
- Implement respected authentication and session libraries; do not invent cryptography.
- Add authorization, secure cookies, logout and invalidation, CSRF protection where
  applicable, strict security headers, and rate limiting.
- Terminate HTTPS at a reviewed reverse proxy.
- Separate development and production images and remove reload behavior.
- Use production secret storage and least-privilege database roles.
- Add audit events, backup encryption, restoration tests, dependency scanning, and recovery
  documentation.
- Review CORS before adding any cross-origin client; keep explicit origins rather than `*`.

## Google Drive And Sessions

- Dashboard and integration routes require a local server-side session. The session cookie is
  HttpOnly and SameSite; mutations also require a session-bound CSRF token.
- Configure a unique Argon2id password hash and random session secret in ignored `.env`, not in
  source control. Set `ARK_COOKIE_SECURE=true` whenever access is served over HTTPS.
- Google OAuth client credentials and Fernet encryption key remain server-side. Refresh tokens are
  encrypted before database storage and are never returned to the browser or written to logs.
- The OAuth callback validates a short-lived state value bound to the local session, then redirects
  immediately so authorization parameters do not remain in the browser URL.
- Ark Cloud requests metadata-only Drive access for account/quota health. It is not a Drive file
  manager and never proxies file content.
