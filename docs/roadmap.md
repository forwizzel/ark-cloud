# Roadmap

Ark Cloud focuses on files that stay on the owner's server and remain usable from authorized
remote devices. New work should strengthen that local-storage and private-access experience.

## Delivered Foundation

- React/TypeScript browser client, FastAPI control plane, and PostgreSQL persistence.
- Reproducible Compose lifecycle, reviewed Alembic upgrades, and loopback-only host exposure.
- Local accounts, expiring setup codes and invitations, administrator/member roles, and
  terminal-only account recovery.
- Argon2id passwords, session-bound CSRF, persisted login throttling, and session revocation.
- Dashboard health, runtime System Information, normalized Tailscale devices, and honest
  partial-failure states.
- Responsive named navigation, keyboard access, light/dark and high-contrast appearance,
  bundled fonts, and reduced-motion support.

## Local Files And Storage Administration

Status: implemented. Local Files is the file workspace.

- Private account folders use immutable user IDs. Shared locations have explicit per-account
  No access, Read-only, or Read & write grants. Administrator status does not bypass private
  folder confinement.
- Administration connects new or existing locations within owner-approved host areas, prepares
  narrow filesystem access, verifies the API's mounts, and repairs the same registration.
- Location management separates Connection, Access, Configuration, and Activity. Upload policy,
  diagnostics, and job history have dedicated views.
- Browsing, streaming uploads/downloads, folder creation, rename, within-location moves, and
  confirmed deletion of files or empty folders operate directly on the host filesystem.
- Descriptor-relative Linux confinement rejects symlinks, nested mounts, traversal, unsupported
  file types, and unsafe hard-link cases. Publication is atomic and does not clobber targets.
- Account starting-folder preferences are explicit; status reads never create private folders.
- Missing or deleted host locations become unavailable and do not block core startup. Files
  remain on the host when access is revoked, an account is deleted, or a location is disconnected.

The host manifest remains the mount authority. PostgreSQL stores control-plane policy and jobs,
never file bodies. Backups must preserve both host content and immutable account/registration IDs.
SELinux-confined rootless Docker with real existing-directory policies still needs independent
validation; checks on a Docker daemon without SELinux confinement do not establish that support.

## UI-Managed Private Remote Access

Status: implemented; fresh live-tailnet acceptance remains to be verified.

Administration → Tailscale accepts an API key, saves it encrypted, creates a single-use auth key,
registers a dedicated userspace node, and enables private HTTPS Serve. Tailscale's required HTTPS
approval is presented as a vendor link when needed; Ark resumes automatically afterward.
No host Tailscale installation or host networking privileges are required.

Private-access disable preserves credentials and node identity; disconnect removes saved
credentials and logs out the managed node. Local loopback access remains available. API inventory
status is independent of Serve, and API-key expiry does not inherently stop an already-joined node.
Independent host Serve endpoints remain outside the managed node's control.

PostgreSQL and the `tailscale_secrets`, `tailscale_controller`, and `tailscale_state` volumes form
the recovery set. Live acceptance should cover registration, required approval, HTTPS reachability,
large transfers, restart recovery, disable/re-enable, disconnect, and backup restoration.

## Next Priorities

1. Test large and interrupted transfers, disappearing mounts, permission changes, disk-full
   errors, and concurrent host edits on supported deployment configurations.
2. Exercise and document restoration of host files, accounts, storage grants, and managed
   Tailscale identity together.
3. Improve mobile file workflows and evaluate PWA behavior against real usage.
4. Review production packaging, strict security headers, audit coverage, backup encryption,
   dependency scanning, MFA/passkeys, and multi-user authorization.
5. Consider a narrow authenticated host telemetry agent when exact host measurements justify
   its separate privileges, freshness contract, and failure handling.

## Boundaries

Public exposure, arbitrary host-root access, privileged API containers, Docker-socket mounts,
process-control APIs, unrestricted ACL editing, cross-location moves, implicit overwrites, and
automatic destructive cleanup remain outside the supported feature set. Quotas, file versioning,
sync clients, notifications, and new integrations need concrete requirements and a reviewed design.

Kubernetes, Kafka, Elasticsearch, Redis, and microservices are not required by the current workload.
