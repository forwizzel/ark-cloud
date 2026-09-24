export type IntegrationState =
  "healthy" | "degraded" | "unavailable" | "not_configured";

export type IntegrationHealth = {
  id: string;
  name: string;
  state: IntegrationState;
  message: string;
  checked_at: string;
};

export type ResourceUsage = {
  total_bytes: number;
  used_bytes: number;
  available_bytes: number;
  percent: number;
};

export type SystemSummary = {
  hostname: string;
  os: string;
  kernel: string;
  uptime_seconds: number;
  cpu_percent: number;
  cpu_count: number;
  memory: ResourceUsage;
  storage: ResourceUsage;
  storage_path: string;
  scope: "api-runtime-view";
  collected_at: string;
};

export type TailscaleDevice = {
  id: string;
  hostname: string;
  os: string;
  addresses: string[];
  online: boolean;
  last_seen: string | null;
};

export type Dashboard = {
  platform: {
    status: "healthy" | "unhealthy";
    service: string;
    database: "connected" | "disconnected";
  };
  system: SystemSummary | null;
  tailscale: {
    state: IntegrationState;
    device_count: number;
    online_count: number;
    devices: TailscaleDevice[];
    message: string;
    collected_at: string;
  };
  google_drive: GoogleDriveSummary;
  integrations: IntegrationHealth[];
  generated_at: string;
};

export type GoogleDriveSummary = {
  state: IntegrationState;
  account_email: string | null;
  account_name: string | null;
  used_bytes: number | null;
  total_bytes: number | null;
  available_bytes: number | null;
  percent: number | null;
  message: string;
  checked_at: string;
  web_url: string;
};

export type CatalogState =
  "not_configured" | "not_synced" | "syncing" | "ready" | "error";

export type DriveCatalogStatus = {
  state: CatalogState;
  item_count: number;
  last_synced_at: string | null;
  revision: number;
  last_started_at: string | null;
  mode: DriveSyncMode | null;
  phase: DriveSyncPhase | null;
  processed_count: number;
  total_count: number | null;
  retryable: boolean;
  recovery: boolean;
  message: string;
};

export type DriveKind =
  "folder" | "document" | "image" | "video" | "audio" | "archive" | "other";

export type DriveParent = {
  id: string;
  name: string;
  available: boolean;
};

export type SearchResult = {
  source: "google_drive";
  id: string;
  name: string;
  mime_type: string;
  size_bytes: number | null;
  kind: DriveKind;
  created_at: string | null;
  modified_at: string;
  starred: boolean;
  ownership: "owned_by_me";
  parent: DriveParent | null;
  status_labels: string[];
  web_url: string;
};

export type SearchResponse = {
  items: SearchResult[];
  next_cursor: string | null;
  catalog: DriveCatalogStatus;
};

export type AuthSession = {
  authenticated: boolean;
  username: string | null;
  csrf_token: string | null;
};

export type DriveView = "all" | "recent" | "starred";
export type DriveSort = "modified" | "created" | "name" | "size";
export type DriveDirection = "asc" | "desc";
export type DriveSyncMode = "full" | "incremental" | "recovery";
export type DriveSyncPhase =
  "starting" | "fetching" | "applying" | "completed" | "failed";

export type DriveItemQuery = {
  q?: string | null;
  view?: DriveView;
  kind?: DriveKind | "all";
  parent_id?: string | null;
  modified_after?: string | null;
  modified_before?: string | null;
  min_size?: number | null;
  max_size?: number | null;
  starred?: boolean | null;
  ownership?: "owned_by_me";
  sort?: DriveSort;
  direction?: DriveDirection;
  cursor?: string;
  limit?: number;
};

export type DriveFolder = {
  id: string;
  name: string;
  web_url: string;
  modified_at: string | null;
  starred: boolean;
  breadcrumbs: DriveParent[];
  breadcrumbs_complete: boolean;
};

export type SavedSearchFilters = {
  q?: string | null;
  view: DriveView;
  kind: DriveKind | "all";
  parent_id?: string | null;
  modified_after?: string | null;
  modified_before?: string | null;
  min_size?: number | null;
  max_size?: number | null;
  starred?: boolean | null;
  ownership: "owned_by_me";
  sort: DriveSort;
  direction: DriveDirection;
};

export type SavedSearch = {
  id: string;
  name: string;
  filters: SavedSearchFilters;
  created_at: string;
};

export type PinnedLocation = {
  id: string;
  drive_folder_id: string;
  label: string | null;
  folder_name: string | null;
  available: boolean;
  web_url: string | null;
  created_at: string;
};

export type KindInsight = {
  kind: DriveKind;
  item_count: number;
  known_size_bytes: number;
  unknown_size_count: number;
};

export type InsightFile = {
  id: string;
  name: string;
  kind: Exclude<DriveKind, "folder">;
  size_bytes: number | null;
  modified_at: string;
  web_url: string;
};

export type DriveInsights = {
  account_used_bytes: number | null;
  account_total_bytes: number | null;
  catalog_known_size_bytes: number;
  catalog_unknown_size_count: number;
  by_kind: KindInsight[];
  largest_files: InsightFile[];
  stale_files: InsightFile[];
  freshness_at: string | null;
};

export type SyncAttempt = {
  id: string;
  mode: DriveSyncMode;
  status: "running" | "success" | "failed";
  phase: DriveSyncPhase;
  processed_count: number;
  total_count: number | null;
  retryable: boolean;
  recovery: boolean;
  error: string | null;
  started_at: string;
  completed_at: string | null;
};

export type DriveActivityEvent = {
  id: string;
  event_type:
    "created" | "modified" | "removed" | "sync_completed" | "sync_failed";
  file_id: string | null;
  name: string | null;
  kind: DriveKind | null;
  summary: string;
  observed_at: string;
};

