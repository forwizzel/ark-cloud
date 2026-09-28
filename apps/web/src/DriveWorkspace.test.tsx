import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import DriveWorkspace from "./DriveWorkspace";
import type { DriveCatalogStatus, SearchResult } from "./api";

const status: DriveCatalogStatus = {
  state: "ready",
  item_count: 3,
  last_synced_at: "2026-09-23T12:00:00Z",
  revision: 7,
  last_started_at: "2026-09-23T11:59:00Z",
  mode: "incremental",
  phase: "completed",
  processed_count: 3,
  total_count: 3,
  retryable: false,
  recovery: false,
  message: "Catalog is current.",
};

const projectFolder: SearchResult = {
  source: "google_drive",
  id: "projects",
  name: "Projects",
  mime_type: "application/vnd.google-apps.folder",
  size_bytes: null,
  kind: "folder",
  created_at: "2025-01-01T00:00:00Z",
  modified_at: "2026-09-20T12:00:00Z",
  starred: true,
  ownership: "owned_by_me",
  parent: { id: "root", name: "My Drive", available: true },
  status_labels: [],
  web_url: "https://drive.google.com/drive/folders/projects",
};

const projectFile: SearchResult = {
  source: "google_drive",
  id: "brief",
  name: "Phase 4 Brief.pdf",
  mime_type: "application/pdf",
  size_bytes: 8192,
  kind: "document",
  created_at: "2026-08-01T00:00:00Z",
  modified_at: "2026-09-22T12:00:00Z",
  starred: false,
  ownership: "owned_by_me",
  parent: { id: "projects", name: "Projects", available: true },
  status_labels: ["recent"],
  web_url: "https://drive.google.com/open?id=brief",
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("loads root items and navigates folders and breadcrumbs inside Ark", async () => {
  const fetchMock = workspaceFetch();
  render(<DriveWorkspace connected csrfToken="csrf" />);

  expect(await screen.findByRole("table")).toHaveAccessibleName(
    "Indexed Drive items",
  );
  expect(screen.getAllByRole("columnheader")).toHaveLength(5);
  fireEvent.click(await screen.findByRole("button", { name: "Projects" }));
  expect(
    await screen.findByRole("link", { name: "Phase 4 Brief.pdf" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Projects" })).toBeDisabled();

  const rootCrumb = screen
    .getAllByRole("button", { name: "My Drive" })
    .find((button) => !button.hasAttribute("aria-pressed"));
  expect(rootCrumb).toBeDefined();
  fireEvent.click(rootCrumb!);

  expect(
    await screen.findByRole("button", { name: "Projects" }),
  ).toBeInTheDocument();
  const itemRequests = fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.includes("/items?"));
  expect(itemRequests.some((url) => url.includes("parent_id=root"))).toBe(true);
  expect(itemRequests.some((url) => url.includes("parent_id=projects"))).toBe(
    true,
  );
});

test("ignores an older folder response after newer navigation", async () => {
  let resolveProjects: ((response: Response) => void) | undefined;
  const delayedProjects = new Promise<Response>((resolve) => {
    resolveProjects = resolve;
  });
  workspaceFetch((url, parsed) => {
    if (
      url.includes("/items?") &&
      parsed.searchParams.get("parent_id") === "root"
    ) {
      return jsonResponse({
        items: [projectFolder, archiveFolder],
        next_cursor: null,
        catalog: status,
      });
    }
    if (url.endsWith("/folders/projects")) return delayedProjects;
    if (url.endsWith("/folders/archive-folder")) {
      return jsonResponse(folderResponse(archiveFolder));
    }
    if (
      url.includes("/items?") &&
      parsed.searchParams.get("parent_id") === "archive-folder"
    ) {
      return jsonResponse({ items: [], next_cursor: null, catalog: status });
    }
    return undefined;
  });
  render(<DriveWorkspace connected csrfToken="csrf" />);

  fireEvent.click(await screen.findByRole("button", { name: "Projects" }));
  fireEvent.click(screen.getByRole("button", { name: "Archives" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Archives" })).toBeDisabled(),
  );

  await act(async () => {
    resolveProjects?.(jsonResponse(folderResponse(projectFolder)));
    await delayedProjects;
  });

  expect(screen.getByRole("button", { name: "Archives" })).toBeDisabled();
  expect(
    screen.queryByText("Unable to open that folder", { exact: false }),
  ).not.toBeInTheDocument();
});

test("sync completion reloads the latest browser mode", async () => {
  let resolveSync: ((response: Response) => void) | undefined;
  const delayedSync = new Promise<Response>((resolve) => {
    resolveSync = resolve;
  });
  const fetchMock = workspaceFetch((url, _parsed, init) => {
    if (url.endsWith("/catalog/sync") && init?.method === "POST") {
      return delayedSync;
    }
    return undefined;
  });
  render(<DriveWorkspace connected csrfToken="csrf" />);

  await screen.findByRole("button", { name: "Projects" });
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
  fireEvent.click(screen.getByRole("button", { name: "Starred" }));
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("view=starred"),
      ),
    ).toBe(true);
  });

  await act(async () => {
    resolveSync?.(
      jsonResponse({
        ...status,
        revision: 8,
        last_started_at: "2026-09-23T12:05:00Z",
      }),
    );
    await delayedSync;
  });

  await waitFor(() => {
    const itemRequests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes("/items?"));
    expect(itemRequests.at(-1)).toContain("view=starred");
    expect(itemRequests.at(-1)).not.toContain("parent_id=root");
  });
});

