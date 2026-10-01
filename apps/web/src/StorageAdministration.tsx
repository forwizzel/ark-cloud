import {
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  fetchStorageAdministration,
  storageRequest,
  submitStorageOperation,
  type ManagedLocation,
  type StorageAdministration,
  type StorageJob,
  type StorageOperation,
  type AccessLevel,
} from "./storageAdminApi";
import "./storage-administration.css";
import StorageSetup from "./StorageSetup";
import StorageActivity from "./StorageActivity";
import StorageAccess from "./StorageAccess";
import SharedStorageSetup from "./SharedStorageSetup";

const failureMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Storage operation failed.";
const active = (job: StorageJob) =>
  ["queued", "applying", "verifying"].includes(job.state);
const titles: Record<string, string> = {
  add: "Connect folder",
  init: "Create private account folders",
  update: "Configure location",
  remove: "Disconnect location",
  "refresh-identity": "Reconnect reviewed directory",
  check: "Check access",
  settings: "Upload policy",
  browse: "Browse host folders",
  preflight: "Review folder",
  relocate: "Change private-folder base",
  setup: "Set up Local Files",
  access: "Account access",
};

export default function StorageAdministration({
  csrfToken,
}: {
  csrfToken: string;
}) {
  const [data, setData] = useState<StorageAdministration | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<StorageOperation | null>(null);
  const [accessRoot, setAccessRoot] = useState<ManagedLocation | null>(null);
  const [sharedSetup, setSharedSetup] = useState(false);
  const [review, setReview] = useState<StorageJob | null>(null);
  const [waiting, setWaiting] = useState<{
    id: string;
    purpose: "browse" | "review" | "apply";
  } | null>(null);
  const [browser, setBrowser] = useState<StorageJob["result"] | null>(null);
  const [limit, setLimit] = useState("");
  const [unit, setUnit] = useState("MiB");
  const [limitLoaded, setLimitLoaded] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);

  const acceptSnapshot = useEffectEvent((next: StorageAdministration) => {
    setData(next);
    setError("");
    if (!limitLoaded) {
      setLimit(String(next.upload_max_bytes / 1024 ** 2));
      setUnit("MiB");
      setLimitLoaded(true);
    }
    if (!waiting) return;
    const job = next.jobs.find((job) => job.id === waiting.id);
    if (!job || active(job)) return;
    setWaiting(null);
    if (job.state === "failed") {
      setNotice(job.message);
      return;
    }
    if (waiting.purpose === "browse") setBrowser(job.result);
    if (waiting.purpose === "review") setReview(job);
    if (waiting.purpose === "apply") {
      setEditor(null);
      setBrowser(null);
      setReview(null);
      setNotice(job.message);
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
        if (!controller.signal.aborted) {
          acceptSnapshot(next);
        }
      } catch (error) {
        if (!controller.signal.aborted)
          setError(
            `${failureMessage(error)} Ark will reconnect automatically if storage changes are restarting the API.`,
          );
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

  const applying = busy || Boolean(waiting) || Boolean(data?.jobs.some(active));
  const canChange =
    data?.manager.online && !data.configuration_error && !applying;
  function edit(operation: StorageOperation) {
    setAccessRoot(null);
    setEditor(operation);
    setReview(null);
    setBrowser(null);
    setNotice("");
    requestAnimationFrame(() => heading.current?.focus());
  }
  function field(change: Partial<StorageOperation>) {
    setEditor((value) => (value ? { ...value, ...change } : value));
    setReview(null);
  }
  async function send(
    operation: StorageOperation,
    purpose: "browse" | "review" | "apply",
  ) {
    setBusy(true);
    setNotice("");
    try {
      const job = await submitStorageOperation(operation, csrfToken);
      setWaiting({ id: job.id, purpose });
      setData((current) =>
        current ? { ...current, jobs: [job, ...current.jobs] } : current,
      );
    } catch (error) {
      setNotice(failureMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function saveLimit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    const bytes =
      Number(limit) *
      (unit === "GiB" ? 1024 ** 3 : unit === "MiB" ? 1024 ** 2 : 1);
    try {
      if (!Number.isSafeInteger(bytes) || bytes < 1 || bytes > 10 * 1024 ** 3)
        throw new Error("Choose a file size between 1 byte and 10 GiB.");
      await storageRequest("admin/storage/settings", csrfToken, "PUT", {
        upload_max_bytes: bytes,
      });
      setNotice("Maximum file size saved. No restart needed.");
    } catch (error) {
      setNotice(failureMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function refreshInventory() {
    const next = await fetchStorageAdministration(csrfToken);
    setData(next);
  }
  function connectExisting() {
    edit({
      action: "add",
      label: "",
      path: "",
      read_only: false,
      selinux: "preserve",
      shared: true,
      grants: newGrants(),
    });
  }
  function newGrants() {
    return (
      data?.users
        .filter((user) => user.active)
        .map((user) => ({
          user_id: user.id,
          level: user.current ? ("write" as const) : ("none" as const),
        })) ?? []
    );
  }
  function configure(
    root: ManagedLocation,
    action: StorageOperation["action"],
  ) {
    edit({
      action,
      root_id: root.id,
      path: root.source,
      label: root.label,
      owner: root.owner ?? undefined,
      read_only: root.read_only,
      selinux: root.selinux,
      managed: root.kind === "managed",
    });
  }

  if (!data)
    return (
      <p role={error ? "alert" : "status"}>
        {error || "Loading storage administration…"}
      </p>
    );
  return (
    <div className="storage-admin">
      <div className="storage-admin-intro">
        <div>
          <h2>Local Storage</h2>
          <p>Choose where Ark keeps files and who can use each location.</p>
        </div>
        <a href="#local-files">Open my files</a>
      </div>
      {error && (
        <p className="local-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="storage-notice" role="status">
          {notice}
        </p>
      )}
      {data.configuration_error && (
        <section
          className="panel storage-section"
          aria-labelledby="storage-recovery-heading"
        >
          <h3 id="storage-recovery-heading">
            Storage configuration needs host attention
          </h3>
          <p className="local-error" role="alert">
            {data.configuration_error}
          </p>
          <p>
            Storage changes are paused until the API can read its manifest. On
            the Ark server, check the host configuration and file permissions,
            then reload this page. The host owner can run{" "}
            <code>./scripts/ark storage check</code> after restoring access.
            Activity and diagnostics remain available below.
          </p>
        </section>
      )}
      <StorageSetup data={data} onConnect={connectExisting} />
      {!data.manager.online && data.roots.length > 0 && (
        <p role="status">
          The host helper is{" "}
          {data.manager.enrolled ? "offline" : "not enrolled"}. Connected files
          remain usable. Reconnect it to change locations.
        </p>
      )}
      {data.manager.approved_areas
        ?.filter((area) => area.state !== "ready")
        .map((area) => (
          <p key={area.path} className="local-error">
            Approved host area <span className="storage-path">{area.path}</span>
            : {area.message}
          </p>
        ))}
      <section
        className="panel storage-section"
        aria-labelledby="locations-heading"
      >
        <div className="storage-section-heading">
          <h3 id="locations-heading">Locations</h3>
          <div className="local-actions">
            <button
              className="refresh-button"
              disabled={!canChange}
              onClick={connectExisting}
            >
              Connect existing folder
            </button>
            <button onClick={() => setSharedSetup((value) => !value)}>
              {sharedSetup ? "Hide shared setup" : "Create shared folder"}
            </button>
            {!data.roots.some((root) => root.kind === "managed") && (
              <button
                disabled={!canChange}
                onClick={() =>
                  edit({
                    action: "init",
                    label: "My files",
                    path: "",
                    managed: true,
                    grants: newGrants(),
                  })
                }
              >
                Create private account folders
              </button>
            )}
          </div>
        </div>
        {!data.roots.length && (
          <div className="local-empty">
            <h4>Choose where your files belong</h4>
            <p>
              Use the setup wizard above to create your cloud storage, or
              connect an existing folder to an account.
            </p>
          </div>
        )}
        <ul className="storage-locations">
          {data.roots.map((root) => (
            <li key={root.id}>
              <div className="storage-location-identity">
                <h4>{root.label}</h4>
                <p className="storage-path">{root.source}</p>
                <p>
                  {root.kind === "managed"
                    ? "Private folders for accounts"
                    : "Shared directory"}{" "}
                  ·{" "}
                  {root.read_only
                    ? "Host mount read-only"
                    : "Host mount read / write"}
                </p>
                <p>
                  Access for {root.access_count ?? (root.owner ? 1 : 0)}{" "}
                  accounts
                </p>
                <p className={root.state === "healthy" ? "" : "local-error"}>
                  {root.message}
                </p>
              </div>
              <div className="local-actions">
                <button
                  disabled={Boolean(data.configuration_error) || applying}
                  onClick={() => {
                    setEditor(null);
                    setAccessRoot(root);
                  }}
                >
                  Manage access
                </button>
                <button
                  disabled={!canChange}
                  onClick={() => configure(root, "update")}
                >
                  Configure
                </button>
                {root.kind === "managed" && (
                  <button
                    disabled={!canChange}
                    onClick={() => {
                      edit({
                        action: "relocate",
                        root_id: root.id,
                        label: root.label,
                        path: "",
                        managed: true,
                      });
                    }}
                  >
                    Change base directory
                  </button>
                )}
                <button
                  disabled={!canChange}
                  onClick={() => configure(root, "check")}
                >
                  Check access
                </button>
                <button
                  disabled={!canChange}
                  onClick={() => configure(root, "refresh-identity")}
                >
                  Reconnect
                </button>
                <button
                  disabled={!canChange}
                  onClick={() => configure(root, "remove")}
                >
                  Disconnect
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {sharedSetup && (
        <SharedStorageSetup
          canCreate={Boolean(canChange)}
          onCreate={() =>
            edit({
              action: "add",
              shared: true,
              create_directory: true,
              label: "Shared files",
              path: "",
              read_only: false,
              selinux: "private",
              grants: newGrants(),
            })
          }
        />
      )}
      {accessRoot && (
        <StorageAccess
          key={accessRoot.id}
          root={accessRoot}
          csrfToken={csrfToken}
          onClose={() => setAccessRoot(null)}
          onChanged={refreshInventory}
        />
      )}

      {editor && (
        <section
          className="panel storage-section"
          aria-labelledby="storage-editor-heading"
        >
          <h3 id="storage-editor-heading" tabIndex={-1} ref={heading}>
            {titles[editor.action]}
          </h3>
          {waiting && (
            <p role="status">
              {data.jobs.find((job) => job.id === waiting.id)?.message ??
                "Waiting for the host storage manager…"}
            </p>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!applying)
                void send(
                  review || !["add", "init"].includes(editor.action)
                    ? { ...editor, confirmed: true }
                    : { ...editor, action: "preflight" },
                  review || !["add", "init"].includes(editor.action)
                    ? "apply"
                    : "review",
                );
            }}
          >
            <fieldset disabled={applying || !canChange}>
              {["add", "init", "update", "relocate"].includes(editor.action) ? (
                <>
                  <div className="storage-form-grid">
                    <label>
                      Location name
                      <input
                        required
                        maxLength={80}
                        readOnly={editor.action === "relocate"}
                        value={editor.label ?? ""}
                        onChange={(event) =>
                          field({ label: event.target.value })
                        }
                      />
                    </label>
                    {editor.action !== "update" && (
                      <label>
                        {editor.managed
                          ? "New private-folder base on the server"
                          : editor.create_directory
                            ? "New shared directory on the server"
                            : "Existing folder on the server"}
                        <input
                          required
                          placeholder="/your/disk/folder"
                          value={editor.path ?? ""}
                          onChange={(event) =>
                            field({ path: event.target.value })
                          }
                        />
                      </label>
                    )}
                    {!editor.managed && (
                      <label>
                        Host mount access
                        <select
                          value={editor.read_only ? "read" : "write"}
                          onChange={(event) =>
                            field({
                              read_only: event.target.value === "read",
                              grants: editor.grants?.map((grant) => ({
                                ...grant,
                                level:
                                  event.target.value === "read" &&
                                  grant.level === "write"
                                    ? "read"
                                    : grant.level,
                              })),
                            })
                          }
                        >
                          <option value="write">Read and write</option>
                          <option value="read">Read only</option>
                        </select>
                      </label>
                    )}
                  </div>
                  {["add", "init"].includes(editor.action) && editor.grants && (
                    <fieldset className="storage-initial-access">
                      <legend>Account permissions</legend>
                      <p>
                        {editor.managed
                          ? "Selected accounts get separate private folders."
                          : "Selected accounts will share the same files."}
                      </p>
                      {data.users
                        .filter((user) => user.active)
                        .map((user) => (
                          <label key={user.id}>
                            Access for {user.username}
                            {user.pending ? " · Invitation pending" : ""}
                            <select
                              value={
                                editor.grants?.find(
                                  (grant) => grant.user_id === user.id,
                                )?.level ?? "none"
                              }
                              onChange={(event) =>
                                field({
                                  grants: editor.grants?.map((grant) =>
                                    grant.user_id === user.id
                                      ? {
                                          ...grant,
                                          level: event.target
                                            .value as AccessLevel,
                                        }
                                      : grant,
                                  ),
                                })
                              }
                            >
                              <option value="none">No access</option>
                              <option value="read">Read-only</option>
                              <option value="write" disabled={editor.read_only}>
                                Read &amp; write
                              </option>
                            </select>
                          </label>
                        ))}
                    </fieldset>
                  )}
                  {editor.action === "update" && (
                    <p>
                      Use Manage access on this location to choose accounts and
                      their permissions.
                    </p>
                  )}
                  {editor.create_directory && (
                    <p>
                      Ark creates a new dedicated shared directory with
                      mapped-UID access and Ark-only container labels. Existing
                      directories are never repurposed.
                    </p>
                  )}
                  {editor.action !== "update" && (
                    <>
                      <button
                        type="button"
                        onClick={() =>
                          void send({ action: "browse", path: "" }, "browse")
                        }
                      >
                        Browse approved server folders
                      </button>
                      {browser && (
                        <div className="storage-folder-picker">
                          <p>{browser.path || "Host-owner-approved areas"}</p>
                          <div className="local-actions">
                            {browser.path && (
                              <button
                                type="button"
                                onClick={() => {
                                  field({
                                    path: editor.managed
                                      ? `${browser.path}/ark-files`
                                      : editor.create_directory
                                        ? `${browser.path}/shared-files`
                                        : browser.path,
                                  });
                                  setBrowser(null);
                                }}
                              >
                                Use this {editor.managed ? "parent" : "folder"}
                              </button>
                            )}
                            {browser.parent !== null && (
                              <button
                                type="button"
                                onClick={() =>
                                  void send(
                                    {
                                      action: "browse",
                                      path: browser.parent ?? "",
                                    },
                                    "browse",
                                  )
                                }
                              >
                                Up one level
                              </button>
                            )}
                          </div>
                          <ul>
                            {browser.folders?.map((folder) => (
                              <li key={folder}>
                                <button
                                  type="button"
                                  onClick={() =>
                                    void send(
                                      { action: "browse", path: folder },
                                      "browse",
                                    )
                                  }
                                >
                                  {folder.split("/").at(-1)}
                                </button>
                              </li>
                            ))}
                          </ul>
                          {!browser.folders?.length && (
                            <p>No eligible subfolders.</p>
                          )}
                        </div>
                      )}
                    </>
                  )}
                  {editor.managed && (
                    <p>
                      {editor.action === "relocate"
                        ? "Ark pauses API writes, copies account folders to the new base, verifies contents and permissions, then switches locations. The original directory is kept. Pause external applications writing to this tree until this completes. The new base receives private container labels."
                        : "Each account gets an isolated folder identified by its permanent account ID. This base must be new. Existing files are never moved by this setup."}
                    </p>
                  )}
                  {editor.action === "relocate" && (
                    <label className="storage-checkbox">
                      <input type="checkbox" required />
                      Copy to the new base and keep the original files
                    </label>
                  )}
                  {!editor.managed && (
                    <details>
                      <summary>Advanced access and SELinux</summary>
                      <label>
                        Host labeling
                        <select
                          value={editor.selinux ?? "preserve"}
                          onChange={(event) =>
                            field({
                              selinux: event.target
                                .value as StorageOperation["selinux"],
                            })
                          }
                        >
                          <option value="preserve">
                            Preserve existing labels
                          </option>
                          <option value="private">
                            Relabel for Ark only (private)
                          </option>
                          <option value="shared">
                            Relabel for container sharing
                          </option>
                        </select>
                      </label>
                      <p>
                        Relabeling changes the selected tree recursively and may
                        affect other applications. Unix file permissions are
                        independent of labels. Read-only access does not change
                        labels.
                      </p>
                      <label className="storage-checkbox">
                        <input
                          type="checkbox"
                          checked={editor.grant_access ?? false}
                          onChange={(event) =>
                            field({ grant_access: event.target.checked })
                          }
                        />
                        Grant API access to this folder and future content
                      </label>
                      <p>
                        This adds a narrow ACL only when the host manager owns
                        the folder. It does not recursively change existing
                        children; those must already allow access.
                      </p>
                    </details>
                  )}
                </>
              ) : (
                <>
                  <p>
                    <strong>{editor.label}</strong>
                  </p>
                  <p className="storage-path">{editor.path}</p>
                  <p>
                    {editor.action === "remove"
                      ? "Disconnecting removes Ark access immediately. Files stay on the server; permissions and labels are not undone."
                      : editor.action === "check"
                        ? "This tests access as the API user. Writable locations receive a temporary file that is created, renamed, and removed."
                        : "First verify that the intended disk is mounted and this path contains the correct files. This explicitly accepts the directory’s current identity; do not accept an empty mountpoint for a missing disk."}
                  </p>
                </>
              )}
              {review && (
                <div className="storage-review" role="status">
                  <h4>Ready to connect</h4>
                  <p>{review.result.message}</p>
                  <p>
                    {editor.managed
                      ? "Ark will create separate private folders for selected accounts."
                      : "Selected accounts will share this directory."}{" "}
                    {editor.selinux && editor.selinux !== "preserve"
                      ? "You are authorizing recursive relabeling of this folder."
                      : "Existing file labels are preserved."}
                  </p>
                  <p>
                    {editor.grants
                      ?.filter((grant) => grant.level !== "none")
                      .map(
                        (grant) =>
                          `${data.users.find((user) => user.id === grant.user_id)?.username}: ${grant.level === "write" ? "read & write" : "read-only"}`,
                      )
                      .join(" · ")}
                  </p>
                  <details>
                    <summary>Runtime details</summary>
                    <p>API host UID: {review.result.api_host_uid}</p>
                  </details>
                </div>
              )}
              <p className="storage-help">
                {["browse", "preflight", "check"].includes(editor.action)
                  ? ""
                  : "Applying mount changes briefly restarts the API. Current transfers may be interrupted; Ark reconnects automatically."}
              </p>
              <div className="local-actions">
                <button type="submit" className="refresh-button">
                  {applying
                    ? "Working…"
                    : ["add", "init"].includes(editor.action)
                      ? review
                        ? editor.action === "init"
                          ? "Create private folders"
                          : "Connect folder"
                        : "Review folder"
                      : editor.action === "remove"
                        ? "Confirm disconnect"
                        : editor.action === "refresh-identity"
                          ? "Confirm reviewed directory"
                          : editor.action === "check"
                            ? "Run access test"
                            : editor.action === "relocate"
                              ? "Copy and switch base"
                              : "Apply changes"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditor(null);
                    setReview(null);
                    setBrowser(null);
                  }}
                >
                  Cancel
                </button>
              </div>
            </fieldset>
          </form>
        </section>
      )}

      <section
        className="panel storage-section"
        aria-labelledby="upload-policy-heading"
      >
        <h3 id="upload-policy-heading">Maximum file size</h3>
        <p>
          Per-file upload limit for every account. This is separate from disk
          space and personal quotas.
        </p>
        <form
          onSubmit={(event) => void saveLimit(event)}
          className="storage-policy-form"
        >
          <label>
            File size
            <input
              type="number"
              required
              min="0.000000001"
              step="any"
              value={limit}
              onChange={(event) => setLimit(event.target.value)}
            />
          </label>
          <label>
            Unit
            <select
              value={unit}
              onChange={(event) => setUnit(event.target.value)}
            >
              <option>MiB</option>
              <option>GiB</option>
              <option>B</option>
            </select>
          </label>
          <button className="refresh-button" disabled={busy}>
            Save limit
          </button>
        </form>
        <p>
          Up to 10 GiB. Effective limit:{" "}
          {new Intl.NumberFormat().format(data.upload_max_bytes)} bytes ·{" "}
          {data.upload_limit_source === "ui"
            ? "Saved in Ark"
            : "Environment default"}
        </p>
        <button
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void storageRequest("admin/storage/settings", csrfToken, "PUT", {
              upload_max_bytes: null,
            })
              .then(() => {
                setLimitLoaded(false);
                setNotice("Environment default restored.");
              })
              .catch((error) => setNotice(failureMessage(error)))
              .finally(() => setBusy(false));
          }}
        >
          Restore environment default
        </button>
      </section>

      <section
        className="panel storage-section"
        aria-labelledby="assignments-heading"
      >
        <h3 id="assignments-heading">Accounts and storage</h3>
        <ul className="storage-assignments">
          {data.users.map((user) => (
            <li key={user.id}>
              <strong>{user.username}</strong>
              <span>
                {!user.active
                  ? "Disabled · "
                  : user.pending
                    ? "Invitation pending · "
                    : ""}
                {data.roots
                  .filter((root) =>
                    root.access_accounts?.some(
                      (grant) =>
                        grant.user_id === user.id && grant.level !== "none",
                    ),
                  )
                  .map(
                    (root) =>
                      `${root.label} (${root.kind === "managed" ? "private" : "shared"})`,
                  )
                  .join(" · ") || "No locations assigned"}
              </span>
              <details>
                <summary>Permanent account ID</summary>
                <code>{user.id}</code>
              </details>
            </li>
          ))}
        </ul>
        <p>
          Username changes preserve assignments. Disabling or deleting an
          account removes access, not files.
        </p>
        <p>
          Use Manage access on each location to grant or revoke account
          permissions.
        </p>
        <a href="#administration-users">Manage accounts and invitations</a>
      </section>

      <section
        className="panel storage-section"
        aria-labelledby="activity-heading"
      >
        <h3 id="activity-heading">Activity &amp; diagnostics</h3>
        <StorageActivity
          jobs={data.jobs}
          csrfToken={csrfToken}
          busy={applying}
          titles={titles}
          onNotice={setNotice}
          onRefresh={refreshInventory}
          onRetry={(job) => {
            setBusy(true);
            void storageRequest<StorageJob>(
              `admin/storage/jobs/${encodeURIComponent(job.id)}/retry`,
              csrfToken,
              "POST",
            )
              .then((next) => setWaiting({ id: next.id, purpose: "apply" }))
              .catch((error) => setNotice(failureMessage(error)))
              .finally(() => setBusy(false));
          }}
        />
        {data.manager.enrolled && (
          <details>
            <summary>Host manager connection</summary>
            <p>
              {data.manager.online ? "Connected" : "Offline"}. Approved areas:{" "}
              {data.manager.approved_paths.join(", ") ||
                "Waiting for host inventory"}
            </p>
            <button
              disabled={applying}
              onClick={() => {
                if (
                  window.confirm(
                    "Revoke host manager access? Existing mounts and files are preserved. Host enrollment is required to reconnect.",
                  )
                )
                  void storageRequest(
                    "admin/storage/manager/revoke",
                    csrfToken,
                    "POST",
                  )
                    .then(() => setNotice("Host manager revoked."))
                    .catch((error) => setNotice(failureMessage(error)));
              }}
            >
              Revoke manager
            </button>
          </details>
        )}
      </section>
    </div>
  );
}
