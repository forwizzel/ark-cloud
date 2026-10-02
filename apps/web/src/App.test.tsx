import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
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
  window.localStorage.removeItem("ark-cloud-theme");
  window.localStorage.removeItem("ark-cloud-contrast");
});

test("offers appearance controls before signing in", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    jsonResponse({ authenticated: false, username: null, csrf_token: null }),
  );

  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Sign in" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("switch", { name: "High contrast" }));
  expect(document.documentElement).toHaveAttribute("data-contrast", "more");
  expect(
    screen.getByRole("switch", { name: "Light mode" }),
  ).toBeInTheDocument();
});

test("signing in starts on Dashboard instead of the previous page", async () => {
  window.history.replaceState({}, "", "/#drive-workspace");
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/auth/session") {
      return jsonResponse({
        authenticated: false,
        username: null,
        csrf_token: null,
      });
    }
    if (url === "/api/auth/login") {
      return jsonResponse({
        authenticated: true,
        username: "ark",
        csrf_token: "csrf",
      });
    }
    if (url === "/api/dashboard") return jsonResponse(dashboard);
    return new Response(null, { status: 404 });
  });

  render(<App />);
  await screen.findByRole("heading", { name: "Sign in" });
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "ark" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(
    await screen.findByRole("heading", { name: "Dashboard", level: 1 }),
  ).toBeInTheDocument();
  expect(window.location.hash).toBe("");
  expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("restoring a session preserves the requested page", async () => {
  window.history.replaceState({}, "", "/#drive-workspace");
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (String(input) === "/api/auth/session") {
      return jsonResponse({
        authenticated: true,
        username: "ark",
        csrf_token: "csrf",
      });
    }
    if (String(input) === "/api/dashboard") return jsonResponse(dashboard);
    return new Response(null, { status: 404 });
  });

  render(<App />);

  expect(
    await screen.findByRole("heading", { name: "Drive Workspace", level: 1 }),
  ).toBeInTheDocument();
  expect(window.location.hash).toBe("#drive-workspace");
});

test("administration storage deep links survive session restore and hash navigation", async () => {
  window.history.replaceState({}, "", "/#administration/storage/settings");
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path === "/api/auth/session")
      return jsonResponse({
        authenticated: true,
        username: "ark",
        role: "admin",
        csrf_token: "csrf",
      });
    if (path === "/api/dashboard") return jsonResponse(dashboard);
    if (path === "/api/admin/storage")
      return jsonResponse({
        configuration_error: null,
        manager: {
          enrolled: true,
          online: true,
          approved_paths: [],
          managed_area: "/host/locations",
        },
        setup: {
          default_path: "~/Ark-Files",
          repository_path: null,
          job: null,
        },
        roots: [],
        jobs: [],
        users: [],
        upload_max_bytes: 1024,
        upload_limit_source: "environment",
      });
    return new Response(null, { status: 404 });
  });
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Storage settings" }),
  ).toBeInTheDocument();
  expect(window.location.hash).toBe("#administration/storage/settings");
  window.location.hash = "administration/storage";
  fireEvent(window, new HashChangeEvent("hashchange"));
  expect(
    await screen.findByRole("heading", { name: "Storage locations" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Storage settings" }),
  ).not.toBeInTheDocument();
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
  expect(
    screen.getByRole("heading", { name: "Google Drive" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("Not configured")).toHaveLength(4);
  expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute(
    "href",
    "#overview",
  );
  expect(screen.getByRole("link", { name: "Drive Workspace" })).toHaveAttribute(
    "href",
    "#drive-workspace",
  );
  expect(
    screen.getByRole("link", { name: "System Information" }),
  ).toHaveAttribute("href", "#system-information");
  expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: /Open System Information/ }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(/Metrics are the API runtime's view/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: "Light mode" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: "High contrast" }),
  ).toBeInTheDocument();
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

  const drivePanel = (
    await screen.findByRole("heading", { name: "Google Drive" })
  ).closest("section");
  expect(drivePanel).not.toBeNull();
  expect(within(drivePanel!).queryByText("Healthy")).not.toBeInTheDocument();
  expect(drivePanel!.querySelector(".drive-panel-body")).toContainElement(
    screen.getByRole("link", { name: "Open Drive workspace" }),
  );
  fireEvent.click(screen.getByRole("link", { name: /Drive Workspace/ }));
  expect(
    await screen.findByRole("heading", { name: "Drive Workspace", level: 1 }),
  ).toBeInTheDocument();
  expect(document.getElementById("drive-workspace")).toBeNull();
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
  expect(
    screen.getByText("Location", { selector: ".mobile-label" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Modified", { selector: ".mobile-label" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Size", { selector: ".mobile-label" }),
  ).toBeInTheDocument();
  await waitFor(() => expect(window.location.hash).toBe("#drive-workspace"));
});

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
