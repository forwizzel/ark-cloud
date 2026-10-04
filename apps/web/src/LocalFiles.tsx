import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  fetchLocalItems,
  fetchStorageRoots,
  fetchStoragePreference,
  saveStoragePreference,
  provisionPrivateFolder,
  localMutation,
  storageUrl,
  uploadLocalFile,
  type LocalItem,
  type LocalListing,
  type StorageRoot,
  type StoragePreference,
} from "./localStorageApi";
import "./local-files.css";
import useUnsavedChanges from "./useUnsavedChanges";

type IconKind =
  | "file"
  | "folder"
  | "upload"
  | "new-folder"
  | "up"
  | "more"
  | "chevron"
  | "storage";

function FileIcon({
  kind,
  className = "",
}: {
  kind: IconKind;
  className?: string;
}) {
  const paths: Record<IconKind, string> = {
    file: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Zm0 0v6h6M8 13h8M8 17h5",
    folder:
      "M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
    upload: "M12 16V3m-5 5 5-5 5 5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4",
    "new-folder":
      "M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Zm9 5v6m-3-3h6",
    up: "M12 19V5m-6 6 6-6 6 6",
    more: "M5 12h.01M12 12h.01M19 12h.01",
    chevron: "m9 5 7 7-7 7",
    storage: "M4 4h16v16H4V4Zm0 10h16M7 17h.01M10 17h.01",
  };
  return (
    <svg
      className={`local-icon ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={kind === "more" ? 4 : 1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[kind]} />
    </svg>
  );
}

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
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(bytes / 1024 ** index)}\u00a0${units[index]}`;
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
        <p role="status">{state}</p>
      </div>
      <a href="#local-files">Open Local Files</a>
    </section>
  );
}

export default function LocalFiles({
  csrfToken,
  isAdmin = false,
}: {
  csrfToken: string;
  isAdmin?: boolean;
}) {
  const [roots, setRoots] = useState<StorageRoot[]>([]);
  const [selected, setSelected] = useState(() =>
    window.location.hash.startsWith("#local-files/")
      ? window.location.hash.slice("#local-files/".length)
      : "",
  );
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [preference, setPreference] = useState<StoragePreference | null>(null);
  const [preferenceNotice, setPreferenceNotice] = useState("");
  const workspace = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) return;
      workspace.current
        ?.querySelectorAll<HTMLDetailsElement>("details[open]")
        .forEach((menu) => {
          if (
            !menu.contains(event.target as Node) &&
            !menu.hasAttribute("data-keep-open")
          )
            menu.open = false;
        });
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const menus =
        workspace.current?.querySelectorAll<HTMLDetailsElement>(
          "details[open]",
        );
      const menu = Array.from(menus ?? []).find((item) =>
        item.contains(document.activeElement),
      );
      if (menu) {
        menu.open = false;
        menu.querySelector("summary")?.focus();
        event.preventDefault();
      }
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchStorageRoots(controller.signal, refresh > 0),
      fetchStoragePreference(controller.signal),
    ])
      .then(([data, saved]) => {
        if (controller.signal.aborted) return;
        setRoots(data.roots);
        setPreference(saved);
        if (
          saved.root_id &&
          !data.roots.some((root) => root.id === saved.root_id)
        )
          setPreferenceNotice(
            "Your default location is no longer available. Choose another location and set a new default.",
          );
        setSelected((current) =>
          data.roots.some((root) => root.id === current)
            ? current
            : data.roots.some((root) => root.id === saved.root_id)
              ? (saved.root_id ?? "")
              : "",
        );
        setError(data.roots.length ? "" : data.message);
        setLoading(false);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setError(message(failure));
          setRoots((current) =>
            current.map((item) => ({
              ...item,
              state: "unavailable",
              message:
                "Location status could not be verified. Refresh and retry.",
            })),
          );
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [refresh]);
  const root = roots.find((item) => item.id === selected);
  async function setDefault(path: string) {
    setBusy(true);
    try {
      const saved = await saveStoragePreference(
        selected || null,
        path,
        csrfToken,
      );
      setPreference(saved);
      setPreferenceNotice("Default starting folder saved.");
    } catch (failure) {
      setPreferenceNotice(message(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="panel local-files" ref={workspace}>
      <div className="local-location-bar">
        <label>
          Storage location
          <select
            name="storage-location"
            data-discard-changes
            data-current-value={selected}
            autoComplete="off"
            value={selected}
            disabled={busy || !roots.length}
            onChange={(event) => {
              const url = new URL(window.location.href);
              url.searchParams.delete("files-path");
              url.searchParams.delete("files-root");
              url.hash = event.target.value
                ? `#local-files/${event.target.value}`
                : "#local-files";
              window.history.replaceState(
                window.history.state,
                "",
                `${url.pathname}${url.search}${url.hash}`,
              );
              setSelected(event.target.value);
            }}
          >
            <option value="">
              {roots.length ? "Choose a location" : "No locations configured"}
            </option>
            {roots.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
                {item.read_only ? " · Read only" : ""}
                {item.state !== "healthy" ? " · Unavailable" : ""}
                {preference?.root_id === item.id ? " · Default" : ""}
              </option>
            ))}
          </select>
        </label>
        <details
          className="local-location-options"
          open={Boolean(error || root?.state === "unavailable")}
          data-keep-open={
            error || root?.state === "unavailable" ? "" : undefined
          }
          aria-label="Location options"
        >
          <summary>
            Location options
            <FileIcon kind="more" />
          </summary>
          <div className="local-actions">
            <button
              type="button"
              disabled={busy || loading}
              onClick={() => {
                setLoading(true);
                setRefresh((value) => value + 1);
              }}
            >
              Refresh locations
            </button>
            {isAdmin && <a href="#administration">Manage storage</a>}
            {preference?.root_id && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void saveStoragePreference(null, "", csrfToken)
                    .then((saved) => {
                      setPreference(saved);
                      setPreferenceNotice(
                        "Default cleared. Choose a starting location next time you open Local Files.",
                      );
                    })
                    .catch((failure) => setPreferenceNotice(message(failure)))
                    .finally(() => setBusy(false));
                }}
              >
                Clear default
              </button>
            )}
          </div>
        </details>
      </div>
      {preferenceNotice && <p role="status">{preferenceNotice}</p>}
      {!loading && roots.length > 0 && !selected && (
        <section className="local-empty local-empty--location">
          <FileIcon kind="storage" className="local-empty-icon" />
          <h2>Choose your starting location</h2>
          <p>
            Select a location above. You can make any available folder your
            default; Ark Cloud will open it the next time you visit.
          </p>
        </section>
      )}
      {loading && (
        <p className="local-loading" role="status">
          Loading storage locations…
        </p>
      )}
      {error && (
        <section className="local-empty local-empty--location" role="status">
          <FileIcon kind="storage" className="local-empty-icon" />
          <h2>Local storage needs attention</h2>
          <p>{error}</p>
          {!roots.length && (
            <p>
              {isAdmin ? (
                <a href="#administration">Set up storage</a>
              ) : (
                "Ask your administrator to connect a folder for your account."
              )}
            </p>
          )}
        </section>
      )}
      {root &&
        (root.state !== "healthy" ? (
          <section className="local-empty local-empty--location" role="alert">
            <FileIcon kind="storage" className="local-empty-icon" />
            <h2>{root.label} is unavailable</h2>
            <p>{root.message}</p>
            {root.kind === "managed" && root.needs_setup && (
              <button
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void provisionPrivateFolder(csrfToken)
                    .then(() => setRefresh((value) => value + 1))
                    .catch((failure) => setPreferenceNotice(message(failure)))
                    .finally(() => setBusy(false));
                }}
              >
                Create my private folder
              </button>
            )}
            {isAdmin && (
              <a href="#administration">Review storage diagnostics</a>
            )}
          </section>
        ) : (
          <FileBrowser
            key={root.id}
            root={root}
            csrfToken={csrfToken}
            onBusy={setBusy}
            initialPath={
              window.location.hash === `#local-files/${root.id}` &&
              (!new URLSearchParams(window.location.search).has("files-root") ||
                new URLSearchParams(window.location.search).get(
                  "files-root",
                ) === root.id)
                ? (new URLSearchParams(window.location.search).get(
                    "files-path",
                  ) ?? (preference?.root_id === root.id ? preference.path : ""))
                : preference?.root_id === root.id
                  ? preference.path
                  : ""
            }
            preference={preference}
            onDefault={(path) => void setDefault(path)}
          />
        ))}
      <p className="local-scope">
        Files stay on your server. Available space describes the location’s
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
  initialPath,
  preference,
  onDefault,
}: {
  root: StorageRoot;
  csrfToken: string;
  onBusy: (value: boolean) => void;
  initialPath: string;
  preference: StoragePreference | null;
  onDefault: (path: string) => void;
}) {
  const [path, setPath] = useState(initialPath);
  const [listing, setListing] = useState<LocalListing | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [action, setAction] = useState<Action | null>(null);
  const [value, setValue] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [deleteReview, setDeleteReview] = useState(false);
  const [refreshedDelete, setRefreshedDelete] = useState(false);
  const [revisionPending, setRevisionPending] = useState(false);
  const reconcileAction = useRef<Action | null>(null);
  const firstAddedPath = useRef<string | null>(null);
  const fileList = useRef<HTMLUListElement>(null);
  const cancelUpload = useRef<(() => void) | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const editorHeading = useRef<HTMLHeadingElement>(null);
  const editorInput = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const focusAfterLoad = useRef(false);
  const restoreTrigger = useRef(false);
  const mounted = useRef(true);
  const parts = path.split("/").filter(Boolean);
  useEffect(() => {
    const url = new URL(window.location.href);
    url.hash = `#local-files/${root.id}`;
    url.searchParams.set("files-path", path);
    url.searchParams.set("files-root", root.id);
    window.history.replaceState(
      window.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  }, [root.id, path]);
  const initialValue =
    action?.kind === "rename"
      ? action.item.name
      : action && action.kind !== "folders"
        ? action.item.path
        : "";
  const discardChanges = useUnsavedChanges(
    progress !== null ||
      Boolean(action && action.kind !== "delete" && value !== initialValue),
    progress !== null
      ? "Leaving this page cancels the active upload. Leave and cancel upload?"
      : undefined,
  );
  useEffect(() => {
    if (!firstAddedPath.current) return;
    const row = Array.from(
      fileList.current?.querySelectorAll<HTMLElement>("[data-file-path]") ?? [],
    ).find((element) => element.dataset.filePath === firstAddedPath.current);
    row?.querySelector<HTMLElement>(".local-name")?.focus();
    firstAddedPath.current = null;
  }, [listing]);
  useEffect(() => {
    if (action) editorHeading.current?.focus();
    if (!action && restoreTrigger.current) {
      restoreTrigger.current = false;
      if (trigger.current?.isConnected) trigger.current.focus();
      else heading.current?.focus();
    }
  }, [action]);
  useEffect(() => {
    if (!loading && focusAfterLoad.current) {
      focusAfterLoad.current = false;
      if (action) editorHeading.current?.focus();
      else heading.current?.focus();
    }
  }, [loading, listing, error, action]);
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
      .then(async (data) => {
        if (controller.signal.aborted) return;
        const pending = reconcileAction.current;
        if (pending && pending.kind !== "folders") {
          // The edited item may be on a later page of this folder.
          while (
            reconcileAction.current === pending &&
            !data.items.some((item) => item.path === pending.item.path) &&
            data.next_offset !== null
          ) {
            const page = await fetchLocalItems(
              root.id,
              path,
              controller.signal,
              data,
            );
            if (controller.signal.aborted) return;
            data = { ...page, items: [...data.items, ...page.items] };
          }
          if (reconcileAction.current === pending) {
            const fresh = data.items.find(
              (item) =>
                item.path === pending.item.path &&
                item.kind === pending.item.kind,
            );
            reconcileAction.current = null;
            setRevisionPending(false);
            if (fresh) {
              setAction({ ...pending, item: fresh });
              setDeleteReview(pending.kind === "delete");
              setRefreshedDelete(pending.kind === "delete");
              setNotice(
                pending.kind === "delete"
                  ? "Item refreshed. Review it again before deleting."
                  : "Item refreshed. Your draft has been preserved.",
              );
            } else {
              setAction(null);
              setNotice(
                "This item is no longer in this folder. Your action was closed; choose an item from the refreshed list.",
              );
            }
          }
        }
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
  function reload(clearNotice = true, reconcile = true) {
    reconcileAction.current = reconcile ? action : null;
    setRevisionPending(
      Boolean(reconcile && action && action.kind !== "folders"),
    );
    if (clearNotice) setNotice("");
    focusAfterLoad.current = true;
    setLoading(true);
    setListing(null);
    setError("");
    setRefresh((current) => current + 1);
  }
  function navigate(next: string) {
    if (!discardChanges()) return;
    reconcileAction.current = null;
    setRevisionPending(false);
    focusAfterLoad.current = true;
    setPath(next);
    setListing(null);
    setLoading(true);
    setAction(null);
    setError("");
    setNotice("");
  }
  function choose(next: Action) {
    if (!discardChanges()) return;
    reconcileAction.current = null;
    trigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const menu = trigger.current?.closest("details");
    if (menu) {
      trigger.current = menu.querySelector("summary");
      menu.open = false;
    }
    setAction(next);
    setDeleteReview(false);
    setRefreshedDelete(false);
    setRevisionPending(false);
    setValue(
      next.kind === "folders"
        ? ""
        : next.kind === "rename"
          ? next.item.name
          : next.item.path,
    );
    setError("");
    setNotice("");
  }
  function cancelEditor() {
    if (!discardChanges()) return;
    reconcileAction.current = null;
    setRevisionPending(false);
    restoreTrigger.current = true;
    setAction(null);
  }
  function lock(value: boolean) {
    setBusy(value);
    onBusy(value);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!action || loading || deleteReview || revisionPending) return;
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
      reload(false, false);
    } catch (failure) {
      setError(message(failure));
      if (action.kind !== "delete") editorInput.current?.focus();
    } finally {
      lock(false);
    }
  }
  async function upload(file: File) {
    if (preference && file.size > preference.upload_max_bytes) {
      setError(
        `This file exceeds the ${size(preference.upload_max_bytes)} upload limit.`,
      );
      return;
    }
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
      if (mounted.current) {
        firstAddedPath.current = page.items[0]?.path ?? null;
        setListing({ ...page, items: [...listing.items, ...page.items] });
        setNotice(
          `${page.items.length} more ${page.items.length === 1 ? "item" : "items"} loaded. ${listing.items.length + page.items.length} items shown.${page.next_offset === null ? " All files loaded." : ""}`,
        );
        if (!page.items.length && page.next_offset === null)
          heading.current?.focus();
      }
    } catch (failure) {
      if (mounted.current) setError(message(failure));
    } finally {
      if (mounted.current) lock(false);
    }
  }
  return (
    <section className="local-browser" aria-label={`${root.label} files`}>
      <div className="local-path-bar">
        <button
          className="local-up"
          type="button"
          aria-label="Up one folder"
          title="Up one folder"
          disabled={busy || !path}
          onClick={() => navigate(parts.slice(0, -1).join("/"))}
        >
          <FileIcon kind="up" />
        </button>
        <nav
          className="local-breadcrumbs"
          aria-label="File breadcrumbs"
          translate="no"
        >
          <ol>
            <li>
              {path ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => navigate("")}
                >
                  {root.label}
                </button>
              ) : (
                <span aria-current="page">{root.label}</span>
              )}
            </li>
            {parts.map((part, index) => (
              <li key={index}>
                <FileIcon kind="chevron" />
                {index === parts.length - 1 ? (
                  <span aria-current="page">{part}</span>
                ) : (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      navigate(parts.slice(0, index + 1).join("/"))
                    }
                  >
                    {part}
                  </button>
                )}
              </li>
            ))}
          </ol>
        </nav>
      </div>
      <header className="local-browser-header">
        <div className="local-folder-heading">
          <h2 ref={heading} tabIndex={-1} translate="no">
            {parts.at(-1) ?? root.label}
          </h2>
          <p>
            {!loading && listing && (
              <span>
                {listing.items.length}{" "}
                {listing.items.length === 1 ? "item" : "items"} shown ·{" "}
              </span>
            )}
            <span>
              {root.available_bytes === null
                ? "Available space not reported"
                : `${size(root.available_bytes)} available`}
            </span>
          </p>
          {(root.read_only ||
            (preference?.root_id === root.id && preference.path === path)) && (
            <div className="local-folder-badges">
              {root.read_only && <span>Read only</span>}
              {preference?.root_id === root.id && preference.path === path && (
                <span>Starting folder</span>
              )}
            </div>
          )}
        </div>
        <div className="local-actions">
          {!root.read_only && (
            <>
              <button
                className="refresh-button"
                disabled={busy || loading}
                onClick={() => input.current?.click()}
                type="button"
              >
                <FileIcon kind="upload" />
                Upload file
              </button>
              <button
                disabled={busy || loading}
                onClick={() => choose({ kind: "folders" })}
                type="button"
              >
                <FileIcon kind="new-folder" />
                New folder
              </button>
            </>
          )}
          <details className="local-secondary-options">
            <summary aria-label="Folder options" title="Folder options">
              <FileIcon kind="more" />
              <span className="local-sr-only">Folder options</span>
            </summary>
            <div className="local-actions">
              <button
                type="button"
                disabled={
                  busy ||
                  loading ||
                  (preference?.root_id === root.id && preference.path === path)
                }
                onClick={() => onDefault(path)}
              >
                {preference?.root_id === root.id && preference.path === path
                  ? "Default starting folder"
                  : "Set as starting folder"}
              </button>
              <button
                disabled={busy || loading}
                onClick={() => reload()}
                type="button"
              >
                Refresh files
              </button>
              {!root.read_only && preference && (
                <p>Maximum file size: {size(preference.upload_max_bytes)}</p>
              )}
            </div>
          </details>
          {!root.read_only && (
            <>
              <input
                ref={input}
                name="upload-file"
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
      {notice && progress === null && (
        <p className="local-feedback" role="status">
          {notice}
        </p>
      )}
      {progress !== null && (
        <div className="local-transfer">
          <FileIcon kind="upload" />
          <span className="local-transfer-name" role="status">
            {notice}
          </span>
          <progress max={100} value={progress} aria-label="Upload progress" />
          <span>{progress === 100 ? "Finalizing…" : `${progress}%`}</span>
          <button type="button" onClick={() => cancelUpload.current?.()}>
            Cancel upload
          </button>
        </div>
      )}
      {error && !action && (
        <div>
          <p className="local-error" role="alert" id="file-action-error">
            {error}
          </p>
          {path && !listing && (
            <button type="button" onClick={() => navigate("")}>
              Return to location root
            </button>
          )}
        </div>
      )}
      {action && (
        <form
          className={`local-editor${action.kind === "delete" ? " local-editor--delete" : ""}`}
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
            <>
              <p className="local-filename" translate="no">
                {action.item.path}
              </p>
              <p className="local-feedback">
                {action.item.kind === "file"
                  ? `${size(action.item.size_bytes)} · `
                  : "Folder · "}
                Modified {new Date(action.item.modified_at).toLocaleString()}
              </p>
            </>
          )}
          {error && (
            <div>
              <p className="local-error" role="alert" id="file-action-error">
                {error}
              </p>
              <button
                type="button"
                disabled={busy || loading}
                onClick={() => reload()}
              >
                Refresh files
              </button>
            </div>
          )}
          {action.kind === "delete" ? (
            <>
              <p>This cannot be undone. Folders must be empty.</p>
              {refreshedDelete && (
                <label className="local-delete-review">
                  <input
                    type="checkbox"
                    name="review-refreshed-item"
                    checked={!deleteReview}
                    onChange={(event) => setDeleteReview(!event.target.checked)}
                  />
                  I reviewed the refreshed item and still want to delete it.
                </label>
              )}
            </>
          ) : (
            <>
              <label>
                {action.kind === "move"
                  ? "Destination path, relative to this storage location"
                  : "Name"}
                <input
                  ref={editorInput}
                  name={
                    action.kind === "move" ? "destination-path" : "item-name"
                  }
                  aria-invalid={Boolean(error)}
                  aria-describedby={
                    [
                      error ? "file-action-error" : "",
                      action.kind === "move" ? "file-move-help" : "",
                    ]
                      .filter(Boolean)
                      .join(" ") || undefined
                  }
                  autoComplete="off"
                  spellCheck={false}
                  autoCapitalize="none"
                  required
                  maxLength={action.kind === "move" ? 2048 : 255}
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  disabled={busy}
                />
              </label>
              {action.kind === "move" && (
                <p id="file-move-help" className="local-feedback">
                  Include the destination folder and item name, for example
                  Reports/notes.txt. Use a path within {root.label}, without a
                  leading /. The destination folder must already exist.
                </p>
              )}
            </>
          )}
          <div className="local-actions">
            <button
              className={
                action.kind === "delete"
                  ? "local-danger-button"
                  : "refresh-button"
              }
              type="submit"
              disabled={busy || loading || deleteReview || revisionPending}
              aria-busy={busy}
            >
              {busy
                ? "Saving…"
                : action.kind === "delete"
                  ? "Delete permanently"
                  : action.kind === "folders"
                    ? "Create folder"
                    : action.kind === "rename"
                      ? "Rename item"
                      : "Move item"}
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
                <FileIcon kind="folder" className="local-empty-icon" />
                <h3>This folder is empty</h3>
                <p>
                  {root.read_only
                    ? "Files added on the host will appear after refreshing."
                    : "Upload a file or create a folder to get started."}
                </p>
              </div>
            ) : (
              <>
                <div className="local-list-columns" aria-hidden="true">
                  <span>Name</span>
                  <span>Size</span>
                  <span>Modified</span>
                  <span />
                </div>
                <ul
                  ref={fileList}
                  className="local-file-list"
                  aria-label="Files and folders"
                >
                  {listing.items.map((item) => (
                    <li
                      key={item.path}
                      data-file-path={item.path}
                      className="local-file-row"
                    >
                      <div className="local-file-identity">
                        <FileIcon
                          kind={item.kind}
                          className="local-item-icon"
                        />
                        <div className="local-file-name-group">
                          {item.kind === "folder" ? (
                            <button
                              type="button"
                              className="local-name"
                              translate="no"
                              disabled={busy}
                              onClick={() => navigate(item.path)}
                            >
                              {item.name}
                            </button>
                          ) : (
                            <a
                              className="local-name"
                              translate="no"
                              href={storageUrl(root.id, "download", {
                                path: item.path,
                                revision: item.revision,
                              })}
                              download
                            >
                              {item.name}
                            </a>
                          )}
                          <span className="local-sr-only local-file-kind">
                            {item.kind === "folder" ? "Folder" : "File"}
                          </span>
                        </div>
                      </div>
                      <span className="local-file-meta">
                        <span className="local-file-size">
                          <span className="local-sr-only">Size: </span>
                          {item.kind === "file" ? size(item.size_bytes) : "—"}
                        </span>
                        <time
                          className="local-file-date"
                          dateTime={item.modified_at}
                          title={new Date(item.modified_at).toLocaleString()}
                          aria-label={`Modified ${new Date(item.modified_at).toLocaleString()}`}
                        >
                          {new Date(item.modified_at).toLocaleDateString(
                            undefined,
                            { year: "numeric", month: "short", day: "numeric" },
                          )}
                        </time>
                      </span>
                      {(!root.read_only || item.kind === "file") && (
                        <details
                          className="local-item-actions"
                          name={`file-actions-${root.id}`}
                        >
                          <summary
                            aria-label={`Actions for ${item.name}`}
                            title={`Actions for ${item.name}`}
                          >
                            <FileIcon kind="more" />
                            <span className="local-sr-only">Actions</span>
                          </summary>
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
                                  onClick={() =>
                                    choose({ kind: "rename", item })
                                  }
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
                                  className="local-danger-action"
                                  onClick={() =>
                                    choose({ kind: "delete", item })
                                  }
                                >
                                  Delete
                                </button>
                              </>
                            )}
                          </div>
                        </details>
                      )}
                    </li>
                  ))}
                </ul>
              </>
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
