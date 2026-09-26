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

## Phase 5: System Information

Status: implemented.

Expand the existing System integration into an authenticated Runtime Information page. The Dashboard
retains compact uptime, CPU, memory, storage, and health cards, with a link to the dedicated page.
System information remains an `api-runtime-view`: configured labels, host-global kernel views,
container-visible hardware, and usage of the configured filesystem path are identified separately.

### Delivered Scope

- Identity: configured hostname and OS, kernel, architecture, API/Python versions, and host boot
  uptime distinguished from API runtime uptime.
- Compute: CPU model when available from bounded `/proc/cpuinfo`, logical cores, utilization, load
  averages, frequency, and detected GPUs. Inspect only bounded DRM device metadata under
  `/sys/class/drm`; where available, match an NVIDIA PCI slot to the bounded driver-reported model
  under `/proc/driver/nvidia/gpus`. Otherwise show vendor and PCI ID, or `Unavailable`. These are
  kernel-visible devices, not proof the API can use them or measure GPU utilization.
- Memory and storage: normalized RAM/swap and configured-path disk usage; filesystem type is
  optional. Neither metric claims exact cgroup or user-content capacity.
- Temperatures: normalized Celsius readings labeled by meaning rather than raw driver identifiers.
  `Package id 0` becomes CPU package 0, `jc42` a memory module, and `acpitz` an ACPI thermal zone;
  recognized motherboard labels distinguish chipset, motherboard CPU sensor, VRM, and external
  header;
  unfamiliar identifiers become Other temperature sensor. Keep the original identifier as supporting
  context. Do not infer ambient temperature or a precise physical location from an ACPI zone.
- Read-only `GET /api/system/information` with explicit section availability, source, safe warnings,
  and collection time; `GET /api/system` remains the compact dashboard contract. The System page
  fetches independently of dashboard integrations and offers retry and manual refresh.

The page leads with grouped temperature readings and a nearby refresh control. It keeps the prior
readings visible during refresh or failure, so checking new temperatures does not lose the user's
place. Raw sensor IDs are available in a disclosure, while metric-scope guidance sits at the bottom.
API package version and unqualified 1/5/15-minute load averages remain in the API contract for
diagnostics but are omitted from the daily-use page.

Missing sensors and GPU metadata are normal unavailable states, not page failures. No process list,
process API, or background polling is provided: container-only processes did not give useful host
information. No system snapshots are stored in PostgreSQL, and Phase 5 requires no database
migration, host mounts, Docker socket, privileged namespaces, or root access.

Backend checks cover normalized data, sensor naming and unknown labels, GPU model/PCI fallback and
missing devices, partial collection failures, authentication, and dashboard compatibility. Frontend
checks cover independent navigation and retry, meaningful labels, GPU availability, and empty
sensor states. Run the standard backend/frontend checks and a loopback-proxy Compose smoke test.

### Future Host Telemetry

Exact host-wide processes, physical hardware, temperatures, and disks are not guaranteed from the
API container. A later dedicated host agent may collect an allowlisted set of normalized metrics and
expose them through a narrow authenticated local socket. The agent must be reviewed separately for
privileges, authentication, authorization, freshness, failure behavior, and disclosure risk.

### Out Of Scope

- Exact host telemetry without a dedicated authenticated agent.
- Container-only process listings or a process-control API.
- Killing, restarting, pausing, or otherwise controlling processes.
- Real-time process streaming or historical metric storage.
- Charts, alerts, notifications, or automated remediation.
- Network packet capture or unrestricted network inspection.
- Filesystem browsing or file-content access.
- Docker socket access, host-root mounts, privileged containers, and root-only collection.

## Phase 6: Version 0.6 UI/UX Overhaul

Status: implemented. This phase covers the presentation and usability of sign-in, Dashboard,
Drive Workspace, and System Information. The original project prompt proposed a password-vault
integration for Phase 6; the current roadmap defers that work to a later phase.

### Scope and Constraints

Make Ark Cloud a coherent, readable, professional private infrastructure console on desktop,
tablet, and phone. Improve visual hierarchy, navigation clarity, interaction feedback, responsive
layouts, and accessibility **without changing functionality**. Preserve all existing routes and
hash links, API contracts and requests, authentication and OAuth flows, Drive sync and search
semantics, mutation behavior, and the accuracy of data-source and availability labels. Do not add
new pages, integrations, settings, actions, telemetry, charts, polling, theme toggles, or backend
work. Google Drive remains the source of truth for file content and operations; system readings
remain the API runtime's view, not exact host telemetry.

### Design Direction

Use a dark-first operations-console aesthetic specific to Ark's three daily tasks: checking system
health, finding indexed Drive items, and understanding the provenance of readings. Keep the
information density, but give primary readings and actions more prominence than supporting
metadata. Start with a compact, reusable design system rather than introducing a component
framework:

- Foundation: midnight canvas `#0B1420`, slate surfaces `#132333`, raised surface `#1B3041`,
  primary text `#E8F0F2`, signal blue `#89A8FF` in dark mode and `#174EA6` in light mode, and
  restrained amber/red for existing warning and failure states. The stronger blue and thicker
  horizontal indicators avoid the cyan-green shift seen while scrolling in Chrome.
