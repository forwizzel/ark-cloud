import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import App from "./App";
import type { Dashboard } from "./api";

const dashboard: Dashboard = {
  platform: {
    status: "healthy",
    service: "ark-cloud-api",
    database: "connected",
  },
  system: {
    hostname: "Ark",
    os: "Fedora Linux",
    kernel: "6.18.7",
    uptime_seconds: 392_400,
    cpu_percent: 12,
    cpu_count: 8,
    memory: {
      total_bytes: 34_359_738_368,
      used_bytes: 8_589_934_592,
      available_bytes: 25_769_803_776,
      percent: 25,
    },
    storage: {
      total_bytes: 2_199_023_255_552,
      used_bytes: 861_140_942_848,
      available_bytes: 1_337_882_312_704,
      percent: 39.2,
    },
    storage_path: "/",
    scope: "api-runtime-view",
    collected_at: "2026-09-13T12:00:00Z",
  },
  tailscale: {
    state: "not_configured",
    device_count: 0,
    online_count: 0,
    devices: [],
    message: "Add a Tailscale access token to enable device status.",
    collected_at: "2026-09-13T12:00:00Z",
  },
  google_drive: {
    state: "not_configured",
    account_email: null,
    account_name: null,
    used_bytes: null,
    total_bytes: null,
    available_bytes: null,
    percent: null,
    message: "Connect a Google Drive account to enable Drive status.",
    checked_at: "2026-09-13T12:00:00Z",
    web_url: "https://drive.google.com/",
  },
  integrations: [
    {
      id: "system",
      name: "Ark system",
      state: "healthy",
      message: "System metrics are available.",
      checked_at: "2026-09-13T12:00:00Z",
    },
    {
      id: "tailscale",
      name: "Tailscale",
      state: "not_configured",
      message: "Add a Tailscale access token to enable device status.",
      checked_at: "2026-09-13T12:00:00Z",
    },
  ],
  generated_at: "2026-09-13T12:00:00Z",
};

const catalogStatus = {
  state: "ready" as const,
  item_count: 2,
  last_synced_at: "2026-09-13T12:00:00Z",
  revision: 3,
  last_started_at: "2026-09-13T11:59:00Z",
  mode: "incremental" as const,
  phase: "completed" as const,
  processed_count: 2,
  total_count: 2,
  retryable: false,
  recovery: false,
  message: "The Drive catalog is current.",
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

test("renders normalized system and integration health", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          authenticated: true,
          username: "ark",
          csrf_token: "csrf",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(dashboard), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(catalogStatus), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

  render(<App />);

  expect(
    await screen.findByRole("heading", { name: "Ark" }),
  ).toBeInTheDocument();
  expect(screen.getByText("4d 13h")).toBeInTheDocument();
  expect(screen.getByText("12%")).toBeInTheDocument();
  expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
  expect(screen.getByText("Primary storage")).toBeInTheDocument();
  expect(screen.getAllByText("Not configured")).toHaveLength(5);
});

test("renders normalized Tailscale devices", async () => {
  const withDevice: Dashboard = {
    ...dashboard,
    tailscale: {
      state: "healthy",
      device_count: 1,
      online_count: 1,
      message: "Device status is current.",
      collected_at: "2026-09-13T12:00:00Z",
      devices: [
        {
          id: "device-1",
          hostname: "Laptop",
          os: "windows",
          addresses: ["100.64.0.2"],
          online: true,
          last_seen: "2026-09-13T11:59:00Z",
        },
      ],
    },
  };
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          authenticated: true,
          username: "ark",
          csrf_token: "csrf",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(withDevice), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(catalogStatus), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

  render(<App />);

  expect(await screen.findByText("Laptop")).toBeInTheDocument();
  expect(screen.getByText("100.64.0.2")).toBeInTheDocument();
  expect(screen.getByText("1 / 1 online")).toBeInTheDocument();
});

test("searches the Drive catalog and links to Drive", async () => {
  const connected: Dashboard = {
    ...dashboard,
    google_drive: {
      ...dashboard.google_drive,
      state: "healthy",
      account_name: "Ark User",
      message: "Google Drive status is current.",
    },
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/auth/session") {
      return jsonResponse({
        authenticated: true,
        username: "ark",
        csrf_token: "csrf",
      });
    }
    if (url === "/api/dashboard") return jsonResponse(connected);
    if (url.endsWith("/catalog/status")) return jsonResponse(catalogStatus);
    if (url.includes("/items?")) {
      const query = new URL(url, "http://ark.test").searchParams.get("q");
      return jsonResponse({
        items:
          query === "tax return"
            ? [
                {
                  source: "google_drive",
                  id: "file-1",
                  name: "Tax Return.pdf",
                  mime_type: "application/pdf",
                  size_bytes: 1200,
                  kind: "document",
                  created_at: "2025-01-01T12:00:00Z",
                  modified_at: "2026-09-12T12:00:00Z",
                  starred: true,
                  ownership: "owned_by_me",
                  parent: { id: "root", name: "My Drive", available: true },
                  status_labels: ["recent"],
                  web_url: "https://drive.google.com/open?id=file-1",
                },
              ]
            : [],
        next_cursor: null,
        catalog: catalogStatus,
      });
    }
    if (url.endsWith("/saved-searches") || url.endsWith("/pinned-locations")) {
      return jsonResponse({ items: [] });
    }
    if (url.endsWith("/insights")) {
      return jsonResponse({
        account_used_bytes: null,
        account_total_bytes: null,
        catalog_known_size_bytes: 0,
        catalog_unknown_size_count: 0,
        by_kind: [],
        largest_files: [],
        stale_files: [],
        freshness_at: null,
      });
    }
    if (url.includes("/catalog/syncs?")) return jsonResponse({ items: [] });
    if (url.includes("/activity?")) {
      return jsonResponse({
        items: [],
        next_cursor: null,
        scope: "sync_observed",
        message: "Activity is sync-observed metadata.",
      });
    }
    return new Response(null, { status: 404 });
  });

  render(<App />);

  fireEvent.click(await screen.findByRole("link", { name: /Drive Workspace/ }));
  const input = await screen.findByRole("searchbox", {
    name: "Search indexed names",
  });
  fireEvent.change(input, { target: { value: "tax return" } });
  fireEvent.submit(input.closest("form")!);

  const result = await screen.findByRole("link", { name: "Tax Return.pdf" });
  expect(result).toHaveAttribute(
    "href",
    "https://drive.google.com/open?id=file-1",
  );
  expect(result).toHaveAttribute("rel", "noreferrer");
  await waitFor(() => expect(window.location.hash).toBe("#drive-workspace"));
});

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
