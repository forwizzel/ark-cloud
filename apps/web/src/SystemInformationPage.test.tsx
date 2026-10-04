import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";
import SystemInformationPage from "./SystemInformationPage";
import type { HostSnapshot } from "./systemApi";

const usage = {
  total_bytes: 1000,
  used_bytes: 400,
  available_bytes: 600,
  percent: 40,
};
const snapshot: HostSnapshot = {
  scope: "host",
  boot_id: "boot",
  collected_at: "2026-10-02T12:00:00Z",
  identity: {
    hostname: "ark-host",
    os: "Fedora Linux",
    kernel: "6-test",
    architecture: "x86_64",
    boot_time: "2026-10-01T12:00:00Z",
    uptime_seconds: 86400,
  },
  compute: {
    model: "Test CPU",
    physical_cores: 2,
    logical_cores: 4,
    sockets: 1,
    percent: 12,
    per_core: [10, 20],
    frequency_mhz: 2400,
    load_average: [0.1, 0.2, 0.3],
    gpus: ["Test GPU"],
  },
  memory: {
    usage,
    swap: usage,
    cached_bytes: 10,
    buffers_bytes: 5,
    swap_in_bytes: 0,
    swap_out_bytes: 0,
  },
  temperatures: [
    {
      id: "cpu-0",
      group: "cpu",
      label: "CPU package",
      source_name: "coretemp",
      celsius: 53,
      high: 90,
      critical: 100,
    },
  ],
  mounts: [
    {
      id: "/",
      path: "/",
      device: "/dev/test",
      filesystem: "ext4",
      options: "rw",
      usage,
    },
  ],
  omitted_mounts: ["/proc"],
  disk_io: [],
  warnings: [],
};
const policy = {
  terminal: true,
  power: false,
  processes: true,
  shell: "/bin/bash",
  account: "host-owner",
  services: [],
};
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function mockHost() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path === "/api/auth/session")
      return json({
        authenticated: true,
        username: "ark",
        role: "admin",
        csrf_token: "csrf",
      });
    if (path === "/api/dashboard")
      return json({ detail: "Dashboard unavailable" }, 503);
    if (path === "/api/system/overview" || path === "/api/system/vitals")
      return json({
        state: "connected",
        scope: "host",
        collected_at: snapshot.collected_at,
        snapshot,
        history: [],
      });
    if (path === "/api/admin/system/status")
      return json({ state: "connected", policy });
    if (path === "/api/admin/system/services")
      return json({
        items: [
          {
            unit: "backup.service",
            scope: "user",
            state: "active",
            actions: ["restart"],
          },
        ],
      });
    if (path.startsWith("/api/admin/system/processes"))
      return json({
        items: [
          {
            pid: 12,
            started_at: 1,
            owner: "host-owner",
            name: "test-process",
            percent: 5,
            memory_bytes: 100,
            state: "sleeping",
          },
        ],
      });
    return json({}, 404);
  });
}
beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {
      configurable: true,
      value: vi.fn(function (this: HTMLDialogElement) {
        this.setAttribute("open", "");
      }),
    },
    close: {
      configurable: true,
      value: vi.fn(function (this: HTMLDialogElement) {
        this.removeAttribute("open");
      }),
    },
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

test("legacy route opens System, identity leads, Vitals moves resource panels, and terminal stays last", async () => {
  window.history.replaceState({}, "", "/#system-information");
  mockHost();
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "System", level: 1 }),
  ).toBeInTheDocument();
  expect(await screen.findByText("ark-host")).toBeInTheDocument();
  expect(
    screen
      .getByRole("heading", { name: "Identity" })
      .compareDocumentPosition(
        screen.getByRole("heading", { name: "Compute" }),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    screen.queryByRole("heading", { name: "Temperatures" }),
  ).not.toBeInTheDocument();
  expect(
    screen
      .getByRole("heading", { name: "Host controls" })
      .compareDocumentPosition(
        screen.getByRole("heading", { name: "Terminal" }),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "Vitals" }));
  expect(
    await screen.findByRole("heading", { name: "Temperatures" }),
  ).toBeInTheDocument();
  expect(screen.getByText("53 °C")).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Terminal" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Vitals" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  fireEvent.keyDown(screen.getByRole("tab", { name: "Vitals" }), {
    key: "Home",
  });
  expect(
    await screen.findByRole("heading", { name: "Identity" }),
  ).toBeInTheDocument();
});

test("read-only view never requests administrator data or creates a shell", async () => {
  const fetch = mockHost();
  render(<SystemInformationPage />);
  expect(await screen.findByText("ark-host")).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Terminal" }),
  ).not.toBeInTheDocument();
  expect(
    fetch.mock.calls
      .map(([url]) => String(url))
      .some((url) => url.includes("/admin/")),
  ).toBe(false);
});

