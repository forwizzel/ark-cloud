# Roadmap

Ark Cloud advances one usable, verified phase at a time. Later phases may change as actual
requirements become clearer.

## Phase 0: Foundation

Status: implemented.

- Monorepo with web and API applications
- Reproducible Docker Compose environment
- Private PostgreSQL service and migration baseline
- Validated environment configuration and structured API logging
- Database-aware backend health endpoint
- Responsive frontend status page
- Backend and frontend tests, linting, formatting, and builds
- Architecture, development, and security documentation

## Phase 1: Version 0.1

Status: implemented.

- Minimal integration health and summary contract
- Non-root runtime System integration for hostname, OS, kernel, uptime, CPU, memory, and
  disk usage
- Optional server-side Tailscale device integration with a mockable HTTP boundary
- Dashboard assembled from normalized integration summaries
- Connector failure, degraded resource, and unconfigured integration tests
- Documented path from runtime collection to a dedicated least-privilege host agent

The Phase 1 security review retains loopback-only binding by default. Authentication and
HTTPS are still required before Ark Cloud is treated as more than a trusted private service.

## Phase 2: Version 0.2

Status: finalized.

- Local single-user session authentication with CSRF protection
- Optional server-side Google OAuth connection and encrypted refresh-token persistence
- Normalized Google Drive connection health and storage quota on the dashboard
- Google Drive remains the file manager and source of truth; Ark Cloud never proxies file content

## Phase 3: Drive Catalog and Unified Search

Status: planned.

- Catalog normalized Google Drive file metadata without storing file content in Ark Cloud
- Search Drive metadata through an authenticated, principal-scoped API
- Open results directly in Google Drive for file operations
- Keep Google credentials, access tokens, and raw upstream payloads server-side
- Preserve Google Drive as the source of truth and PostgreSQL as control-plane and search-index
  storage only
- Review OAuth scopes, pagination, synchronization, indexing, and privacy before implementation

## Later Direction

1. Immich status and metadata integration rather than custom photo management.
2. Backup monitoring with documented and tested restoration.
3. Safe Vaultwarden or Bitwarden metadata only, never custom password cryptography.
4. Normalized activity and notifications.
5. Extend unified search to supported integrations while excluding secrets.
6. Observational container and service health.
7. Focused notes or bookmarks where they support the control-plane purpose.
8. Mobile and PWA improvements.
9. Threat modeling, authentication, authorization, audit events, rate limiting, recovery,
    and production hardening.

Kubernetes, Kafka, Elasticsearch, Redis, native mobile applications, public exposure, and
destructive infrastructure controls remain non-goals until a concrete requirement justifies
them.
