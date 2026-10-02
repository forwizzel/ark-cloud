import { useState } from "react";
import {
  storageRequest,
  submitStorageOperation,
  type AccessLevel,
  type StorageAdministration,
  type StorageJob,
  type StorageOperation,
} from "./storageAdminApi";

export default function StorageConnection({
  data,
  csrfToken,
  onQueued,
}: {
  data: StorageAdministration;
  csrfToken: string;
  onQueued: (job: StorageJob) => void;
}) {
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [kind, setKind] = useState<"shared" | "managed">("shared");
  const [label, setLabel] = useState("");
  const [path, setPath] = useState("");
  const [grants, setGrants] = useState(
    data.users
      .filter((user) => user.active)
      .map((user) => ({
        user_id: user.id,
        level: user.current
          ? ("write" as AccessLevel)
          : ("none" as AccessLevel),
      })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [folders, setFolders] = useState<string[]>(data.manager.approved_paths);
  const area = data.manager.managed_area;
  const newPath = area
    ? `${area}/${
        label
          .trim()
          .toLowerCase()
          .replace(/[^a-z0-9-]+/g, "-")
          .replace(/^-|-$/g, "") || "files"
      }`
    : "";
  const working = data.jobs.some((job) =>
    ["queued", "applying", "verifying"].includes(job.state),
  );
  async function browse(value: string) {
    setBusy(true);
    setError("");
    try {
      const job = await submitStorageOperation(
        { action: "browse", path: value },
        csrfToken,
      );
      let current = job;
      for (
        let i = 0;
        i < 30 && ["queued", "applying", "verifying"].includes(current.state);
        i++
      ) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        const next = await storageRequest<StorageAdministration>(
          "admin/storage",
          csrfToken,
        );
        current = next.jobs.find((item) => item.id === job.id) ?? current;
      }
      if (current.state !== "completed") throw new Error(current.message);
      setFolders(current.result.folders ?? []);
      setPath(current.result.path ?? value);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Server folders are unavailable.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function connect(event: React.FormEvent) {
    event.preventDefault();
    if (!grants.some((grant) => grant.level !== "none")) {
      setError("Choose at least one account with access.");
      return;
    }
    setBusy(true);
    setError("");
    const operation: StorageOperation = {
      action: kind === "managed" ? "init" : "add",
      label: label.trim(),
      path: mode === "new" ? newPath : path,
      managed: kind === "managed",
      shared: kind === "shared",
      create_directory: mode === "new" && kind === "shared",
      grants,
      confirmed: true,
      automatic_access: true,
    };
    try {
      onQueued(await submitStorageOperation(operation, csrfToken));
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The location could not be connected.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="panel storage-section"
      aria-labelledby="connect-heading"
    >
      <h2 id="connect-heading">Add location</h2>
      <p>
        Choose the folder and its accounts. Ark prepares filesystem access and
        verifies the connection automatically.
      </p>
      {error && (
        <p className="local-error" role="alert">
          {error}
        </p>
      )}
      {!data.manager.online && (
        <p role="status">
          Host storage management is unavailable. Deployment status is available
          in Diagnostics.
        </p>
      )}
      <form onSubmit={(event) => void connect(event)}>
        <fieldset
          disabled={
            busy ||
            working ||
            !data.manager.online ||
            Boolean(data.configuration_error)
          }
        >
          <div className="storage-form-grid">
            <label>
              Location name
              <input
                required
                maxLength={80}
                value={label}
                onChange={(event) => setLabel(event.target.value)}
              />
            </label>
            <label>
              Folder
              <select
                value={mode}
                onChange={(event) => {
                  setMode(event.target.value as "new" | "existing");
                  if (event.target.value === "existing") setKind("shared");
                }}
              >
                <option value="new">Create a new folder</option>
                <option value="existing">Use an existing folder</option>
              </select>
            </label>
            <label>
              Purpose
              <select
                value={kind}
                onChange={(event) =>
                  setKind(event.target.value as "shared" | "managed")
                }
              >
                <option value="shared">Shared files</option>
                <option
                  value="managed"
                  disabled={
                    data.roots.some((root) => root.kind === "managed") ||
                    mode === "existing"
                  }
                >
                  Private account folders
                </option>
              </select>
            </label>
          </div>
          {mode === "new" ? (
            <p className="storage-path">
              {area
                ? `Server folder: ${newPath}`
                : "The deployment has not provisioned its managed storage area. Check Diagnostics."}
            </p>
          ) : (
            <>
              <label>
                Existing server folder
                <input
                  required
                  value={path}
                  onChange={(event) => setPath(event.target.value)}
                />
              </label>
              <div className="local-actions">
                <button type="button" onClick={() => void browse("")}>
                  Approved areas
                </button>
                <button
                  type="button"
                  disabled={!path}
                  onClick={() => void browse(path)}
                >
                  Browse folder
                </button>
              </div>
              <ul className="storage-folder-options">
                {folders.map((folder) => (
                  <li key={folder}>
                    <button
                      type="button"
                      onClick={() => {
                        setPath(folder);
                      }}
                    >
                      {folder}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          <fieldset className="storage-initial-access">
            <legend>Account permissions</legend>
            <p>
              {kind === "managed"
                ? "Each enabled account gets its own isolated folder."
                : "Enabled accounts see the same files in this directory."}
            </p>
            {data.users
              .filter((user) => user.active)
              .map((user) => (
                <label key={user.id}>
                  Access for {user.username}
                  <select
                    value={
                      grants.find((grant) => grant.user_id === user.id)
                        ?.level ?? "none"
                    }
                    onChange={(event) =>
                      setGrants((current) =>
                        current.map((grant) =>
                          grant.user_id === user.id
                            ? {
                                ...grant,
                                level: event.target.value as AccessLevel,
                              }
                            : grant,
                        ),
                      )
                    }
                  >
                    <option value="none">No access</option>
                    <option value="read">Read-only</option>
                    <option value="write">Read &amp; write</option>
                  </select>
                </label>
              ))}
          </fieldset>
          <p className="storage-help">
            Connecting prepares narrow API access for this directory and
            eligible content. Existing file labels are preserved. Applying
            mounts briefly reconnects the API.
          </p>
          <div className="local-actions">
            <button
              className="refresh-button"
              type="submit"
              disabled={mode === "new" && !area}
            >
              {busy ? "Connecting…" : "Connect"}
            </button>
            <a href="#administration/storage">Cancel</a>
          </div>
        </fieldset>
      </form>
    </section>
  );
}
