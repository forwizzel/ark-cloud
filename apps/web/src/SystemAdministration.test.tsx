import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import App from "./App";
import SystemAdministration, {
  type SystemAdministrationStatus,
} from "./SystemAdministration";

const configuration = {
  terminal: true,
  processes: true,
  power: false,
  shell: "",
  services: [],
};
const status: SystemAdministrationStatus = {
  host: { state: "not_enrolled", policy: null, collected_at: null },
  manager: {
    online: true,
    inventory: {
      supported: true,
      account: "owner",
      default_shell: "/bin/bash",
      shells: ["/bin/bash", "/bin/zsh"],
      power: false,
      message: "",
      services: [
        {
          unit: "backup.service",
          scope: "user",
          actions: ["start", "stop", "restart"],
        },
      ],
    },
  },
  configuration,
  jobs: [],
};
function json(value: unknown, code = 200) {
  return new Response(JSON.stringify(value), {
    status: code,
    headers: { "Content-Type": "application/json" },
  });
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

test("Administration has a directly navigable System tab with UI setup and no script instructions", async () => {
  window.history.replaceState({}, "", "/#administration/system");
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url) => {
      if (String(url) === "/api/auth/session")
        return json({
          authenticated: true,
          username: "ark",
          role: "admin",
          csrf_token: "csrf",
        });
      if (String(url) === "/api/admin/system/configuration")
        return json(status);
      return json({ detail: "Unavailable" }, 503);
    });
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "System configuration" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "System" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("tabpanel")).toHaveAttribute(
    "aria-labelledby",
    "administration-tab-system",
  );
  expect(
    (await screen.findAllByRole("button", { name: "Connect System" }))[0],
  ).toBeEnabled();
  expect(screen.queryByText(/scripts\/ark/)).not.toBeInTheDocument();
  expect(
    fetch.mock.calls.some(([url]) => String(url).includes("/admin/storage")),
  ).toBe(false);
});

test("Connect submits selected installed shell and service actions with CSRF and shows applying state", async () => {
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (_url, options) => {
      if (options?.method === "POST")
        return json({
          id: "job",
          state: "queued",
          message: "Preparing System connection.",
          payload: { action: "connect" },
        });
      return json(status);
    });
  render(<SystemAdministration csrfToken="csrf" />);
  await screen.findByText("owner");
  fireEvent.change(screen.getByLabelText("Installed shell"), {
    target: { value: "/bin/zsh" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /backup.service/ }));
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Stop backup.service (user service)",
    }),
  );
  fireEvent.click(screen.getAllByRole("button", { name: "Connect System" })[0]);
  expect(
    await screen.findByText("Preparing System connection."),
  ).toBeInTheDocument();
  expect(
    screen.getAllByRole("button", { name: "Applying…" })[0],
  ).toBeDisabled();
  const [, options] = fetch.mock.calls.find(
    ([, options]) => options?.method === "POST",
  )!;
  expect(options?.headers).toMatchObject({ "X-CSRF-Token": "csrf" });
  expect(JSON.parse(String(options?.body))).toMatchObject({
    action: "connect",
    configuration: {
      shell: "/bin/zsh",
      services: [
        {
          unit: "backup.service",
          scope: "user",
          actions: ["start", "restart"],
        },
      ],
    },
  });
  expect(
    screen.getByRole("checkbox", { name: /Restart and shutdown/ }),
  ).toBeDisabled();
});

test("offline host management disables connection and retryable setup errors remain visible", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    json({
      ...status,
      manager: { ...status.manager, online: false },
      jobs: [
        {
          id: "failed",
          state: "failed",
          message: "Setup failed. Retry the connection.",
          payload: { action: "connect" },
        },
      ],
    }),
  );
  render(<SystemAdministration csrfToken="csrf" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Setup failed");
  expect(
    screen.getAllByRole("button", { name: "Retry connection" })[0],
  ).toBeDisabled();
  expect(screen.getByText(/retries automatically/)).toBeInTheDocument();
});

test("disconnect preserves saved configuration and requires deliberate confirmation", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (_url, options) =>
      options?.method === "POST"
        ? json({
            id: "disconnect",
            state: "queued",
            message: "Disconnecting System.",
            payload: { action: "disconnect" },
          })
        : json({ ...status, host: { ...status.host, state: "connected" } }),
    );
  render(<SystemAdministration csrfToken="csrf" />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Disconnect System" }),
  );
  await screen.findByText("Disconnecting System.");
  expect(confirm).toHaveBeenCalled();
  const [, options] = fetch.mock.calls.find(
    ([, options]) => options?.method === "POST",
  )!;
  expect(JSON.parse(String(options?.body))).toMatchObject({
    action: "disconnect",
  });
  expect(JSON.parse(String(options?.body)).configuration).toBeUndefined();
});

test("polling does not replace unsaved access settings", async () => {
  vi.useFakeTimers();
  try {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(status));
    render(<SystemAdministration csrfToken="csrf" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Terminal access/ }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(
      screen.getByRole("checkbox", { name: /Terminal access/ }),
    ).not.toBeChecked();
  } finally {
    vi.useRealTimers();
  }
});

test("connected apply has consistent labels, adjacent interruption warnings, and confirmation preserves edits when cancelled", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (_path, options) =>
      options?.method === "POST"
        ? json({
            id: "apply",
            state: "queued",
            message: "Applying settings.",
            payload: { action: "connect" },
          })
        : json({ ...status, host: { ...status.host, state: "connected" } }),
    );
  render(<SystemAdministration csrfToken="csrf" />);
  await screen.findByText("owner");
  fireEvent.click(screen.getByRole("checkbox", { name: /Terminal access/ }));
  const buttons = screen.getAllByRole("button", {
    name: "Apply settings and reconnect",
  });
  expect(buttons).toHaveLength(2);
  expect(
    screen.getAllByText(/briefly interrupts host readings and controls/),
  ).toHaveLength(2);
  fireEvent.click(buttons[1]);
  expect(confirm).toHaveBeenCalledWith(
    expect.stringContaining("ends all active terminal sessions"),
  );
  expect(
    fetch.mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(false);
  expect(
    screen.getByRole("checkbox", { name: /Terminal access/ }),
  ).not.toBeChecked();
  confirm.mockReturnValue(true);
  fireEvent.click(buttons[1]);
  await screen.findByText("Applying settings.");
  const submission = fetch.mock.calls.find(
    ([, options]) => options?.method === "POST",
  )!;
  expect(JSON.parse(String(submission[1]?.body))).toMatchObject({
    action: "connect",
    configuration: { terminal: false },
  });
});
