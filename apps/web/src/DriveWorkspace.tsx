import { FormEvent, useEffect, useEffectEvent, useRef, useState } from "react";

import {
  createPinnedLocation,
  createSavedSearch,
  deletePinnedLocation,
  deleteSavedSearch,
  fetchDriveActivity,
  fetchDriveCatalogStatus,
  fetchDriveFolder,
  fetchDriveInsights,
  fetchPinnedLocations,
  fetchSavedSearches,
  fetchSyncHistory,
  searchCatalog,
  syncDriveCatalog,
  type DriveActivityEvent,
  type DriveCatalogStatus,
  type DriveDirection,
  type DriveFolder,
  type DriveInsights,
  type DriveKind,
  type DriveSort,
  type DriveView,
  type PinnedLocation,
  type SavedSearch,
  type SavedSearchFilters,
  type SearchResult,
  type SyncAttempt,
} from "./api";

type DriveWorkspaceProps = {
  connected: boolean;
  csrfToken: string;
};

type ResultState =
  | { phase: "loading" }
  | { phase: "ready"; items: SearchResult[]; nextCursor: string | null }
  | { phase: "error"; message: string };

const rootFolder: DriveFolder = {
  id: "root",
  name: "My Drive",
  web_url: "https://drive.google.com/drive/my-drive",
  modified_at: null,
  starred: false,
  breadcrumbs: [{ id: "root", name: "My Drive", available: true }],
  breadcrumbs_complete: true,
};

const rootFilters: SavedSearchFilters = {
  q: null,
  view: "all",
  kind: "all",
  parent_id: "root",
  modified_after: null,
  modified_before: null,
  min_size: null,
  max_size: null,
  starred: null,
  ownership: "owned_by_me",
  sort: "modified",
  direction: "desc",
};

const kindLabels: Record<DriveKind, string> = {
  folder: "Folder",
  document: "Document",
  image: "Image",
  video: "Video",
  audio: "Audio",
  archive: "Archive",
  other: "Other",
};