test("sync recovery returns to root when the current folder disappeared", async () => {
  let folderRequests = 0;
  const fetchMock = workspaceFetch((url, _parsed, init) => {
    if (url.endsWith("/folders/projects")) {
      folderRequests += 1;
      return folderRequests === 1
        ? jsonResponse(folderResponse(projectFolder))
        : jsonResponse({ detail: "Folder not found." }, 404);
    }
    if (url.endsWith("/catalog/sync") && init?.method === "POST") {
      return jsonResponse({
        ...status,
        revision: 8,
        last_started_at: "2026-09-23T12:05:00Z",
      });
    }
    return undefined;
  });
  render(<DriveWorkspace connected csrfToken="csrf" />);

  fireEvent.click(await screen.findByRole("button", { name: "Projects" }));
  expect(
    await screen.findByRole("link", { name: "Phase 4 Brief.pdf" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

  expect(
    await screen.findByText(
      /folder is no longer available.*Returned to My Drive/i,
    ),
  ).toBeInTheDocument();
  await waitFor(() => {
    const itemRequests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes("/items?"));
    expect(itemRequests.at(-1)).toContain("parent_id=root");
  });
});

test("disconnected workspace explains unavailable sections without auxiliary requests", async () => {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(jsonResponse({ ...status, state: "not_configured" }));

  render(<DriveWorkspace connected={false} csrfToken="csrf" />);

  expect(
    screen.getByText("Workspace shortcuts unavailable"),
  ).toBeInTheDocument();
  expect(screen.getByText("Storage insights unavailable")).toBeInTheDocument();
  expect(screen.getByText("Catalog activity unavailable")).toBeInTheDocument();
  expect(screen.queryByText(/No saved searches/)).not.toBeInTheDocument();
  expect(screen.queryByText(/No catalog activity/)).not.toBeInTheDocument();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(String(fetchMock.mock.calls[0][0])).toContain("/catalog/status");
});

test("renders separate quota and indexed insights with sync-observed activity", async () => {
  workspaceFetch();
  render(<DriveWorkspace connected csrfToken="csrf" />);

  expect(await screen.findByText("Google account quota")).toBeInTheDocument();
  expect(screen.getByText("Indexed known size")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Archive.zip" })).toHaveAttribute(
    "target",
    "_blank",
  );
  expect(screen.getByText("Catalog activity")).toBeInTheDocument();
  expect(screen.getByText("Phase 4 Brief.pdf")).toBeInTheDocument();
  expect(
    screen.getByText(/not a complete real-time audit log/i),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Catalog sync" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Incremental mode")).not.toBeInTheDocument();
});

test("creates a named saved search through the inline form with CSRF", async () => {
  const fetchMock = workspaceFetch();
  render(<DriveWorkspace connected csrfToken="csrf-token" />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Save current search" }),
  );
  fireEvent.change(screen.getByLabelText("Search name"), {
    target: { value: "Current projects" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save current" }));

  expect(await screen.findByText("Current projects")).toBeInTheDocument();
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/saved-searches") && init?.method === "POST",
    );
    expect(request?.[1]?.headers).toEqual(
      expect.objectContaining({ "X-CSRF-Token": "csrf-token" }),
    );
  });
});

test("serializes modified-before as exclusive next-day midnight", async () => {
  const fetchMock = workspaceFetch();
  render(<DriveWorkspace connected csrfToken="csrf" />);

  await screen.findByRole("button", { name: "Projects" });
  fireEvent.click(screen.getByText("Size and date"));
  const before = screen.getByLabelText("Modified before");
  fireEvent.change(before, { target: { value: "2026-09-23" } });
  expect(before).toHaveValue("2026-09-23");
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

  await waitFor(() => {
    const itemRequests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes("/items?"));
    expect(itemRequests.at(-1)).toContain(
      "modified_before=2026-09-24T00%3A00%3A00.000Z",
    );
  });
});

