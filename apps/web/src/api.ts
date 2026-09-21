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
  message: string;
};

export type SearchResult = {
  source: "google_drive";
  id: string;
  name: string;
  mime_type: string;
  size_bytes: number | null;
  modified_at: string;
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
  query: string,
  cursor?: string | null,
): Promise<SearchResponse> {
  const parameters = new URLSearchParams({ q: query });
  if (cursor) parameters.set("cursor", cursor);
  return apiResponse<SearchResponse>(
    await fetch(`/api/search?${parameters.toString()}`),
  );
}