export type DriveActivityResponse = {
  items: DriveActivityEvent[];
  next_cursor: string | null;
  scope: "sync_observed";
  message: string;
};

async function apiResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(payload?.detail ?? "Ark API request failed.");
  }
  return (await response.json()) as T;
}

export async function fetchSession(): Promise<AuthSession> {
  return apiResponse<AuthSession>(await fetch("/api/auth/session"));
}

export async function login(
  username: string,
  password: string,
): Promise<AuthSession> {
  return apiResponse<AuthSession>(
    await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),
  );
}

export async function logout(csrfToken: string): Promise<void> {
  const response = await fetch("/api/auth/logout", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
  if (!response.ok && response.status !== 204) {
    throw new Error("Unable to log out.");
  }
}

export async function fetchDashboard(signal: AbortSignal): Promise<Dashboard> {
  const response = await fetch("/api/dashboard", { signal });
  if (!response.ok) {
    throw new Error("Ark API could not assemble the dashboard.");
  }
  return (await response.json()) as Dashboard;
}

export async function refreshGoogleDrive(
  csrfToken: string,
): Promise<GoogleDriveSummary> {
  return apiResponse<GoogleDriveSummary>(
    await fetch("/api/integrations/google-drive/refresh", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    }),
  );
}

export async function disconnectGoogleDrive(csrfToken: string): Promise<void> {
  const response = await fetch("/api/integrations/google-drive/disconnect", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
  if (response.status !== 204) {
    await apiResponse(response);
  }
}

export async function fetchDriveCatalogStatus(
  signal?: AbortSignal,
): Promise<DriveCatalogStatus> {
  return apiResponse<DriveCatalogStatus>(
    await fetch("/api/integrations/google-drive/catalog/status", { signal }),
  );
}

export async function syncDriveCatalog(
  csrfToken: string,
): Promise<DriveCatalogStatus> {
  return apiResponse<DriveCatalogStatus>(
    await fetch("/api/integrations/google-drive/catalog/sync", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    }),
  );
}

export async function searchCatalog(
  query: DriveItemQuery,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const parameters = driveQueryParameters(query);
  return apiResponse<SearchResponse>(
    await fetch(
      `/api/integrations/google-drive/items?${parameters.toString()}`,
      { signal },
    ),
  );
}

export function driveQueryParameters(query: DriveItemQuery): URLSearchParams {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      parameters.set(key, String(value));
    }
  }
  return parameters;
}

export async function fetchDriveFolder(
  id: string,
  signal?: AbortSignal,
): Promise<DriveFolder> {
  return apiResponse<DriveFolder>(
    await fetch(
      `/api/integrations/google-drive/folders/${encodeURIComponent(id)}`,
      { signal },
    ),
  );
}

export async function fetchSavedSearches(): Promise<SavedSearch[]> {
  const response = await apiResponse<{ items: SavedSearch[] }>(
    await fetch("/api/integrations/google-drive/saved-searches"),
  );
  return response.items;
}

export async function createSavedSearch(
  name: string,
  filters: SavedSearchFilters,
  csrfToken: string,
): Promise<SavedSearch> {
  return apiResponse<SavedSearch>(
    await fetch("/api/integrations/google-drive/saved-searches", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({ name, ...filters }),
    }),
  );
}

export async function deleteSavedSearch(
  id: string,
  csrfToken: string,
): Promise<void> {
  await deleteMutation(
    `/api/integrations/google-drive/saved-searches/${encodeURIComponent(id)}`,
    csrfToken,
  );
}

export async function fetchPinnedLocations(): Promise<PinnedLocation[]> {
  const response = await apiResponse<{ items: PinnedLocation[] }>(
    await fetch("/api/integrations/google-drive/pinned-locations"),
  );
  return response.items;
}

export async function createPinnedLocation(
  driveFolderId: string,
  label: string | null,
  csrfToken: string,
): Promise<PinnedLocation> {
  return apiResponse<PinnedLocation>(
    await fetch("/api/integrations/google-drive/pinned-locations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({
        drive_folder_id: driveFolderId,
        ...(label ? { label } : {}),
      }),
    }),
  );
}

export async function deletePinnedLocation(
  id: string,
  csrfToken: string,
): Promise<void> {
  await deleteMutation(
    `/api/integrations/google-drive/pinned-locations/${encodeURIComponent(id)}`,
    csrfToken,
  );
}

export async function fetchDriveInsights(): Promise<DriveInsights> {
  return apiResponse<DriveInsights>(
    await fetch("/api/integrations/google-drive/insights"),
  );
}

export async function fetchSyncHistory(limit = 8): Promise<SyncAttempt[]> {
  const response = await apiResponse<{ items: SyncAttempt[] }>(
    await fetch(
      `/api/integrations/google-drive/catalog/syncs?${new URLSearchParams({ limit: String(limit) })}`,
    ),
  );
  return response.items;
}

export async function fetchDriveActivity(
  cursor?: string | null,
  limit = 12,
): Promise<DriveActivityResponse> {
  const parameters = new URLSearchParams({ limit: String(limit) });
  if (cursor) parameters.set("cursor", cursor);
  return apiResponse<DriveActivityResponse>(
    await fetch(
      `/api/integrations/google-drive/activity?${parameters.toString()}`,
    ),
  );
}

async function deleteMutation(url: string, csrfToken: string): Promise<void> {
  const response = await fetch(url, {
    method: "DELETE",
    headers: { "X-CSRF-Token": csrfToken },
  });
  if (response.status !== 204) await apiResponse(response);
}
