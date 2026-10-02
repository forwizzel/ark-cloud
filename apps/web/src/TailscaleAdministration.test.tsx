import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import TailscaleAdministration from "./TailscaleAdministration";
import type { TailscaleStatus } from "./tailscaleAdminApi";

const initial: TailscaleStatus = {
  configured: false,
  source: "none",
  integration_state: "not_configured",
  integration_message: null,
  desired_enabled: false,
  revision: 0,
  state: "disconnected",
  message: "Add an API key to connect.",
  serve_url: null,
  approval_url: null,
  dns_name: null,
  node_id: null,
  controller_online: true,
};
const connected: TailscaleStatus = {
  ...initial,
  configured: true,
  source: "ui",
  integration_state: "available",
  desired_enabled: true,
  state: "connected",
  revision: 1,
  message: "Private access is ready.",
  serve_url: "https://ark.example.ts.net/",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("connect sends the transient password with CSRF and clears it after success", async () => {
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json(initial))
    .mockResolvedValueOnce(json({ ...connected, state: "connecting" }));
  render(<TailscaleAdministration csrfToken="csrf" />);
  const input = await screen.findByLabelText("Tailscale API key");
  expect(input).toHaveAttribute("type", "password");
  fireEvent.change(input, { target: { value: "secret-test-key" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect Tailscale" }));
  await waitFor(() => expect(input).toHaveValue(""));
  expect(fetch).toHaveBeenLastCalledWith(
    "/api/admin/tailscale/connect",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ api_key: "secret-test-key" }),
      headers: { "X-CSRF-Token": "csrf", "Content-Type": "application/json" },
    }),
  );
  expect(screen.getByText("Connecting", { exact: true })).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("secret-test-key");
});

test("failed replacement keeps input and existing state without echoing upstream secrets", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json(connected))
    .mockResolvedValueOnce(json({ detail: "Rejected secret-test-key" }, 422));
  render(<TailscaleAdministration csrfToken="csrf" />);
  await screen.findByText("Connected", { exact: true });
  const input = screen.getByLabelText("New Tailscale API key");
  fireEvent.change(input, { target: { value: "secret-test-key" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Replace key and connect" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "existing saved key is retained",
  );
  expect(input).toHaveValue("secret-test-key");
  expect(screen.getByText("Connected", { exact: true })).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("Rejected secret-test-key");
});

test("poll failure marks stale state, recovers, and aborts on leaving", async () => {
  vi.useFakeTimers();
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json(connected))
    .mockRejectedValueOnce(new Error("secret upstream error"))
    .mockResolvedValueOnce(json(connected));
  const view = render(<TailscaleAdministration csrfToken="csrf" />);
  await act(async () => {});
  expect(screen.getByText("Connected", { exact: true })).toBeInTheDocument();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(screen.getByRole("alert")).toHaveTextContent("last known state");
  expect(screen.getByText("Status unknown")).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("secret upstream error");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  const signal = fetch.mock.calls[2][1]?.signal;
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await vi.advanceTimersByTimeAsync(6000);
  expect(fetch).toHaveBeenCalledTimes(3);
});

