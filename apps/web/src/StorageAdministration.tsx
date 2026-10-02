import { useEffect, useEffectEvent, useState } from "react";
import { administrationRoute, locationHref } from "./administrationRoutes";
import {
  fetchStorageAdministration,
  storageRequest,
  submitStorageOperation,
  type ManagedLocation,
  type StorageAdministration as Snapshot,
  type StorageJob,
  type StorageOperation,
} from "./storageAdminApi";
import StorageAccess from "./StorageAccess";
import StorageActivity from "./StorageActivity";
import StorageConnection from "./StorageConnection";
import "./storage-administration.css";

const active = (job: StorageJob) =>
  ["queued", "applying", "verifying"].includes(job.state);
const titles: Record<string, string> = {
  add: "Connect location",
  init: "Create private folders",
  repair: "Repair connection",
  inspect: "Inspect location",
  update: "Configure location",
  remove: "Disconnect location",
  check: "Verify access",
  "refresh-identity": "Reconnect reviewed disk",
  relocate: "Move private base",
  settings: "Upload policy",
  access: "Account access",
  setup: "Storage setup",
};
const failure = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Storage is temporarily unavailable.";

export default function StorageAdministration({
  csrfToken,
  route = window.location.hash,
}: {
  csrfToken: string;
  route?: string;
}) {
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sending, setSending] = useState(false);
  const [waiting, setWaiting] = useState<string | null>(null);
  const page = administrationRoute(route);
  const accept = useEffectEvent((next: Snapshot) => {
    setData(next);
    setError("");
    if (!waiting) return;
    const job = next.jobs.find((item) => item.id === waiting);
    if (!job || active(job)) return;
    setWaiting(null);
    setNotice(job.message);
    if (job.state === "completed" && page.page === "new") {
      const id = job.result.existing_root_id ?? job.payload.root_id;
      if (id) window.location.hash = locationHref(id).slice(1);
    }
  });
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await fetchStorageAdministration(
          csrfToken,
          controller.signal,
        );
        if (!controller.signal.aborted) accept(next);
      } catch (problem) {
        if (!controller.signal.aborted) setError(failure(problem));
      } finally {
        if (!controller.signal.aborted)
          timer = setTimeout(() => void poll(), 3000);
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [csrfToken]);
  const busy = sending || Boolean(waiting) || Boolean(data?.jobs.some(active));
  const queued = (job: StorageJob) => {
    if (job.state === "completed") {
      const id = job.result.existing_root_id ?? job.payload.root_id;
      if (id) window.location.hash = locationHref(id).slice(1);
      setNotice(job.message);
    } else setWaiting(job.id);
    setData((current) =>
      current ? { ...current, jobs: [job, ...current.jobs] } : current,
    );
  };
  async function send(operation: StorageOperation) {
    setSending(true);
    setNotice("");
    try {
      queued(
        await submitStorageOperation(
          { ...operation, confirmed: true, automatic_access: true },
          csrfToken,
        ),
      );
    } catch (problem) {
      setNotice(failure(problem));
    } finally {
      setSending(false);
    }
  }
  async function refresh() {
    setData(await fetchStorageAdministration(csrfToken));
  }
  if (!data)
    return (
      <div className="panel storage-section administration-loading">
        <p role={error ? "alert" : "status"}>
          {error || "Loading administration…"}
        </p>
      </div>
    );
  const selected = data.roots.find((root) => root.id === page.rootId);
  const jobs =
    page.page === "location"
      ? data.jobs.filter((job) => job.payload.root_id === selected?.id)
      : data.jobs;
  const canApply = data.manager.online && !data.configuration_error && !busy;
  const activity = (
    <StorageActivity
      jobs={jobs}
      csrfToken={csrfToken}
      busy={busy}
      titles={titles}
      onNotice={setNotice}
      onRefresh={refresh}
      onRetry={(job) => {
        setSending(true);
        void storageRequest<StorageJob>(
          `admin/storage/jobs/${encodeURIComponent(job.id)}/retry`,
          csrfToken,
          "POST",
        )
          .then(queued)
          .catch((problem) => setNotice(failure(problem)))
          .finally(() => setSending(false));
      }}
    />
  );
  return (
    <div className="storage-admin">
      {page.page !== "overview" && (
        <nav className="administration-subnav" aria-label="Storage pages">
          <a
            href="#administration/storage"
            aria-current={page.page === "storage" ? "page" : undefined}
          >
            Locations
          </a>
          <a
            href="#administration/storage/settings"
            aria-current={page.page === "settings" ? "page" : undefined}
          >
            Settings
          </a>
          <a
            href="#administration/storage/diagnostics"
            aria-current={page.page === "diagnostics" ? "page" : undefined}
          >
            Diagnostics &amp; history
          </a>
        </nav>
      )}
      {error && (
        <p className="local-error" role="alert">
          {error} Ark reconnects automatically while mounts are applied.
        </p>
      )}
      {notice && (
        <p className="storage-notice" role="status">
          {notice}
        </p>
      )}
      {data.configuration_error && (
        <p className="local-error" role="alert">
          {data.configuration_error}{" "}
          <a href="#administration/storage/diagnostics">Open diagnostics</a>
        </p>
      )}
      {waiting && (
        <p role="status">
          {data.jobs.find((job) => job.id === waiting)?.message ??
            "Preparing access and verifying the connection…"}
        </p>
      )}
      {page.page === "overview" && (
        <section
          className="panel administration-overview"
          aria-labelledby="administration-overview-heading"
        >
          <header className="administration-overview-heading">
            <h2 id="administration-overview-heading">
              Administration overview
            </h2>
          </header>
          <ul className="administration-destinations">
            <li>
              <a href="#administration/storage">
                <div className="administration-destination-copy">
                  <h3>Storage</h3>
                  <p>
                    {
                      data.roots.filter((root) => root.state === "healthy")
                        .length
                    }{" "}
                    connected locations ·{" "}
                    {
                      data.roots.filter((root) => root.state !== "healthy")
                        .length
                    }{" "}
                    need attention
                  </p>
                </div>
                <span className="administration-destination-action">
                  Manage storage <DestinationArrow />
                </span>
              </a>
            </li>
            <li>
              <a href="#administration/users">
                <div className="administration-destination-copy">
                  <h3>Users</h3>
                  <p>
                    {data.users.filter((user) => user.active).length} active
                    accounts ·{" "}
                    {data.users.filter((user) => user.pending).length}{" "}
                    invitations pending
                  </p>
                </div>
                <span className="administration-destination-action">
                  Manage users <DestinationArrow />
                </span>
              </a>
            </li>
          </ul>
          {(data.configuration_error || !data.manager.online) && (
            <p className="administration-attention">
              Host storage management needs attention.{" "}
              <a href="#administration/storage/diagnostics">
                View deployment status
              </a>
            </p>
          )}
        </section>
      )}
      {page.page === "storage" && (
        <section
          className="panel storage-section"
          aria-labelledby="locations-heading"
        >
          <div className="storage-section-heading">
            <h2 id="locations-heading">Storage locations</h2>
            <a
              className="storage-primary-link"
              href="#administration/storage/new"
            >
              Add location
            </a>
          </div>
          {!data.roots.length && (
            <div className="local-empty">
              <h3>Your files need a location</h3>
              <p>
                Create a folder or connect one of the server's authorized
                directories. Ark configures and verifies access automatically.
              </p>
            </div>
          )}
          <ul className="storage-locations">
            {data.roots.map((root) => (
              <li key={root.id}>
                <div className="storage-location-identity">
                  <h3>
                    <a href={locationHref(root.id)}>{root.label}</a>
                  </h3>
                  <p className="storage-path">{root.source}</p>
                  <p>
                    {root.kind === "managed"
                      ? "Private account folders"
                      : "Shared files"}{" "}
                    · {root.access_count ?? 0} accounts
                  </p>
                  <p
                    className={`storage-connection-state ${root.state === "healthy" ? "storage-connection-state--healthy" : "storage-connection-state--attention"}`}
                  >
                    {root.state === "healthy"
                      ? "Connected"
                      : root.connection_state === "preparing"
                        ? "Preparing access"
                        : root.connection_state === "verifying"
                          ? "Verifying"
                          : "Needs repair"}
                  </p>
                </div>
                <div className="local-actions">
                  <a href={locationHref(root.id)}>Open location</a>
                  <a href={locationHref(root.id, "access")}>Manage access</a>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      {page.page === "new" && (
        <StorageConnection
          key="new"
          data={data}
          csrfToken={csrfToken}
          onQueued={queued}
        />
      )}
      {page.page === "settings" && (
        <StorageSettings
          data={data}
          csrfToken={csrfToken}
          onNotice={setNotice}
          onRefresh={refresh}
        />
      )}
      {page.page === "diagnostics" && (
        <section className="panel storage-section">
          <h2>Storage diagnostics &amp; history</h2>
          <p>
            Host management:{" "}
            {data.manager.online
              ? "Connected"
              : data.manager.enrolled
                ? "Unavailable"
                : "Not provisioned by deployment"}
            .
          </p>
          <p className="storage-path">
            Managed storage area:{" "}
            {data.manager.managed_area ?? "Not provisioned"}
          </p>
          <ul className="storage-assignments">
            {data.manager.approved_areas?.map((area) => (
              <li key={area.path}>
                <strong className="storage-path">{area.path}</strong>
                <span>{area.message}</span>
              </li>
            ))}
          </ul>
          {data.roots.map((root) => (
            <div key={root.id}>
              <h3>
                <a href={locationHref(root.id)}>{root.label}</a>
              </h3>
              <p>{root.message}</p>
              <Checks root={root} />
            </div>
          ))}
          {activity}
        </section>
      )}
      {page.page === "location" &&
        (!selected ? (
          <p role="alert">
            This location is no longer registered.{" "}
            <a href="#administration/storage">Return to locations</a>
          </p>
        ) : (
          <>
            <header className="storage-detail-heading">
              <a href="#administration/storage">Back to locations</a>
              <h2>{selected.label}</h2>
              <p className="storage-path">{selected.source}</p>
              <nav
                className="administration-subnav"
                aria-label="Location pages"
              >
                {(
                  ["overview", "access", "configuration", "activity"] as const
                ).map((tab) => (
                  <a
                    key={tab}
                    href={locationHref(selected.id, tab)}
                    aria-current={page.tab === tab ? "page" : undefined}
                  >
                    {tab === "overview"
                      ? "Connection"
                      : tab === "access"
                        ? "Access"
                        : tab === "configuration"
                          ? "Configuration"
                          : "Activity"}
                  </a>
                ))}
              </nav>
            </header>
            {page.tab === "overview" && (
              <section className="panel storage-section">
                <h3>
                  {selected.state === "healthy"
                    ? "Connected"
                    : "Connection needs repair"}
                </h3>
                <p>{selected.message}</p>
                <Checks root={selected} />
                {selected.state !== "healthy" && (
                  <button
                    className="refresh-button"
                    disabled={!canApply}
                    onClick={() =>
                      void send({
                        action: "repair",
                        root_id: selected.id,
                        registration: selected.registration ?? undefined,
                      })
                    }
                  >
                    Repair connection
                  </button>
                )}
                <p>
                  {selected.kind === "managed"
                    ? "Each account's files stay in its own private folder."
                    : "Accounts granted access share the same files."}
                </p>
                <a href={locationHref(selected.id, "access")}>
                  Manage account access
                </a>
                {selected.state === "healthy" && (
                  <p>
                    <a href={`#local-files/${selected.id}`}>Open my files</a>
                  </p>
                )}
              </section>
            )}
            {page.tab === "access" && (
              <StorageAccess
                key={selected.id}
                root={selected}
                csrfToken={csrfToken}
                onClose={() => {
                  window.location.hash = locationHref(selected.id).slice(1);
                }}
                onChanged={refresh}
              />
            )}
            {page.tab === "configuration" && (
              <LocationConfiguration
                key={selected.id}
                root={selected}
                canApply={canApply}
                onSend={send}
              />
            )}
            {page.tab === "activity" && (
              <section className="panel storage-section">
                <h3>Location activity</h3>
                {activity}
              </section>
            )}
          </>
        ))}
    </div>
  );
}

function DestinationArrow() {
  return (
    <svg
      aria-hidden="true"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 12h14m-6-6 6 6-6 6" />
    </svg>
  );
}

function Checks({ root }: { root: ManagedLocation }) {
  return root.checks?.length ? (
    <ul className="storage-checks">
      {root.checks.map((check, index) => (
        <li key={`${check.code}-${index}`}>
          <span className={check.state === "blocked" ? "local-error" : ""}>
            {check.state === "passed"
              ? "Passed"
              : check.state === "blocked"
                ? "Blocked"
                : "Pending"}
          </span>
          <span>{check.message}</span>
        </li>
      ))}
    </ul>
  ) : null;
}

function StorageSettings({
  data,
  csrfToken,
  onNotice,
  onRefresh,
}: {
  data: Snapshot;
  csrfToken: string;
  onNotice: (value: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const [limit, setLimit] = useState(String(data.upload_max_bytes / 1024 ** 2));
  const [busy, setBusy] = useState(false);
  async function save(value: number | null) {
    setBusy(true);
    try {
      if (
        value !== null &&
        (!Number.isSafeInteger(value) || value < 1 || value > 10 * 1024 ** 3)
      )
        throw new Error("Choose a size between 1 byte and 10 GiB.");
      await storageRequest("admin/storage/settings", csrfToken, "PUT", {
        upload_max_bytes: value,
      });
      await onRefresh();
      onNotice("Upload policy saved. No restart needed.");
    } catch (problem) {
      onNotice(failure(problem));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel storage-section">
      <h2>Storage settings</h2>
      <h3>Maximum file size</h3>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save(Number(limit) * 1024 ** 2);
        }}
      >
        <label>
          File size (MiB)
          <input
            required
            type="number"
            min="0.000001"
            step="any"
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
          />
        </label>
        <div className="local-actions">
          <button disabled={busy}>Save limit</button>
          <button type="button" disabled={busy} onClick={() => void save(null)}>
            Use deployment default
          </button>
        </div>
      </form>
      <p>
        Effective limit: {new Intl.NumberFormat().format(data.upload_max_bytes)}{" "}
        bytes.
      </p>
      <h3>Host-managed area</h3>
      <p className="storage-path">
        {data.manager.managed_area ??
          "Deployment has not provisioned host management."}
      </p>
      <p>
        Filesystem provisioning is handled by the deployment owner’s service.
        Account permissions are managed on each location.
      </p>
    </section>
  );
}

function LocationConfiguration({
  root,
  canApply,
  onSend,
}: {
  root: ManagedLocation;
  canApply: boolean;
  onSend: (operation: StorageOperation) => Promise<void>;
}) {
  const [label, setLabel] = useState(root.label);
  const [destination, setDestination] = useState("");
  const [confirm, setConfirm] = useState<"remove" | "refresh-identity" | null>(
    null,
  );
  return (
    <section className="panel storage-section">
      <h3>Location configuration</h3>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void onSend({
            action: "update",
            root_id: root.id,
            label,
            owner: root.owner ?? undefined,
            read_only: root.read_only,
            selinux: root.selinux,
          });
        }}
      >
        <label>
          Location name
          <input
            required
            maxLength={80}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
        </label>
        <button disabled={!canApply}>Save name</button>
      </form>
      {root.kind === "managed" && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void onSend({
              action: "relocate",
              root_id: root.id,
              path: destination,
              label: root.label,
              managed: true,
            });
          }}
        >
          <h3>Move private-folder base</h3>
          <label>
            New server directory
            <input
              required
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
            />
          </label>
          <p>
            Ark copies and verifies the account folders. The original files
            remain on the server.
          </p>
          <button disabled={!canApply}>Copy and move base</button>
        </form>
      )}
      <div className="local-actions">
        <button
          disabled={!canApply}
          onClick={() => void onSend({ action: "check", root_id: root.id })}
        >
          Verify access
        </button>
        <button
          disabled={!canApply}
          onClick={() => setConfirm("refresh-identity")}
        >
          Accept reviewed disk identity
        </button>
        <button disabled={!canApply} onClick={() => setConfirm("remove")}>
          Disconnect
        </button>
      </div>
      {confirm && (
        <div className="storage-notice">
          <p>
            {confirm === "remove"
              ? "Disconnect this location? Account access is removed and files stay on the server."
              : "Accept this disk's current identity only after verifying the intended disk and files are present."}
          </p>
          <div className="local-actions">
            <button
              disabled={!canApply}
              onClick={() => void onSend({ action: confirm, root_id: root.id })}
            >
              {confirm === "remove"
                ? "Confirm disconnect"
                : "Confirm reviewed identity"}
            </button>
            <button onClick={() => setConfirm(null)}>Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}
