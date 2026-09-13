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

## Later Direction

1. Private file storage with path traversal protections and access control.
2. Immich status and metadata integration rather than custom photo management.
3. Backup monitoring with documented and tested restoration.
4. Safe Vaultwarden or Bitwarden metadata only, never custom password cryptography.
5. Normalized activity and notifications.
6. Database-backed unified search that excludes secrets.
7. Observational container and service health.
8. Focused notes or bookmarks where they support the control-plane purpose.
9. Mobile and PWA improvements.
10. Threat modeling, authentication, authorization, audit events, rate limiting, recovery,
    and production hardening.

Kubernetes, Kafka, Elasticsearch, Redis, native mobile applications, public exposure, and
destructive infrastructure controls remain non-goals until a concrete requirement justifies
them.