export default function DriveWorkspace({
  connected,
  csrfToken,
}: DriveWorkspaceProps) {
  const [status, setStatus] = useState<DriveCatalogStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [filters, setFilters] = useState<SavedSearchFilters>(rootFilters);
  const [draft, setDraft] = useState<SavedSearchFilters>(rootFilters);
  const [folder, setFolder] = useState<DriveFolder>(rootFolder);
  const [folderError, setFolderError] = useState<string | null>(null);
  const [results, setResults] = useState<ResultState>(
    connected
      ? { phase: "loading" }
      : {
          phase: "error",
          message: "Connect Google Drive before browsing catalog metadata.",
        },
  );
  const [pageError, setPageError] = useState<string | null>(null);
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [pins, setPins] = useState<PinnedLocation[]>([]);
  const [insights, setInsights] = useState<DriveInsights | null>(null);
  const [history, setHistory] = useState<SyncAttempt[]>([]);
  const [activity, setActivity] = useState<DriveActivityEvent[]>([]);
  const [activityCursor, setActivityCursor] = useState<string | null>(null);
  const [activityMessage, setActivityMessage] = useState(
    "Activity reflects metadata observed during synchronization, not a full audit log.",
  );
  const [sideError, setSideError] = useState<string | null>(null);
  const [saveName, setSaveName] = useState("");
  const [showSaveForm, setShowSaveForm] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [loadingActivity, setLoadingActivity] = useState(false);
  const requestNumber = useRef(0);
  const navigationRequest = useRef(0);
  const latestFilters = useRef<SavedSearchFilters>(rootFilters);
  const syncInFlight = useRef(false);
  const pollSequence = useRef(0);
  const completedSyncKey = useRef<string | null>(null);

  const updateStatus = (next: DriveCatalogStatus) => {
    setStatus((current) =>
      shouldAcceptCatalogStatus(current, next) ? next : current,
    );
  };

  const commitFilters = (next: SavedSearchFilters) => {
    latestFilters.current = next;
    setFilters(next);
    setDraft(next);
  };

  useEffect(() => {
    const controller = new AbortController();
    fetchDriveCatalogStatus(controller.signal)
      .then((value) => {
        updateStatus(value);
        setStatusError(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setStatusError(errorMessage(error));
      });

    if (!connected) {
      return () => controller.abort();
    }

    const request = ++requestNumber.current;
    searchCatalog({ ...rootFilters, limit: 20 }, controller.signal)
      .then((response) => {
        if (request !== requestNumber.current) return;
        updateStatus(response.catalog);
        setResults({
          phase: "ready",
          items: response.items,
          nextCursor: response.next_cursor,
        });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && request === requestNumber.current) {
          setResults({ phase: "error", message: errorMessage(error) });
        }
      });

    void Promise.allSettled([
      fetchSavedSearches().then(setSavedSearches),
      fetchPinnedLocations().then(setPins),
      fetchDriveInsights().then(setInsights),
      fetchSyncHistory().then(setHistory),
      fetchDriveActivity().then((response) => {
        setActivity(response.items);
        setActivityCursor(response.next_cursor);
        setActivityMessage(response.message);
      }),
    ]).then((settled) => {
      if (settled.some((value) => value.status === "rejected")) {
        setSideError(
          "Some workspace records could not be loaded. Reload the workspace to retry.",
        );
      }
    });

    return () => controller.abort();
  }, [connected]);

  const loadResults = async (
    nextFilters: SavedSearchFilters,
    cursor?: string,
  ) => {
    const request = ++requestNumber.current;
    if (!cursor) {
      setResults({ phase: "loading" });
      setPageError(null);
    }
    try {
      const response = await searchCatalog({
        ...nextFilters,
        ...(cursor ? { cursor } : {}),
        limit: 20,
      });
      if (request !== requestNumber.current) return;
      updateStatus(response.catalog);
      setResults((current) => ({
        phase: "ready",
        items:
          cursor && current.phase === "ready"
            ? [...current.items, ...response.items]
            : response.items,
        nextCursor: response.next_cursor,
      }));
    } catch (error: unknown) {
      if (request !== requestNumber.current) return;
      if (cursor) {
        setPageError(
          `${errorMessage(error)} The catalog or filters may have changed; restart this listing.`,
        );
      } else {
        setResults({ phase: "error", message: errorMessage(error) });
      }
    }
  };

  const refreshControlPlane = async () => {
    const settled = await Promise.allSettled([
      fetchPinnedLocations().then(setPins),
      fetchDriveInsights().then(setInsights),
      fetchSyncHistory().then(setHistory),
      fetchDriveActivity().then((response) => {
        setActivity(response.items);
        setActivityCursor(response.next_cursor);
        setActivityMessage(response.message);
      }),
    ]);
    if (settled.some((value) => value.status === "rejected")) {
      setSideError(
        "Sync finished, but some advisory records could not be refreshed.",
      );
    }
  };

  const reconcileCurrentFolder = async () => {
    const current = latestFilters.current;
    const folderId = current.view === "all" ? current.parent_id : null;
    if (!folderId || folderId === "root") {
      setFolder(rootFolder);
      return;
    }

    const navigation = navigationRequest.current;
    try {
      const nextFolder = await fetchDriveFolder(folderId);
      if (
        navigation !== navigationRequest.current ||
        latestFilters.current.view !== "all" ||
        latestFilters.current.parent_id !== folderId
      ) {
        return;
      }
      setFolder(nextFolder);
      setFolderError(null);
    } catch {
      if (
        navigation !== navigationRequest.current ||
        latestFilters.current.view !== "all" ||
        latestFilters.current.parent_id !== folderId
      ) {
        return;
      }
      navigationRequest.current += 1;
      const recovered = {
        ...latestFilters.current,
        view: "all" as const,
        parent_id: "root",
      };
      commitFilters(recovered);
      setFolder(rootFolder);
      setFolderError(
        "This folder is no longer available in the catalog. Returned to My Drive.",
      );
    }
  };

  const refreshAfterSync = async (nextStatus: DriveCatalogStatus) => {
    const key = `${nextStatus.revision}:${nextStatus.last_started_at ?? "none"}`;
    if (completedSyncKey.current === key) return;
    completedSyncKey.current = key;
    await Promise.all([refreshControlPlane(), reconcileCurrentFolder()]);
    await loadResults(latestFilters.current);
  };

  const finishPolledSync = useEffectEvent((nextStatus: DriveCatalogStatus) => {
    void refreshAfterSync(nextStatus);
  });

  useEffect(() => {
    if (status?.state !== "syncing") return;
    const sequence = ++pollSequence.current;
    let timer: number | undefined;
    let controller: AbortController | null = null;
    let stopped = false;

    const poll = async () => {
      controller = new AbortController();
      try {
        const value = await fetchDriveCatalogStatus(controller.signal);
        if (stopped || sequence !== pollSequence.current) return;
        updateStatus(value);
        if (value.state === "syncing") {
          timer = window.setTimeout(() => void poll(), 2_000);
        } else {
          finishPolledSync(value);
        }
      } catch {
        if (!stopped && sequence === pollSequence.current) {
          timer = window.setTimeout(() => void poll(), 2_000);
        }
      }
    };

    timer = window.setTimeout(() => void poll(), 2_000);
    return () => {
      stopped = true;
      pollSequence.current += 1;
      if (timer !== undefined) window.clearTimeout(timer);
      controller?.abort();
    };
  }, [status?.state]);

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    navigationRequest.current += 1;
    const next = { ...draft, q: draft.q?.trim() || null };
    commitFilters(next);
    void loadResults(next);
  };

  const selectMode = (view: DriveView) => {
    navigationRequest.current += 1;
    const next: SavedSearchFilters = {
      ...draft,
      view,
      parent_id: view === "all" ? "root" : null,
      starred: null,
    };
    setFolder(rootFolder);
    setFolderError(null);
    commitFilters(next);
    void loadResults(next);
  };

  const navigateFolder = async (id: string) => {
    const navigation = ++navigationRequest.current;
    setFolderError(null);
    try {
      const nextFolder =
        id === "root" ? rootFolder : await fetchDriveFolder(id);
      if (navigation !== navigationRequest.current) return;
      const nextFilters: SavedSearchFilters = {
        ...latestFilters.current,
        view: "all",
        parent_id: id,
      };
      setFolder(nextFolder);
      commitFilters(nextFilters);
      void loadResults(nextFilters);
    } catch (error: unknown) {
      if (navigation !== navigationRequest.current) return;
      setFolderError(`Unable to open that folder. ${errorMessage(error)}`);
    }
  };

  const startSync = async () => {
    if (syncInFlight.current || status?.state === "syncing") return;
    syncInFlight.current = true;
    setSyncing(true);
    setStatusError(null);
    try {
      const nextStatus = await syncDriveCatalog(csrfToken);
      updateStatus(nextStatus);
      if (nextStatus.state !== "syncing") {
        await refreshAfterSync(nextStatus);
      }
    } catch (error: unknown) {
      setStatusError(errorMessage(error));
      try {
        updateStatus(await fetchDriveCatalogStatus());
      } catch {
        // Keep the original sync error visible.
      }
    } finally {
      syncInFlight.current = false;
      setSyncing(false);
    }
  };

  const saveCurrentSearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = saveName.trim();
    if (!name) return;
    setMutating(true);
    setSideError(null);
    try {
      const saved = await createSavedSearch(
        name,
        latestFilters.current,
        csrfToken,
      );
      setSavedSearches((current) => [...current, saved]);
      setSaveName("");
      setShowSaveForm(false);
    } catch (error: unknown) {
      setSideError(errorMessage(error));
    } finally {
      setMutating(false);
    }
  };

  const removeSavedSearch = async (saved: SavedSearch) => {
    setMutating(true);
    setSideError(null);
    try {
      await deleteSavedSearch(saved.id, csrfToken);
      setSavedSearches((current) =>
        current.filter((value) => value.id !== saved.id),
      );
    } catch (error: unknown) {
      setSideError(errorMessage(error));
    } finally {
      setMutating(false);
    }
  };

  const runSavedSearch = async (saved: SavedSearch) => {
    const navigation = ++navigationRequest.current;
    const next = saved.filters;
    setFolderError(null);
    if (next.parent_id && next.parent_id !== "root") {
      try {
        const nextFolder = await fetchDriveFolder(next.parent_id);
        if (navigation !== navigationRequest.current) return;
        setFolder(nextFolder);
      } catch {
        if (navigation !== navigationRequest.current) return;
        const recovered = {
          ...next,
          view: "all" as const,
          parent_id: "root",
        };
        setFolder(rootFolder);
        setFolderError(
          "The saved folder is no longer available. Showing this search from My Drive.",
        );
        commitFilters(recovered);
        void loadResults(recovered);
        return;
      }
    } else {
      setFolder(rootFolder);
    }
    if (navigation !== navigationRequest.current) return;
    commitFilters(next);
    void loadResults(next);
  };

  const pinCurrentFolder = async () => {
    if (folder.id === "root") return;
    setMutating(true);
    setSideError(null);
    try {
      const pin = await createPinnedLocation(folder.id, null, csrfToken);
      setPins((current) => [...current, pin]);
    } catch (error: unknown) {
      setSideError(errorMessage(error));
    } finally {
      setMutating(false);
    }
  };

  const removePin = async (pin: PinnedLocation) => {
    setMutating(true);
    setSideError(null);
    try {
      await deletePinnedLocation(pin.id, csrfToken);
      setPins((current) => current.filter((value) => value.id !== pin.id));
    } catch (error: unknown) {
      setSideError(errorMessage(error));
    } finally {
      setMutating(false);
    }
  };

  const loadMoreActivity = async () => {
    if (!activityCursor) return;
    setLoadingActivity(true);
    try {
      const response = await fetchDriveActivity(activityCursor);
      setActivity((current) => [...current, ...response.items]);
      setActivityCursor(response.next_cursor);
    } catch (error: unknown) {
      setSideError(errorMessage(error));
    } finally {
      setLoadingActivity(false);
    }
  };

  const activeMode = filters.view;
  const currentPinned = pins.some(
    (pin) => pin.drive_folder_id === folder.id && pin.available,
  );

  return (
    <div className="drive-workspace">
      <div
        className="sync-toolbar sync-readout"
        role="group"
        aria-label="Catalog sync controls"
      >
        <span
          className={`sync-state sync-state--${status?.state ?? "unknown"}`}
          aria-hidden="true"
        />
        <div>
          <strong>
            {status
              ? titleCase(status.phase ?? status.state)
              : "Reading status"}
          </strong>
          {status?.state === "syncing" && status.mode && (
            <small>
              {titleCase(status.mode)} sync
              {status.recovery ? " / recovery path" : ""}
            </small>
          )}
        </div>
        <button
          className="sync-action-button"
          type="button"
          onClick={() => void startSync()}
          disabled={!connected || syncing || status?.state === "syncing"}
        >
          {status?.state === "syncing" || syncing
            ? "Sync in progress"
            : status?.retryable
              ? "Retry sync"
              : "Sync now"}
        </button>
      </div>
      <SyncConsole status={status} error={statusError} />

      <div className="workspace-modebar" aria-label="Drive browser modes">
        {(["all", "recent", "starred"] as const).map((view) => (
          <button
            key={view}
            type="button"
            className={activeMode === view ? "is-active" : ""}
            aria-pressed={activeMode === view}
            onClick={() => selectMode(view)}
            disabled={!connected}
          >
            {view === "all" ? "My Drive" : titleCase(view)}
          </button>
        ))}
      </div>

      <div className="workspace-shell">
        <section className="ledger-panel" aria-label="Drive metadata browser">
          <div className="breadcrumb-bar">
            <nav aria-label="Folder breadcrumbs">
              {(filters.view === "all"
                ? folder.breadcrumbs
                : [rootFolder.breadcrumbs[0]]
              ).map((crumb, index, crumbs) => (
                <span key={crumb.id}>
                  <button
                    type="button"
                    onClick={() => void navigateFolder(crumb.id)}
                    disabled={!crumb.available || index === crumbs.length - 1}
                  >
                    {crumb.name}
                  </button>
                  {index < crumbs.length - 1 && <i aria-hidden="true">/</i>}
                </span>
              ))}
              {!folder.breadcrumbs_complete && (
                <small>Path is incomplete in this catalog revision.</small>
              )}
            </nav>
            {filters.view === "all" && folder.id !== "root" && (
              <div className="folder-actions">
                <button
                  type="button"
                  onClick={() => void pinCurrentFolder()}
                  disabled={mutating || currentPinned}
                >
                  {currentPinned ? "Pinned" : "Pin folder"}
                </button>
                <a href={folder.web_url} target="_blank" rel="noreferrer">
                  Open folder in Drive
                </a>
              </div>
            )}
          </div>
          {folderError && <p className="workspace-alert">{folderError}</p>}

          <FilterBar
            draft={draft}
            setDraft={setDraft}
            onSubmit={applyFilters}
            disabled={!connected}
          />

          <div className="ledger-status" aria-live="polite">
            <span>
              {results.phase === "ready"
                ? `${results.items.length} loaded${results.nextCursor ? " / more available" : ""}`
                : results.phase === "loading"
                  ? "Reading catalog index"
                  : "Listing unavailable"}
            </span>
            <span>Revision {status?.revision ?? "--"}</span>
          </div>

          {results.phase === "loading" && (
            <div className="ledger-empty" role="status">
              Scanning indexed metadata
            </div>
          )}
          {results.phase === "error" && (
            <div className="ledger-empty ledger-empty--error" role="alert">
              <strong>Catalog listing unavailable</strong>
              <span>{results.message}</span>
              {connected && (
                <button
                  type="button"
                  onClick={() => void loadResults(latestFilters.current)}
                >
                  Try again
                </button>
              )}
            </div>
          )}
          {results.phase === "ready" && results.items.length === 0 && (
            <div className="ledger-empty">
              <strong>No indexed items match this view.</strong>
              <span>Adjust the filters or run a fresh catalog sync.</span>
            </div>
          )}
          {results.phase === "ready" && results.items.length > 0 && (
            <div
              className="file-ledger"
              role="table"
              aria-label="Indexed Drive items"
            >
              <div className="ledger-head" role="row">
                <span role="columnheader">Type / name</span>
                <span role="columnheader">Location</span>
                <span role="columnheader">Modified</span>
                <span role="columnheader">Size</span>
                <span role="columnheader">Action</span>
              </div>
              {results.items.map((item) => (
                <LedgerRow
                  key={item.id}
                  item={item}
                  onOpenFolder={() => void navigateFolder(item.id)}
                />
              ))}
            </div>
          )}
          {pageError && (
            <div className="cursor-error" role="alert">
              <span>{pageError}</span>
              <button
                type="button"
                onClick={() => void loadResults(latestFilters.current)}
              >
                Restart listing
              </button>
            </div>
          )}
          {results.phase === "ready" && results.nextCursor && !pageError && (
            <button
              type="button"
              className="load-more"
              onClick={() =>
                void loadResults(
                  latestFilters.current,
                  results.nextCursor ?? undefined,
                )
              }
            >
              Load more metadata
            </button>
          )}
        </section>

        <aside
          className="workspace-sidecar"
          aria-label="Drive workspace shortcuts"
        >
          {!connected ? (
            <DisconnectedState
              title="Workspace shortcuts unavailable"
              message="Connect Google Drive to load saved searches and pinned folders."
            />
          ) : (
            <>
              {sideError && (
                <p className="workspace-alert" role="alert">
                  {sideError}
                </p>
              )}
              <SidecarSection
                title="Saved searches"
                count={savedSearches.length}
              >
                {savedSearches.length === 0 ? (
                  <p className="sidecar-empty">
                    No saved searches. Save the current filter set for quick
                    access.
                  </p>
                ) : (
                  <ul className="sidecar-list">
                    {savedSearches.map((saved) => (
                      <li key={saved.id}>
                        <button
                          type="button"
                          onClick={() => void runSavedSearch(saved)}
                        >
                          <strong>{saved.name}</strong>
                          <small>{filterSummary(saved.filters)}</small>
                        </button>
                        <button
                          type="button"
                          className="remove-control"
                          aria-label={`Delete saved search ${saved.name}`}
                          onClick={() => void removeSavedSearch(saved)}
                          disabled={mutating}
                        >
                          Remove
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {showSaveForm ? (
                  <form
                    className="inline-save"
                    onSubmit={(event) => void saveCurrentSearch(event)}
                  >
                    <label htmlFor="saved-search-name">Search name</label>
                    <input
                      id="saved-search-name"
                      value={saveName}
                      onChange={(event) => setSaveName(event.target.value)}
                      maxLength={100}
                      autoFocus
                      required
                    />
                    <div>
                      <button
                        type="submit"
                        disabled={mutating || !saveName.trim()}
                      >
                        Save current
                      </button>
                      <button
                        type="button"
                        onClick={() => setShowSaveForm(false)}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <button
                    className="sidecar-action"
                    type="button"
                    onClick={() => setShowSaveForm(true)}
                    disabled={!connected}
                  >
                    Save current search
                  </button>
                )}
              </SidecarSection>

              <SidecarSection title="Pinned folders" count={pins.length}>
                {pins.length === 0 ? (
                  <p className="sidecar-empty">
                    Open a folder in the ledger to pin its location.
                  </p>
                ) : (
                  <ul className="sidecar-list">
                    {pins.map((pin) => (
                      <li
                        key={pin.id}
                        className={!pin.available ? "is-unavailable" : ""}
                      >
                        <button
                          type="button"
                          onClick={() =>
                            void navigateFolder(pin.drive_folder_id)
                          }
                          disabled={!pin.available}
                        >
                          <strong>
                            {pin.label ?? pin.folder_name ?? "Unnamed folder"}
                          </strong>
                          <small>
                            {pin.available
                              ? "Indexed folder"
                              : "Unavailable in current catalog"}
                          </small>
                        </button>
                        <button
                          type="button"
                          className="remove-control"
                          aria-label={`Remove pinned folder ${pin.label ?? pin.folder_name ?? "Unnamed folder"}`}
                          onClick={() => void removePin(pin)}
                          disabled={mutating}
                        >
                          Remove
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </SidecarSection>
            </>
          )}
        </aside>
      </div>

      <InsightsPanel insights={insights} connected={connected} />
      <div className="workspace-lower-grid">
        <SyncHistory attempts={history} connected={connected} />
        <ActivityFeed
          items={activity}
          message={activityMessage}
          hasMore={Boolean(activityCursor)}
          loading={loadingActivity}
          onMore={() => void loadMoreActivity()}
          connected={connected}
        />
      </div>
    </div>
  );
}

function SyncConsole({
  status,
  error,
}: {
  status: DriveCatalogStatus | null;
  error: string | null;
}) {
  const active = status?.state === "syncing";
  const processed = status?.processed_count ?? 0;
  const total = status?.total_count;
  const percent = total
    ? Math.min(100, (processed / total) * 100)
    : active
      ? 12
      : 100;
  return (
    <section className="sync-console" aria-label="Catalog sync">
      <span className="sync-progress-label">
        {total ? `${processed} / ${total}` : `${processed} processed`}
      </span>
      <div
        className="sync-progress"
        role="progressbar"
        aria-label="Catalog sync progress"
        aria-valuemin={0}
        aria-valuemax={total ?? undefined}
        aria-valuenow={total ? processed : undefined}
        aria-valuetext={total ? `${processed} of ${total}` : status?.message}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="sync-foot">
        <span>
          {status?.last_synced_at
            ? `Last success ${formatDateTime(status.last_synced_at)}`
            : (status?.message ?? "No catalog sync recorded")}
        </span>
      </div>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

function FilterBar({
  draft,
  setDraft,
  onSubmit,
  disabled,
}: {
  draft: SavedSearchFilters;
  setDraft: (filters: SavedSearchFilters) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  disabled: boolean;
}) {
  const patch = (next: Partial<SavedSearchFilters>) =>
    setDraft({ ...draft, ...next });
  return (
    <form className="workspace-filters" onSubmit={onSubmit}>
      <label className="search-field">
        <span>Search indexed names</span>
        <input
          type="search"
          value={draft.q ?? ""}
          onChange={(event) => patch({ q: event.target.value })}
          placeholder="Name contains..."
          maxLength={200}
          disabled={disabled}
        />
      </label>
      <label>
        <span>Kind</span>
        <select
          value={draft.kind}
          onChange={(event) =>
            patch({ kind: event.target.value as DriveKind | "all" })
          }
          disabled={disabled}
        >
          <option value="all">All types</option>
          {Object.entries(kindLabels).map(([kind, label]) => (
            <option key={kind} value={kind}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Sort</span>
        <select
          value={draft.sort}
          onChange={(event) => patch({ sort: event.target.value as DriveSort })}
          disabled={disabled}
        >
          <option value="modified">Modified</option>
          <option value="created">Created</option>
          <option value="name">Name</option>
          <option value="size">Size</option>
        </select>
      </label>
      <label>
        <span>Direction</span>
        <select
          value={draft.direction}
          onChange={(event) =>
            patch({ direction: event.target.value as DriveDirection })
          }
          disabled={disabled}
        >
          <option value="desc">Descending</option>
          <option value="asc">Ascending</option>
        </select>
      </label>
      <label className="filter-check">
        <input
          type="checkbox"
          checked={draft.starred === true}
          onChange={(event) =>
            patch({ starred: event.target.checked ? true : null })
          }
          disabled={disabled}
        />
        <span>Starred only</span>
      </label>
      <details className="advanced-filters">
        <summary>Size and date</summary>
        <div>
          <label>
            <span>Modified after</span>
            <input
              type="date"
              value={dateInputValue(draft.modified_after)}
              onChange={(event) =>
                patch({
                  modified_after: dateApiValue(event.target.value, false),
                })
              }
              disabled={disabled}
            />
          </label>
          <label>
            <span>Modified before</span>
            <input
              type="date"
              value={dateInputValue(draft.modified_before, true)}
              onChange={(event) =>
                patch({
                  modified_before: dateApiValue(event.target.value, true),
                })
              }
              disabled={disabled}
            />
          </label>
          <label>
            <span>Minimum bytes</span>
            <input
              type="number"
              min="0"
              value={draft.min_size ?? ""}
              onChange={(event) =>
                patch({ min_size: numberInputValue(event.target.value) })
              }
              disabled={disabled}
            />
          </label>
          <label>
            <span>Maximum bytes</span>
            <input
              type="number"
              min="0"
              value={draft.max_size ?? ""}
              onChange={(event) =>
                patch({ max_size: numberInputValue(event.target.value) })
              }
              disabled={disabled}
            />
          </label>
        </div>
      </details>
      <button className="apply-filters" type="submit" disabled={disabled}>
        Apply filters
      </button>
    </form>
  );
}

function LedgerRow({
  item,
  onOpenFolder,
}: {
  item: SearchResult;
  onOpenFolder: () => void;
}) {
  const statusLabels = item.status_labels.filter(
    (label, index, labels) =>
      labels.findIndex(
        (value) => value.toLocaleLowerCase() === label.toLocaleLowerCase(),
      ) === index,
  );
  const labels = [
    kindLabels[item.kind],
    ...(item.starred &&
    !statusLabels.some((label) => label.toLocaleLowerCase() === "starred")
      ? ["Starred"]
      : []),
    ...statusLabels.map(titleCase),
  ];
  return (
    <article className="ledger-row" role="row">
      <div className="ledger-identity" role="cell">
        <span
          className={`kind-code kind-code--${item.kind}`}
          aria-hidden="true"
        >
          {kindCode(item.kind)}
        </span>
        <div>
          {item.kind === "folder" ? (
            <button type="button" onClick={onOpenFolder}>
              {item.name}
            </button>
          ) : (
            <a href={item.web_url} target="_blank" rel="noreferrer">
              {item.name}
            </a>
          )}
          <span>{labels.join(" / ")}</span>
        </div>
      </div>
      <span className="ledger-parent" role="cell" aria-label="Location">
        <span className="mobile-label" aria-hidden="true">
          Location
        </span>
        {item.parent ? item.parent.name : "My Drive"}
        {item.parent && !item.parent.available ? " (unavailable)" : ""}
      </span>
      <span role="cell" aria-label="Modified">
        <span className="mobile-label" aria-hidden="true">
          Modified
        </span>
        {formatDateTime(item.modified_at)}
      </span>
      <span role="cell" aria-label="Size">
        <span className="mobile-label" aria-hidden="true">
          Size
        </span>
        {item.size_bytes === null
          ? "Cloud document"
          : formatBytes(item.size_bytes)}
      </span>
      <span role="cell" aria-label="Action">
        <a
          className="row-drive-link"
          href={item.web_url}
          target="_blank"
          rel="noreferrer"
        >
          Open in Drive
        </a>
      </span>
    </article>
  );
}

function DisconnectedState({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <div className="workspace-disconnected">
      <span aria-hidden="true">OFF</span>
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}

function SidecarSection({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section className="sidecar-section">
      <header>
        <h3>{title}</h3>
        <span>{String(count).padStart(2, "0")}</span>
      </header>
      {children}
    </section>
  );
}

function InsightsPanel({
  insights,
  connected,
}: {
  insights: DriveInsights | null;
  connected: boolean;
}) {
  if (!connected) {
    return (
      <section className="insights-panel panel">
        <DisconnectedState
          title="Storage insights unavailable"
          message="Connect Google Drive to compare account quota with indexed metadata."
        />
      </section>
    );
  }
  if (!insights) {
    return (
      <section className="insights-panel panel">
        <h2>Storage insights</h2>
        <p>
          Insights are unavailable until indexed metadata has been collected.
        </p>
      </section>
    );
  }
  const quotaPercent =
    insights.account_used_bytes !== null && insights.account_total_bytes
      ? Math.min(
          100,
          (insights.account_used_bytes / insights.account_total_bytes) * 100,
        )
      : null;
  return (
    <section
      className="insights-panel panel"
      aria-labelledby="insights-heading"
    >
      <header>
        <h2 id="insights-heading">Storage insights</h2>
      </header>
      <div className="insights-grid">
        <div className="quota-readout">
          <span>Google account quota</span>
          <strong>
            {insights.account_used_bytes === null
              ? "Unavailable"
              : `${formatBytes(insights.account_used_bytes)} used`}
          </strong>
          <small>
            {insights.account_total_bytes === null
              ? "Drive did not report a total quota."
              : `of ${formatBytes(insights.account_total_bytes)} account storage`}
          </small>
          {quotaPercent !== null && (
            <div className="quota-track" aria-hidden="true">
              <span style={{ width: `${quotaPercent}%` }} />
            </div>
          )}
        </div>
        <div className="indexed-readout">
          <span>Indexed known size</span>
          <strong>{formatBytes(insights.catalog_known_size_bytes)}</strong>
          <small>
            Separate from quota / {insights.catalog_unknown_size_count} items
            have unknown size
          </small>
        </div>
        <div className="kind-breakdown">
          <span>Catalog by type</span>
          <ul>
            {insights.by_kind.map((group) => (
              <li key={group.kind}>
                <span>{kindLabels[group.kind]}</span>
                <strong>{group.item_count}</strong>
                <small>{formatBytes(group.known_size_bytes)}</small>
              </li>
            ))}
          </ul>
        </div>
        <InsightList
          title="Largest indexed files"
          files={insights.largest_files}
        />
        <InsightList title="Stale indexed files" files={insights.stale_files} />
      </div>
    </section>
  );
}

function InsightList({
  title,
  files,
}: {
  title: string;
  files: DriveInsights["largest_files"];
}) {
  return (
    <div className="insight-list">
      <span>{title}</span>
      {files.length === 0 ? (
        <p>No files in this advisory set.</p>
      ) : (
        <ul>
          {files.map((file) => (
            <li key={file.id}>
              <a href={file.web_url} target="_blank" rel="noreferrer">
                {file.name}
              </a>
              <small>
                {file.size_bytes === null
                  ? "Unknown size"
                  : formatBytes(file.size_bytes)}{" "}
                / {formatDate(file.modified_at)}
              </small>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SyncHistory({
  attempts,
  connected,
}: {
  attempts: SyncAttempt[];
  connected: boolean;
}) {
  return (
    <section className="history-panel panel" aria-labelledby="history-heading">
      <header>
        <h2 id="history-heading">Recent sync attempts</h2>
        <span>{attempts.length} recorded</span>
      </header>
      {!connected ? (
        <DisconnectedState
          title="Sync history unavailable"
          message="Connect Google Drive to record catalog synchronization attempts."
        />
      ) : attempts.length === 0 ? (
        <p className="lower-empty">No sync attempts have been recorded.</p>
      ) : (
        <ol className="history-list">
          {attempts.map((attempt) => (
            <li key={attempt.id}>
              <span
                className={`attempt-status attempt-status--${attempt.status}`}
              />
              <div>
                <strong>{titleCase(attempt.mode)} sync</strong>
                <small>
                  {titleCase(attempt.phase)} / {attempt.processed_count}
                  {attempt.total_count === null
                    ? ""
                    : ` of ${attempt.total_count}`}
                </small>
                {attempt.error && <p>{attempt.error}</p>}
              </div>
              <time dateTime={attempt.started_at}>
                {formatDateTime(attempt.started_at)}
              </time>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ActivityFeed({
  items,
  message,
  hasMore,
  loading,
  onMore,
  connected,
}: {
  items: DriveActivityEvent[];
  message: string;
  hasMore: boolean;
  loading: boolean;
  onMore: () => void;
  connected: boolean;
}) {
  return (
    <section
      className="activity-panel panel"
      aria-labelledby="activity-heading"
    >
      <header>
        <h2 id="activity-heading">Catalog activity</h2>
      </header>
      {connected && <p className="activity-scope">{message}</p>}
      {!connected ? (
        <DisconnectedState
          title="Catalog activity unavailable"
          message="Connect Google Drive to observe metadata changes during synchronization."
        />
      ) : items.length === 0 ? (
        <p className="lower-empty">No catalog activity has been observed.</p>
      ) : (
        <ol className="activity-list">
          {items.map((item) => (
            <li key={item.id}>
              <span>{activityCode(item.event_type)}</span>
              <div>
                <strong>{item.name ?? titleCase(item.event_type)}</strong>
                <p>{item.summary}</p>
              </div>
              <time dateTime={item.observed_at}>
                {formatDateTime(item.observed_at)}
              </time>
            </li>
          ))}
        </ol>
      )}
      {hasMore && (
        <button
          className="load-more"
          type="button"
          onClick={onMore}
          disabled={loading}
        >
          {loading ? "Loading activity" : "Load earlier activity"}
        </button>
      )}
    </section>
  );
}

function filterSummary(filters: SavedSearchFilters): string {
  const parts = [
    filters.view === "all" ? "My Drive" : titleCase(filters.view),
    filters.kind === "all" ? null : kindLabels[filters.kind],
    filters.q ? `“${filters.q}”` : null,
    filters.starred ? "starred" : null,
  ];
  return parts.filter(Boolean).join(" / ");
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Ark API request failed.";
}

function dateInputValue(
  value: string | null | undefined,
  exclusiveEnd = false,
): string {
  if (!value) return "";
  if (!exclusiveEnd) return value.slice(0, 10);
  const date = new Date(value);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

function dateApiValue(value: string, exclusiveEnd: boolean): string | null {
  if (!value) return null;
  if (!exclusiveEnd) return `${value}T00:00:00Z`;
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString();
}

function shouldAcceptCatalogStatus(
  current: DriveCatalogStatus | null,
  next: DriveCatalogStatus,
): boolean {
  if (!current) return true;
  if (next.revision < current.revision) return false;
  const currentStarted = current.last_started_at
    ? Date.parse(current.last_started_at)
    : 0;
  const nextStarted = next.last_started_at
    ? Date.parse(next.last_started_at)
    : 0;
  if (nextStarted < currentStarted) return false;
  return !(
    current.state !== "syncing" &&
    next.state === "syncing" &&
    next.revision === current.revision &&
    nextStarted === currentStarted
  );
}

function numberInputValue(value: string): number | null {
  return value === "" ? null : Number(value);
}

function kindCode(kind: DriveKind): string {
  return kind === "folder" ? "DIR" : kind.slice(0, 3).toUpperCase();
}

function activityCode(event: DriveActivityEvent["event_type"]): string {
  const values: Record<DriveActivityEvent["event_type"], string> = {
    created: "NEW",
    modified: "MOD",
    removed: "DEL",
    sync_completed: "OK",
    sync_failed: "ERR",
  };
  return values[event];
}

function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB", "PiB"];
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length,
  );
  const value = bytes / 1024 ** exponent;
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[exponent - 1]}`;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}