test("unconfigured System directs administrators to Administration without enrollment scripts", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (String(input) === "/api/system/overview")
      return json({
        state: "not_enrolled",
        scope: "host",
        collected_at: null,
        snapshot: null,
        history: [],
      });
    if (String(input) === "/api/admin/system/status")
      return json({ state: "not_enrolled", policy: null });
    return json({ detail: "Runtime readings unavailable" }, 503);
  });
  render(<SystemInformationPage isAdmin csrfToken="csrf" />);
  expect(
    await screen.findByRole("link", {
      name: "Configure System in Administration",
    }),
  ).toHaveAttribute("href", "#administration/system");
  expect(
    screen.queryByRole("heading", { name: "Connect this host" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText(/scripts\/ark system enroll/),
  ).not.toBeInTheDocument();
});

test.each(["#system", "#system/vitals", "#system-information"])(
  "sign-in preserves the requested System route %s",
  async (route) => {
    window.history.replaceState({}, "", `/${route}`);
    const fetchMock = mockHost();
    const implementation = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === "/api/auth/session")
        return json({ authenticated: false });
      if (String(input) === "/api/auth/login")
        return json({
          authenticated: true,
          username: "ark",
          role: "member",
          csrf_token: "csrf",
        });
      return implementation(input, init);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "Sign in" });
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "ark" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "test-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByRole("heading", { name: "System", level: 1 }),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe(route);
    expect(
      await screen.findByRole("heading", {
        name: route === "#system/vitals" ? "Temperatures" : "Identity",
      }),
    ).toBeInTheDocument();
  },
);

test("failed refresh retains readable host data and retry recovers", async () => {
  let calls = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
    calls++;
    return calls === 2
      ? json({ detail: "Connection failed" }, 503)
      : json({
          state: "connected",
          scope: "host",
          collected_at: snapshot.collected_at,
          snapshot,
          history: [],
        });
  });
  render(<SystemInformationPage />);
  expect(await screen.findByText("ark-host")).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Showing values collected",
  );
  expect(screen.getByText("ark-host")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
  );
});

test("administrator controls require confirmation and honor missing power capability", async () => {
  mockHost();
  const showModal = vi.mocked(HTMLDialogElement.prototype.showModal);
  render(<SystemInformationPage isAdmin csrfToken="csrf" />);
  expect(await screen.findByText("backup.service")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Restart host" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Restart backup.service (user service)",
    }),
  );
  expect(showModal).toHaveBeenCalled();
  expect(
    screen.getByRole("heading", { name: "Restart backup.service?" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
});

test("policy failure leaves host telemetry connected and readable while controls are paused", async () => {
  const fetch = mockHost();
  const implementation = fetch.getMockImplementation()!;
  fetch.mockImplementation(async (path, options) =>
    String(path) === "/api/admin/system/status"
      ? json({ detail: "Policy unavailable" }, 503)
      : implementation(path, options),
  );
  render(<SystemInformationPage isAdmin csrfToken="csrf" />);
  await screen.findByText("ark-host");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Host permissions: Policy unavailable",
  );
  expect(screen.getByText("Host connected")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
  expect(screen.getByRole("tabpanel")).toHaveAttribute("tabindex", "0");
});

test("runtime fallback errors do not obscure an unenrolled host or successful policy reads", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (path) => {
    if (String(path) === "/api/system/overview")
      return json({
        state: "not_enrolled",
        scope: "host",
        collected_at: null,
        snapshot: null,
        history: [],
      });
    if (String(path) === "/api/admin/system/status")
      return json({ state: "not_enrolled", policy });
    return json({ detail: "Runtime unavailable" }, 503);
  });
  render(<SystemInformationPage isAdmin csrfToken="csrf" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API runtime: Runtime unavailable",
  );
  expect(screen.getByText("Host agent not enrolled")).toBeInTheDocument();
  expect(screen.queryByText(/Host permissions:/)).not.toBeInTheDocument();
});

test("telemetry failure reports stale status without preventing independent policy refresh", async () => {
  let failed = false;
  let policyCalls = 0;
  const fetch = mockHost();
  const implementation = fetch.getMockImplementation()!;
  fetch.mockImplementation(async (path, options) => {
    if (String(path) === "/api/admin/system/status") policyCalls++;
    if (failed && String(path) === "/api/system/overview")
      return json({ detail: "Telemetry unavailable" }, 503);
    return implementation(path, options);
  });
  render(<SystemInformationPage isAdmin csrfToken="csrf" />);
  await screen.findByText("ark-host");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled(),
  );
  failed = true;
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(
    await screen.findByText("Host status unavailable · readings are stale"),
  ).toBeInTheDocument();
  expect(screen.getByText("ark-host")).toBeInTheDocument();
  expect(policyCalls).toBe(2);
  expect(screen.queryByText("Host connected")).not.toBeInTheDocument();
});