- Pair Barlow Condensed headings with IBM Plex Sans interface text and IBM Plex Mono readings,
  timestamps, and source labels. Fonts are bundled locally with system fallbacks, without a
  third-party font request.
- Make the Dashboard's Ark server banner the signature **runtime readout**: compose its existing
  hostname, health state, uptime, and measurement-scope context in a scannable hierarchy. Do not
  imply that container-visible values are exact host measurements.
- Use spacing, typography, and restrained dividers to organize content. Reduce decorative grids,
  glow, and perpetual motion; reserve color for status, focus, and actionable information. Keep
  reduced-motion support.

### Implementation Record

The original delivery checklist is retained below for future UI regressions:

1. **Shared visual foundation:** Refine color, type, spacing, borders, density, buttons, inputs,
   status treatments, and focus states in `apps/web/src/styles.css`. Consolidate repeated visual
   rules as useful without obscuring the existing components. Give loading, error, unavailable,
   and empty states consistent hierarchy and actionable wording where an existing action exists.
2. **Sign-in and application shell:** Polish the login form, brand, sidebar, page titles, and action
   placement in `apps/web/src/App.tsx`. Keep named navigation visible and operable at narrow widths:
   the former tablet and phone layouts reduced the three links to `01`, `02`, and `03`. Keep the
   Dashboard's existing Refresh control accessible below 400 px instead of hiding it. Retain the
   same `#overview`, `#drive-workspace`, and `#system-information` destinations and logout flow.
3. **Dashboard:** Establish a clear scan order from Ark health and runtime scope to CPU, memory,
   and storage, then services, Tailscale devices, and Google Drive. Align card anatomy and state
   labels; distinguish healthy, degraded, unavailable, and not-configured states by text as well
   as color. Preserve the existing Drive actions, System Information link, timestamps, metrics,
   and partial-failure behavior.
4. **Drive Workspace:** Rebalance the sync console, My Drive/Recent/Starred modes, breadcrumbs,
   filters, results, saved searches, pins, storage insights, sync history, and sync-observed
   activity in `apps/web/src/DriveWorkspace.tsx`. Make the desktop listing efficiently scannable
   and its phone layout a readable record with name, location, modified time, size, and Drive
   action. Retain timestamps in the mobile history and activity views rather than hiding them.
   Preserve draft-versus-applied filters, pagination, retries, sync progress, saved preferences,
   and direct Google Drive links exactly as they work today.
5. **System Information:** Keep grouped temperatures first and manual refresh nearby in
   `apps/web/src/SystemInformationPage.tsx`. Improve alignment and wrapping for long sensor and
   hardware names, source descriptions, partial/unavailable states, and the Sensor IDs disclosure.
   Preserve independent fetching and the prior readings during a failed refresh.
6. **Copy and accessibility pass:** Use consistent, plain-language action labels and feedback;
   make errors and empty states explain the available next step. Review landmarks, control names,
   keyboard navigation, visible focus, status announcements, contrast, touch targets, zoom,
   overflow, and reduced motion. Avoid using color alone to communicate state.

### Regression Checklist

- Visually inspect signed-out and signed-in screens at desktop, tablet, and phone widths, including
  a narrow phone and a long-content/zoom case. Review configured, disconnected, loading, empty,
  partial, failure, and refreshing states using representative data; check that no important
  information or existing control disappears at a breakpoint.
- Exercise the existing journeys: sign in/out; navigate all three views and their links; refresh
  Dashboard and System Information; connect, refresh, and disconnect Drive; browse folders,
  search/filter, paginate, use saved searches and pins, sync and retry, and open items in Drive.
  Verify the behavior and resulting requests remain unchanged.
- Check keyboard-only operation, accessible names and status text, contrast, text enlargement,
  screen-reader reading order, and reduced-motion preference. Keep API-runtime scope and
  sync-observed/activity qualifiers visible and accurate.
- Run the frontend checks from `apps/web`: `npm test`, `npm run lint`,
  `npm run format:check`, and `npm run build`. Update focused frontend tests only where changed
  markup or navigation warrants regression coverage. No API migration or backend change is
  expected.

The implementation uses locally bundled fonts and shared appearance tokens; it preserves named
navigation and Dashboard refresh at phone widths, makes Drive result metadata and activity times
readable at narrow widths, and shows partial System Information warnings. Existing frontend tests
cover the links, controls, and Drive result labels without changing request behavior.

## Version 0.6 Appearance Preferences (Post-Phase 6)

Status: implemented. Light/dark mode and high contrast are two independent browser-local controls,
available on both the sign-in and signed-in screens. The four combinations share the same layout,
data, and actions. When a choice has not been saved, Ark Cloud follows the device's color-scheme
or contrast preference, including changes while the page is open. Explicit choices persist across
reloads and sign-in/out; unavailable browser storage does not prevent switching for the current
page. A small script applies saved preferences before the app loads to prevent a theme flash.
Theme tokens cover all existing screens and states, including status colors, focus rings, browser
controls, and the page theme color. No backend or account-preference storage is involved.

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