test.each([401, 403])(
  "authorization failure %s stops polling and disables mutations",
  async (code) => {
    vi.useFakeTimers();
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(initial))
      .mockResolvedValueOnce(json({}, code));
    render(<TailscaleAdministration csrfToken="csrf" />);
    await act(async () => {});
    fireEvent.change(screen.getByLabelText("Tailscale API key"), {
      target: { value: "test-key" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Sign in again");
    expect(
      screen.getByRole("button", { name: "Connect Tailscale" }),
    ).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(fetch).toHaveBeenCalledTimes(2);
  },
);

test("unsaved input guards tab navigation and clearing removes the guard", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(json(initial));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const navigate = vi.fn();
  render(
    <>
      <TailscaleAdministration csrfToken="csrf" />
      <button role="tab" onClick={navigate}>
        Storage
      </button>
    </>,
  );
  await screen.findByText("Disconnected", { exact: true });
  fireEvent.change(screen.getByLabelText("Tailscale API key"), {
    target: { value: "test-key" },
  });
  fireEvent.click(screen.getByRole("tab"));
  expect(confirm).toHaveBeenCalledWith(
    "Discard your unsaved changes and leave this page?",
  );
  expect(navigate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Clear input" }));
  fireEvent.click(screen.getByRole("tab"));
  expect(navigate).toHaveBeenCalledOnce();
});

test.each(["Disable private access", "Disconnect Tailscale"])(
  "%s confirms remote session loss before a bodyless mutation",
  async (name) => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(json(connected));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<TailscaleAdministration csrfToken="csrf" />);
    const button = await screen.findByRole("button", { name });
    fireEvent.click(button);
    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining("including this session"),
    );
    expect(fetch).toHaveBeenCalledOnce();
    confirm.mockReturnValue(true);
    fireEvent.click(button);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch.mock.calls[1][0]).toBe(
      `/api/admin/tailscale/${name === "Disable private access" ? "disable" : "disconnect"}`,
    );
    expect(fetch.mock.calls[1][1]).not.toHaveProperty("body");
  },
);

test("environment inventory is distinct from remote state and only HTTPS approval links are exposed", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    json({
      ...initial,
      configured: true,
      source: "environment",
      integration_state: "available",
      state: "approval_required",
      approval_url: "javascript:alert(1)",
    }),
  );
  const view = render(<TailscaleAdministration csrfToken="csrf" />);
  await screen.findByText("HTTPS approval required");
  expect(screen.getByText(/environment-provided key/)).toBeInTheDocument();
  expect(screen.getByText("Available", { exact: true })).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: /Approve HTTPS/ }),
  ).not.toBeInTheDocument();
  view.unmount();
  fetch.mockResolvedValue(
    json({
      ...connected,
      state: "approval_required",
      approval_url: "https://login.tailscale.com/admin/dns",
    }),
  );
  render(<TailscaleAdministration csrfToken="csrf" />);
  expect(
    await screen.findByRole("link", { name: /Approve HTTPS/ }),
  ).toHaveAttribute("href", "https://login.tailscale.com/admin/dns");
});

test("private URL can be copied and opened", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(json(connected));
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  render(<TailscaleAdministration csrfToken="csrf" />);
  expect(
    await screen.findByRole("link", { name: "Open private URL" }),
  ).toHaveAttribute("href", connected.serve_url);
  fireEvent.click(screen.getByRole("button", { name: "Copy private URL" }));
  expect(await screen.findByText("Private URL copied.")).toBeInTheDocument();
  expect(writeText).toHaveBeenCalledWith(connected.serve_url);
  vi.unstubAllGlobals();
});

test.each([
  ["Enable private access", "enable"],
  ["Test saved API key", "test"],
])(
  "%s uses the saved configuration without resending a key",
  async (name, endpoint) => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        json({ ...connected, desired_enabled: false, state: "disabled" }),
      )
      .mockResolvedValueOnce(json(connected));
    render(<TailscaleAdministration csrfToken="csrf" />);
    fireEvent.click(await screen.findByRole("button", { name }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch.mock.calls[1]).toEqual([
      `/api/admin/tailscale/${endpoint}`,
      expect.objectContaining({
        method: "POST",
        headers: { "X-CSRF-Token": "csrf" },
      }),
    ]);
    expect(fetch.mock.calls[1][1]).not.toHaveProperty("body");
  },
);

test("leaving during an in-flight request aborts it and prevents further polling", async () => {
  vi.useFakeTimers();
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(
    (_url, options) =>
      new Promise((_resolve, reject) => {
        options?.signal?.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        );
      }),
  );
  const view = render(<TailscaleAdministration csrfToken="csrf" />);
  expect(screen.getByText("Checking Tailscale…")).toBeInTheDocument();
  const signal = fetch.mock.calls[0][1]?.signal;
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(9000);
  });
  expect(fetch).toHaveBeenCalledOnce();
});