const archiveFolder: SearchResult = {
  ...projectFolder,
  id: "archive-folder",
  name: "Archives",
  starred: false,
  web_url: "https://drive.google.com/drive/folders/archive-folder",
};

type FetchOverride = (
  url: string,
  parsed: URL,
  init?: RequestInit,
) => Response | Promise<Response> | undefined;

function workspaceFetch(override?: FetchOverride) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      const parsed = new URL(url, "http://ark.test");
      const overridden = override?.(url, parsed, init);
      if (overridden !== undefined) return overridden;
      if (url.endsWith("/catalog/status")) return jsonResponse(status);
      if (url.includes("/items?")) {
        const parent = parsed.searchParams.get("parent_id");
        return jsonResponse({
          items: parent === "projects" ? [projectFile] : [projectFolder],
          next_cursor: null,
          catalog: status,
        });
      }
      if (url.endsWith("/folders/projects")) {
        return jsonResponse({
          id: "projects",
          name: "Projects",
          web_url: projectFolder.web_url,
          modified_at: projectFolder.modified_at,
          starred: true,
          breadcrumbs: [
            { id: "root", name: "My Drive", available: true },
            { id: "projects", name: "Projects", available: true },
          ],
          breadcrumbs_complete: true,
        });
      }
      if (url.endsWith("/saved-searches") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { name: string };
        return jsonResponse(
          {
            id: "saved-1",
            name: body.name,
            filters: {
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
            },
            created_at: "2026-09-23T12:00:00Z",
          },
          201,
        );
      }
      if (
        url.endsWith("/saved-searches") ||
        url.endsWith("/pinned-locations")
      ) {
        return jsonResponse({ items: [] });
      }
      if (url.endsWith("/insights")) {
        return jsonResponse({
          account_used_bytes: 5_000_000,
          account_total_bytes: 20_000_000,
          catalog_known_size_bytes: 3_000_000,
          catalog_unknown_size_count: 2,
          by_kind: [
            {
              kind: "document",
              item_count: 2,
              known_size_bytes: 10_000,
              unknown_size_count: 1,
            },
          ],
          largest_files: [
            {
              id: "archive",
              name: "Archive.zip",
              kind: "archive",
              size_bytes: 2_000_000,
              modified_at: "2025-01-01T00:00:00Z",
              web_url: "https://drive.google.com/open?id=archive",
            },
          ],
          stale_files: [],
          freshness_at: "2026-09-23T12:00:00Z",
        });
      }
      if (url.includes("/catalog/syncs?")) {
        return jsonResponse({
          items: [
            {
              id: "sync-1",
              mode: "incremental",
              status: "success",
              phase: "completed",
              processed_count: 3,
              total_count: 3,
              retryable: false,
              recovery: false,
              error: null,
              started_at: "2026-09-23T11:59:00Z",
              completed_at: "2026-09-23T12:00:00Z",
            },
          ],
        });
      }
      if (url.includes("/activity?")) {
        return jsonResponse({
          items: [
            {
              id: "activity-1",
              event_type: "modified",
              file_id: "brief",
              name: "Phase 4 Brief.pdf",
              kind: "document",
              summary: "Modified metadata observed for Phase 4 Brief.pdf.",
              observed_at: "2026-09-23T12:00:00Z",
            },
          ],
          next_cursor: null,
          scope: "sync_observed",
          message:
            "Activity reflects metadata observed during synchronization, not a complete real-time audit log.",
        });
      }
      return new Response(null, { status: 404 });
    });
}

function folderResponse(item: SearchResult) {
  return {
    id: item.id,
    name: item.name,
    web_url: item.web_url,
    modified_at: item.modified_at,
    starred: item.starred,
    breadcrumbs: [
      { id: "root", name: "My Drive", available: true },
      { id: item.id, name: item.name, available: true },
    ],
    breadcrumbs_complete: true,
  };
}

function jsonResponse(value: unknown, statusCode = 200): Response {
  return new Response(JSON.stringify(value), {
    status: statusCode,
    headers: { "Content-Type": "application/json" },
  });
}
