import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

test("administrator sign-in preserves the Tailscale destination and sends session CSRF", async () => {
  window.history.replaceState({}, "", "/#administration/tailscale");
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/auth/session")
        return jsonResponse({ authenticated: false });
      if (url === "/api/auth/login")
        return jsonResponse({
          authenticated: true,
          username: "owner",
          role: "admin",
          csrf_token: "admin-csrf",
        });
      if (url === "/api/dashboard") return jsonResponse(dashboard);
      if (url === "/api/admin/tailscale")
        return jsonResponse({
          configured: false,
          source: "none",
          integration_state: "not_configured",
          integration_message: null,
          desired_enabled: false,
          revision: 0,
          state: "disconnected",
          message: "Not connected.",
          serve_url: null,
          approval_url: null,
          dns_name: null,
          node_id: null,
          controller_online: true,
        });
      return new Response(null, { status: 404 });
    });
  render(<App />);
  await screen.findByRole("heading", { name: "Sign in" });
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "owner" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByLabelText("Tailscale API key");
  expect(window.location.hash).toBe("#administration/tailscale");
  expect(screen.getByRole("tab", { name: "Tailscale" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("tabpanel")).toHaveAttribute(
    "aria-labelledby",
    "administration-tab-tailscale",
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/admin/tailscale",
    expect.objectContaining({ headers: { "X-CSRF-Token": "admin-csrf" } }),
  );
});

test("members cannot open the Tailscale administrator page or issue management requests", async () => {
  window.history.replaceState({}, "", "/#administration/tailscale");
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      if (String(input) === "/api/auth/session")
        return jsonResponse({
          authenticated: true,
          username: "member",
          role: "member",
          csrf_token: "csrf",
        });
      if (String(input) === "/api/dashboard") return jsonResponse(dashboard);
      return new Response(null, { status: 404 });
    });
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Administrator access is required",
  );
  expect(screen.queryByLabelText("Tailscale API key")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Administration" }),
  ).not.toBeInTheDocument();
  expect(
    fetch.mock.calls.some(([url]) =>
      String(url).startsWith("/api/admin/tailscale"),
    ),
  ).toBe(false);
});

test.each(["admin", "member"])(
  "dashboard Tailscale configure link is admin-only (%s)",
  async (role) => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input) === "/api/auth/session")
        return jsonResponse({
          authenticated: true,
          username: "ark",
          role,
          csrf_token: "csrf",
        });
      if (String(input) === "/api/dashboard") return jsonResponse(dashboard);
      return new Response(null, { status: 404 });
    });
    render(<App />);
    await screen.findByRole("heading", { name: "Devices" });
    const link = screen.queryByRole("link", { name: "Configure Tailscale" });
    if (role === "admin")
      expect(link).toHaveAttribute("href", "#administration/tailscale");
    else expect(link).not.toBeInTheDocument();
  },
);

test("signing in starts on Dashboard instead of the previous page", async () => {
  window.history.replaceState({}, "", "/#account");
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
  window.history.replaceState({}, "", "/#account");
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
    await screen.findByRole("heading", { name: "Account", level: 1 }),
  ).toBeInTheDocument();
  expect(window.location.hash).toBe("#account");
});

test("retired workspace bookmarks show the dashboard without integration requests", async () => {
  window.history.replaceState({}, "", "/#drive-workspace");
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      if (String(input) === "/api/auth/session")
        return jsonResponse({
          authenticated: true,
          username: "ark",
          csrf_token: "csrf",
        });
      if (String(input) === "/api/dashboard") return jsonResponse(dashboard);
      if (String(input) === "/api/storage/roots")
        return jsonResponse({
          roots: [],
          message: "No storage locations connected.",
        });
      return new Response(null, { status: 404 });
    });
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Dashboard", level: 1 }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Drive Workspace" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Google Drive" }),
  ).not.toBeInTheDocument();
  expect(
    fetch.mock.calls.some(([url]) => String(url).includes("google-drive")),
  ).toBe(false);
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
      new Response(
        JSON.stringify({
          roots: [],
          message: "No storage locations connected.",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

  render(<App />);

  expect(
    await screen.findByRole("heading", { name: "Ark" }),
  ).toBeInTheDocument();
  expect(screen.getByText("4d 13h")).toBeInTheDocument();
  expect(screen.getByText("12%")).toBeInTheDocument();
  expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Local storage" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("Not configured")).toHaveLength(3);
  expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute(
    "href",
    "#overview",
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
      new Response(
        JSON.stringify({
          roots: [],
          message: "No storage locations connected.",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

  render(<App />);

  expect(await screen.findByText("Laptop")).toBeInTheDocument();
  expect(screen.getByText("100.64.0.2")).toBeInTheDocument();
  expect(screen.getByText("1 / 1 online")).toBeInTheDocument();
});

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
