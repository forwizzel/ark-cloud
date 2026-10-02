export type StorageRoot = {
  id: string;
  label: string;
  read_only: boolean;
  state: "healthy" | "unavailable";
  message: string;
  total_bytes: number | null;
  available_bytes: number | null;
  kind?: "managed" | "assigned" | "shared";
  needs_setup?: boolean;
};

export type LocalItem = {
  name: string;
  path: string;
  kind: "file" | "folder";
  size_bytes: number | null;
  modified_at: string;
  revision: string;
};

export type LocalListing = {
  items: LocalItem[];
  revision: string;
  next_offset: number | null;
  skipped_count: number;
};

async function response<T>(result: Response): Promise<T> {
  if (!result.ok) {
    const body = (await result.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : "File request failed. Refresh and retry.",
    );
  }
  if (result.status === 204) return undefined as T;
  return result.json() as Promise<T>;
}

export function storageUrl(
  root: string,
  action: string,
  parameters: Record<string, string> = {},
) {
  return `/api/storage/${encodeURIComponent(root)}/${action}?${new URLSearchParams(parameters)}`;
}

export async function fetchStorageRoots(signal?: AbortSignal, refresh = false) {
  return response<{ roots: StorageRoot[]; message: string }>(
    await fetch(`/api/storage/roots${refresh ? "?refresh=true" : ""}`, {
      signal,
    }),
  );
}

export type StoragePreference = {
  root_id: string | null;
  path: string;
  upload_max_bytes: number;
};

export async function fetchStoragePreference(signal?: AbortSignal) {
  return response<StoragePreference>(
    await fetch("/api/storage/preferences", { signal }),
  );
}

export async function saveStoragePreference(
  root: string | null,
  path: string,
  csrf: string,
) {
  return response<StoragePreference>(
    await fetch("/api/storage/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ root_id: root, path }),
    }),
  );
}

export async function provisionPrivateFolder(csrf: string) {
  return response<void>(
    await fetch("/api/storage/private-folder", {
      method: "POST",
      headers: { "X-CSRF-Token": csrf },
    }),
  );
}

export async function fetchLocalItems(
  root: string,
  path: string,
  signal?: AbortSignal,
  page?: LocalListing,
) {
  return response<LocalListing>(
    await fetch(
      storageUrl(root, "items", {
        path,
        ...(page?.next_offset !== null && page?.next_offset !== undefined
          ? { offset: String(page.next_offset), revision: page.revision }
          : {}),
      }),
      { signal },
    ),
  );
}

export async function localMutation(
  root: string,
  action: "folders" | "move" | "delete",
  csrf: string,
  body: { path: string; destination?: string; revision?: string },
) {
  const deleting = action === "delete";
  return response<void>(
    await fetch(
      storageUrl(
        root,
        deleting ? "items" : action,
        deleting
          ? { path: body.path, revision: body.revision ?? "", confirm: "true" }
          : {},
      ),
      {
        method: deleting ? "DELETE" : "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        ...(deleting ? {} : { body: JSON.stringify(body) }),
      },
    ),
  );
}

export function uploadLocalFile(
  root: string,
  path: string,
  file: File,
  csrf: string,
  onProgress: (percent: number) => void,
) {
  const request = new XMLHttpRequest();
  const done = new Promise<void>((resolve, reject) => {
    request.open("POST", storageUrl(root, "upload", { path }));
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.setRequestHeader("X-CSRF-Token", csrf);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () =>
      reject(
        new Error(
          "Upload connection lost. Refresh the folder before retrying.",
        ),
      );
    request.onabort = () =>
      reject(
        new Error("Upload cancelled. Refresh to check whether it completed."),
      );
    request.onload = () => {
      if (request.status === 201) resolve();
      else {
        let message = "Upload failed. Refresh and retry.";
        try {
          const body = JSON.parse(request.responseText) as { detail?: unknown };
          if (typeof body.detail === "string") message = body.detail;
        } catch {
          /* A proxy may return a non-JSON error. */
        }
        reject(new Error(message));
      }
    };
    request.send(file);
  });
  return { done, cancel: () => request.abort() };
}
