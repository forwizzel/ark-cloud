export type StorageOperation = {
  action:
    | "add"
    | "init"
    | "update"
    | "remove"
    | "refresh-identity"
    | "check"
    | "browse"
    | "preflight"
    | "relocate";
  root_id?: string;
  path?: string;
  label?: string;
  owner?: string;
  read_only?: boolean;
  selinux?: "preserve" | "private" | "shared";
  confirmed?: boolean;
  managed?: boolean;
  grant_access?: boolean;
};

export type StorageJob = {
  id: string;
  action: string;
  payload: Partial<StorageOperation>;
  state: "queued" | "applying" | "verifying" | "completed" | "failed";
  disposition?:
    | "current"
    | "attention"
    | "history"
    | "dismissed"
    | "canceled"
    | "superseded"
    | "resolved"
    | "obsolete";
  can_retry?: boolean;
  retry_reason?: string | null;
  can_dismiss?: boolean;
  message: string;
  result: {
    path?: string;
    folders?: string[];
    parent?: string | null;
    message?: string;
    api_host_uid?: number;
  };
  created_at: string;
};

export type ManagedLocation = {
  id: string;
  label: string;
  source: string;
  kind: "managed" | "assigned";
  owner: string | null;
  username: string | null;
  read_only: boolean;
  selinux: "preserve" | "private" | "shared";
  state: "healthy" | "unavailable";
  message: string;
};

export type StorageAdministration = {
  configuration_error: string | null;
  manager: {
    enrolled: boolean;
    online: boolean;
    last_seen_at: string | null;
    approved_paths: string[];
    approved_areas?: { path: string; state: string; message: string }[];
  };
  setup: {
    default_path: string;
    repository_path: string | null;
    job: StorageJob | null;
    interrupted?: boolean;
  };
  roots: ManagedLocation[];
  jobs: StorageJob[];
  upload_max_bytes: number;
  upload_limit_source: "ui" | "environment";
  users: { id: string; username: string; active: boolean; pending: boolean }[];
};

export async function storageRequest<T>(
  path: string,
  csrf: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method,
    signal,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const error = (await response.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : "Storage request failed. Refresh and retry.",
    );
  }
  return response.json() as Promise<T>;
}

export const fetchStorageAdministration = (
  csrf: string,
  signal?: AbortSignal,
) =>
  storageRequest<StorageAdministration>(
    "admin/storage",
    csrf,
    "GET",
    undefined,
    signal,
  );

export const submitStorageOperation = (body: StorageOperation, csrf: string) =>
  storageRequest<StorageJob>("admin/storage/jobs", csrf, "POST", body);
