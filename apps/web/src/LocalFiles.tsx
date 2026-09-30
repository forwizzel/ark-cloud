import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  fetchLocalItems,
  fetchStorageRoots,
  localMutation,
  storageUrl,
  uploadLocalFile,
  type LocalItem,
  type LocalListing,
  type StorageRoot,
} from "./localStorageApi";
import "./local-files.css";

function message(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Local files are unavailable. Refresh and retry.";
}

function size(bytes: number | null) {
  if (bytes === null) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(
    Math.floor(Math.log(Math.max(bytes, 1)) / Math.log(1024)),
    4,
  );
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(bytes / 1024 ** index)} ${units[index]}`;
}

export function LocalStorageSummary() {
  const [state, setState] = useState<string>("Checking local storage…");
  useEffect(() => {
    const controller = new AbortController();
    fetchStorageRoots(controller.signal)
      .then(({ roots, message: note }) => {
        const ready = roots.filter((root) => root.state === "healthy").length;
        setState(
          roots.length
            ? `${ready} of ${roots.length} storage locations ready`
            : note,
        );
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setState(message(error));
      });
    return () => controller.abort();
  }, []);
  return (
    <section
      className="panel local-summary"
      aria-labelledby="local-summary-heading"
    >
      <div>
        <h2 id="local-summary-heading">Local storage</h2>
        <p>{state}</p>
      </div>
      <a href="#local-files">Open Local Files</a>
    </section>
  );
}

export default function LocalFiles({ csrfToken }: { csrfToken: string }) {
  const [roots, setRoots] = useState<StorageRoot[]>([]);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetchStorageRoots(controller.signal)
      .then((data) => {
        setRoots(data.roots);
        setSelected((current) =>
          data.roots.some((root) => root.id === current)
            ? current
            : (data.roots[0]?.id ?? ""),
        );
        setError(data.roots.length ? "" : data.message);
        setLoading(false);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setError(message(failure));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [refresh]);
  const root = roots.find((item) => item.id === selected);
  return (
    <div className="local-files">
      <div className="local-location-bar">
        <label>
          Storage location
          <select
            value={selected}
            disabled={busy || !roots.length}
            onChange={(event) => setSelected(event.target.value)}
          >
            {!roots.length && <option value="">No locations configured</option>}
            {roots.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
                {item.read_only ? " · Read only" : ""}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={() => setRefresh((value) => value + 1)}
        >
          Refresh locations
        </button>
      </div>
      {loading && <p role="status">Loading storage locations…</p>}
      {error && (
        <section className="panel local-empty" role="status">
          <h2>Local storage needs attention</h2>
          <p>{error}</p>
          {!roots.length && (
            <p>
              The host owner can configure a private folder with{" "}
              <code>./scripts/ark storage init</code>, then restart Ark Cloud.
            </p>
          )}
        </section>
      )}
      {root &&
        (root.state !== "healthy" ? (
          <section className="panel local-empty" role="alert">
            <h2>{root.label} is unavailable</h2>
            <p>{root.message}</p>
          </section>
        ) : (
          <FileBrowser
            key={root.id}
            root={root}
            csrfToken={csrfToken}
            onBusy={setBusy}
          />
        ))}
      <p className="local-scope">
        Files stay on your Ark host. Available space describes the location’s
        filesystem, shared with other host data; it is not a personal quota.
      </p>
    </div>
  );
}

type Action =
  { kind: "folders" } | { kind: "rename" | "move" | "delete"; item: LocalItem };

function FileBrowser({
  root,
  csrfToken,
  onBusy,
}: {
  root: StorageRoot;
  csrfToken: string;
  onBusy: (value: boolean) => void;
}) {
  const [path, setPath] = useState("");
  const [listing, setListing] = useState<LocalListing | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [action, setAction] = useState<Action | null>(null);
  const [value, setValue] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const cancelUpload = useRef<(() => void) | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const editorHeading = useRef<HTMLHeadingElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const focusAfterLoad = useRef(false);
  const restoreTrigger = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    if (action?.kind === "delete") editorHeading.current?.focus();
    if (!action && restoreTrigger.current) {
      restoreTrigger.current = false;
      if (trigger.current?.isConnected) trigger.current.focus();
      else heading.current?.focus();
    }
  }, [action]);
  useEffect(() => {
    if (!loading && focusAfterLoad.current) {
      focusAfterLoad.current = false;
      heading.current?.focus();
    }
  }, [loading, listing, error]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      cancelUpload.current?.();
      onBusy(false);
    };
  }, [onBusy]);
  useEffect(() => {
    const controller = new AbortController();
    fetchLocalItems(root.id, path, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setListing(data);
        setLoading(false);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setError(message(failure));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [root.id, path, refresh]);
  function reload(clearNotice = true) {
    if (clearNotice) setNotice("");
    focusAfterLoad.current = true;
    setLoading(true);
    setListing(null);
    setError("");
    setRefresh((current) => current + 1);
  }
  function navigate(next: string) {
    focusAfterLoad.current = true;
    setPath(next);
    setListing(null);
    setLoading(true);
    setAction(null);
    setError("");
    setNotice("");
  }
  function choose(next: Action) {
    trigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setAction(next);
    setValue(next.kind === "folders" ? "" : next.item.path);
    setError("");
    setNotice("");
  }
  function cancelEditor() {
    restoreTrigger.current = true;
    setAction(null);
  }
  function lock(value: boolean) {
    setBusy(value);
    onBusy(value);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!action) return;
    lock(true);
    setError("");
    setNotice("");
    try {
      await localMutation(
        root.id,
        action.kind === "rename" ? "move" : action.kind,
        csrfToken,
        action.kind === "folders"
          ? { path: [path, value].filter(Boolean).join("/") }
          : {
              path: action.item.path,
              revision: action.item.revision,
              destination:
                action.kind === "rename"
                  ? [path, value].filter(Boolean).join("/")
                  : value,
            },
      );
      setAction(null);
      setNotice(
        action.kind === "delete"
          ? "Item permanently deleted."
          : "Changes saved.",
      );
      reload(false);
    } catch (failure) {
      setError(message(failure));
    } finally {
      lock(false);
    }
  }
  async function upload(file: File) {
    lock(true);
    setError("");
    setNotice(`Uploading ${file.name}`);
    setProgress(0);
    const transfer = uploadLocalFile(
      root.id,
      [path, file.name].filter(Boolean).join("/"),
      file,
      csrfToken,
      setProgress,
    );
    cancelUpload.current = transfer.cancel;
    try {
      await transfer.done;
      if (mounted.current) {
        setNotice(`${file.name} uploaded.`);
        reload(false);
      }
    } catch (failure) {
      if (mounted.current) {
        setNotice("");
        setError(message(failure));
      }
    } finally {
      cancelUpload.current = null;
      if (mounted.current) {
        setProgress(null);
        lock(false);
      }
    }
  }
  async function more() {
    if (!listing) return;
    lock(true);
    setError("");
    try {
      const page = await fetchLocalItems(root.id, path, undefined, listing);
      if (mounted.current)
        setListing({ ...page, items: [...listing.items, ...page.items] });
    } catch (failure) {
      if (mounted.current) setError(message(failure));
    } finally {
      if (mounted.current) lock(false);
    }
  }
  return (
    <section className="panel local-browser" aria-label={`${root.label} files`}>
      <header className="local-browser-header">
        <div>
          <h2 ref={heading} tabIndex={-1}>
            {path.split("/").filter(Boolean).at(-1) ?? root.label}
          </h2>
          <p>
            {size(root.available_bytes)} available
            {root.read_only ? " · Read only" : ""}
          </p>
        </div>
        <div className="local-actions">
          <button
            disabled={busy || loading}
            onClick={() => reload()}
            type="button"
          >
            Refresh files
          </button>
          {!root.read_only && (
            <>
              <button
                disabled={busy}
                onClick={() => choose({ kind: "folders" })}
                type="button"
              >
                New folder
              </button>
              <button
                className="refresh-button"
                disabled={busy}
                onClick={() => input.current?.click()}
                type="button"
              >
                Upload file
              </button>
              <input
                ref={input}
                type="file"
                hidden
                aria-label="File to upload"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void upload(file);
                }}
              />
            </>
          )}
        </div>
      </header>
      <nav className="local-breadcrumbs" aria-label="File breadcrumbs">
        <button
          type="button"
          disabled={busy || !path}
          onClick={() => navigate("")}
        >
          {root.label}
        </button>
        {path
          .split("/")
          .filter(Boolean)
          .map((part, index, all) => (
            <span key={index}>
              <span aria-hidden="true"> / </span>
              <button
                type="button"
                disabled={busy || index === all.length - 1}
                onClick={() => navigate(all.slice(0, index + 1).join("/"))}
              >
                {part}
              </button>
            </span>
          ))}
      </nav>
      {notice && (
        <p className="local-feedback" role="status">
          {notice}
        </p>
      )}
      {progress !== null && (
        <div className="local-transfer">
          <progress max={100} value={progress} aria-label="Upload progress" />
          <span>{progress === 100 ? "Finalizing…" : `${progress}%`}</span>
          <button type="button" onClick={() => cancelUpload.current?.()}>
            Cancel upload
          </button>
        </div>
      )}
      {error && (
        <p className="local-error" role="alert">
          {error}
        </p>
      )}
      {action && (
        <form
          className="local-editor"
          aria-labelledby="file-action-heading"
          onSubmit={(event) => void submit(event)}
        >
          <h3 id="file-action-heading" ref={editorHeading} tabIndex={-1}>
            {action.kind === "folders"
              ? "Create folder"
              : action.kind === "delete"
                ? "Permanently delete this item?"
                : action.kind === "rename"
                  ? "Rename item"
                  : "Move within this location"}
          </h3>
          {action.kind !== "folders" && (
            <p className="local-filename">{action.item.name}</p>
          )}
          {action.kind === "delete" ? (
            <p>This cannot be undone. Folders must be empty.</p>
          ) : (
            <label>
              {action.kind === "move"
                ? "Destination path, relative to this storage location"
                : "Name"}
              <input
                autoFocus
                required
                maxLength={action.kind === "move" ? 2048 : 255}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                disabled={busy}
              />
            </label>
          )}
          <div className="local-actions">
            <button type="submit" disabled={busy}>
              {busy
                ? "Saving…"
                : action.kind === "delete"
                  ? "Delete permanently"
                  : "Save"}
            </button>
            <button type="button" disabled={busy} onClick={cancelEditor}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {loading ? (
        <p className="local-empty" role="status">
          Loading files…
        </p>
      ) : (
        listing && (
          <>
            {listing.items.length === 0 ? (
              <div className="local-empty">
                <h3>This folder is empty</h3>
                <p>
                  {root.read_only
                    ? "Files added on the host will appear after refreshing."
                    : "Upload a file or create a folder to get started."}
                </p>
              </div>
            ) : (
              <ul className="local-file-list" aria-label="Files and folders">
                {listing.items.map((item) => (
                  <li key={item.path}>
                    <div className="local-file-identity">
                      <span className="local-file-kind">
                        {item.kind === "folder" ? "Folder" : "File"}
                      </span>
                      {item.kind === "folder" ? (
                        <button
                          type="button"
                          className="local-name"
                          disabled={busy}
                          onClick={() => navigate(item.path)}
                        >
                          {item.name}
                        </button>
                      ) : (
                        <a
                          className="local-name"
                          href={storageUrl(root.id, "download", {
                            path: item.path,
                            revision: item.revision,
                          })}
                          download
                        >
                          {item.name}
                        </a>
                      )}
                      <span className="local-file-meta">
                        {item.kind === "file" && `${size(item.size_bytes)} · `}
                        <time dateTime={item.modified_at}>
                          {new Date(item.modified_at).toLocaleString()}
                        </time>
                      </span>
                    </div>
                    <div className="local-actions">
                      {item.kind === "file" && (
                        <a
                          href={storageUrl(root.id, "download", {
                            path: item.path,
                            revision: item.revision,
                          })}
                          download
                          aria-label={`Download ${item.name}`}
                        >
                          Download
                        </a>
                      )}
                      {!root.read_only && (
                        <>
                          <button
                            type="button"
                            disabled={busy}
                            aria-label={`Rename ${item.name}`}
                            onClick={() => {
                              choose({ kind: "rename", item });
                              setValue(item.name);
                            }}
                          >
                            Rename
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            aria-label={`Move ${item.name}`}
                            onClick={() => choose({ kind: "move", item })}
                          >
                            Move
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            aria-label={`Delete ${item.name}`}
                            onClick={() => choose({ kind: "delete", item })}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {listing.skipped_count > 0 && (
              <p className="local-feedback">
                {listing.skipped_count} unsupported or internal entries omitted
                (links, special files, or reserved names).
              </p>
            )}
            {listing.next_offset !== null && (
              <button
                className="local-more"
                type="button"
                disabled={busy}
                onClick={() => void more()}
              >
                Load more files
              </button>
            )}
          </>
        )
      )}
    </section>
  );
}
