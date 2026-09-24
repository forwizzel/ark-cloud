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

Status: implemented.

- Catalog normalized Google Drive file metadata without storing file content in Ark Cloud
- Search Drive metadata through an authenticated, principal-scoped API
- Open results directly in Google Drive for file operations
- Keep Google credentials, access tokens, and raw upstream payloads server-side
- Preserve Google Drive as the source of truth and PostgreSQL as control-plane and search-index
  storage only
- Reviewed OAuth scopes, pagination, synchronization, indexing, and privacy boundaries

The Phase 3 implementation retains `drive.metadata.readonly`, catalogs files owned by the connected
account in My Drive, performs the initial synchronization after OAuth connection, and uses a manual
incremental sync action backed by Drive change tokens. Shared files, shared drives, file-content
access, and scheduled workers remain deferred.

## Phase 4: Google Drive Workspace and Quality of Life

Status: implemented.

Make Google Drive a useful daily workspace inside Ark Cloud before adding another content
platform. Ark Cloud remains a control plane and metadata index; Google Drive remains the source of
truth for file content and file operations.

- Add folder browsing with breadcrumbs, recent files, starred files, and direct links to Drive
- Expand search with file-type, folder, date, size, ownership, and starred filters plus stable
  sorting and pagination
- Add saved searches and pinned Drive locations to the local control-plane state
- Improve result metadata with file type, size, modified time, parent folder, and useful status
  labels without storing file bodies
- Add quota and storage insights, including usage by type and reports for large or stale files
- Make quota and cleanup reports advisory; never delete or reorganize files automatically
- Make synchronization observable with last-successful-sync time, progress, history, retry state,
  and actionable failure messages
- Recover safely from expired or invalid Drive change tokens with a bounded full resynchronization
- Evaluate scheduled metadata synchronization only after its workload, locking, and failure
  behavior are defined and tested
- Review support for shared files and shared drives with explicit visibility and principal-scoping
  rules before expanding catalog coverage
- Add normalized Drive activity such as file creation, modification, and synchronization events
- Preserve the metadata-only boundary and keep OAuth credentials, access tokens, raw responses,
  and file content server-side
- Consider narrowly scoped, non-destructive Drive actions such as creating folders, renaming,
  moving, or starring files only after write scopes, confirmation, CSRF protection, audit events,
  and recovery behavior have been reviewed

Phase 4 does not require local photo storage, a NAS, or an Immich deployment. File uploads,
downloads, content proxying, bulk destructive actions, and automatic cleanup remain out of scope.

The Phase 4 implementation retains `drive.metadata.readonly` and adds a responsive Drive Workspace,
normalized folder relationships, filtered revision-bound listings, local saved searches and pins,
advisory storage reports, synchronization history, and activity derived from incremental catalog
changes. Expired Drive change tokens trigger one bounded full rebuild while preserving the prior
catalog if recovery fails. Upgrading from Version 0.3 also requires one full metadata sync to
populate the new folder and starred fields.

The scheduled-sync review found that durable job ownership, locking, shutdown recovery, backoff,
and quota behavior require a real worker design, so scheduling remains deferred. Shared files and
shared drives remain excluded until visibility, revoked-access, corpus, and per-drive cursor rules
are designed. Drive write actions remain deferred because they require broader OAuth scopes,
per-action confirmation, audit records, conflict handling, and recovery semantics.

## Later Direction

1. Immich status and metadata integration rather than custom photo management, once local or NAS
   storage is available and useful.
2. Backup monitoring with documented and tested restoration.
3. Safe Vaultwarden or Bitwarden metadata only, never custom password cryptography.
4. Extend unified search to supported integrations while excluding secrets.
5. Normalized activity and notifications across integrations.
6. Observational container and service health.
7. Focused notes or bookmarks where they support the control-plane purpose.
8. Mobile and PWA improvements.
9. Threat modeling, authentication, authorization, audit events, rate limiting, recovery,
   and production hardening.

Kubernetes, Kafka, Elasticsearch, Redis, native mobile applications, public exposure, and
destructive infrastructure controls remain non-goals until a concrete requirement justifies
them.
