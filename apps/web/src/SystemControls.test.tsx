import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import SystemControls from "./SystemControls";

const policy = {
  terminal: true,
  processes: true,
  power: true,
  shell: "/bin/bash",
  account: "owner",
  services: [],
};
const service = {
  unit: "backup.service",
  scope: "user",
  state: "active",
  actions: ["restart"],
};
const process = {
  pid: 12,
  started_at: 1,
  owner: "owner",
  name: "worker",
  percent: 5,
  memory_bytes: 100,
  state: "sleeping",
};
const job = {
  id: "job-1",
  state: "unknown",
  message: "No acknowledgement yet",
  payload: {
    action: "service",
    unit: "backup.service",
    scope: "user",
    operation: "restart",
  },
};
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status });
}
function inventory(path: unknown) {
  return json({
    items: String(path).includes("/processes") ? [process] : [service],
  });
}
function renderControls() {
  return render(
    <SystemControls csrf="csrf" policy={policy} live hostname="ark-host" />,
  );
}
async function confirmRestart() {
  await act(async () =>
    fireEvent.click(
      screen.getByRole("button", {
        name: "Restart backup.service (user service)",
      }),
    ),
  );
  const dialog = screen.getByRole("dialog");
  expect(dialog).toHaveAccessibleDescription(
    /changes the user service on ark-host/,
  );
  await act(async () =>
    fireEvent.click(
      screen.getByRole("button", {
        name: "Restart backup.service",
      }),
    ),
  );
}
beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {
      configurable: true,
      value: function (this: HTMLDialogElement) {
        this.setAttribute("open", "");
      },
    },
    close: {
      configurable: true,
      value: function (this: HTMLDialogElement) {
        this.removeAttribute("open");
      },
    },
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test("inventories distinguish loading and empty, and process actions name their target", async () => {
  let finish!: (value: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (path) =>
    String(path).includes("/services")
      ? new Promise<Response>((resolve) => {
          finish = resolve;
        })
      : json({ items: [process] }),
  );
  renderControls();
  expect(screen.getByText("Loading selected services…")).toBeInTheDocument();
  expect(screen.queryByText(/No services selected/)).not.toBeInTheDocument();
  expect(
    await screen.findByRole("button", { name: "Terminate worker (PID 12)" }),
  ).toBeEnabled();
  await act(async () => finish(json({ items: [] })));
  expect(screen.getByText(/No services selected/)).toBeInTheDocument();
});

test("service inventory failure does not discard successful process readings", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (path) =>
    String(path).includes("/services")
      ? json({ detail: "Services offline" }, 503)
      : json({ items: [process] }),
  );
  renderControls();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Services offline",
  );
  expect(await screen.findByText("worker")).toBeInTheDocument();
  expect(screen.queryByText(/No services selected/)).not.toBeInTheDocument();
});

test("uncertain submission retains its idempotency key and inventory refresh cannot clear the error", async () => {
  vi.useFakeTimers();
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (path, options) =>
      options?.method === "POST"
        ? json({ detail: "Response lost" }, 503)
        : inventory(path),
    );
  renderControls();
  await act(async () => {
    await Promise.resolve();
  });
  await confirmRestart();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "submission outcome is unresolved",
  );
  expect(screen.getByRole("button", { name: "Restart host" })).toBeDisabled();
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(screen.getByRole("alert")).toHaveTextContent("Response lost");
  fetch.mockImplementation(async (path, options) =>
    options?.method === "POST" ? json(job) : inventory(path),
  );
  fireEvent.click(screen.getByRole("button", { name: "Retry submission" }));
  await act(async () => {
    await Promise.resolve();
  });
  const submissions = fetch.mock.calls.filter(
    ([, options]) => options?.method === "POST",
  );
  expect(submissions).toHaveLength(2);
  expect(JSON.parse(String(submissions[0][1]?.body))).toEqual(
    JSON.parse(String(submissions[1][1]?.body)),
  );
  expect(screen.getByRole("status")).toHaveTextContent("Outcome unresolved");
});

test("unknown jobs keep actions paused through polling errors until a definitive result", async () => {
  vi.useFakeTimers();
  let outcome = "error";
  vi.spyOn(globalThis, "fetch").mockImplementation(async (path, options) => {
    if (options?.method === "POST") return json(job);
    if (String(path).includes("/jobs/"))
      return outcome === "error"
        ? json({ detail: "Status unavailable" }, 503)
        : json({ ...job, state: outcome });
    return inventory(path);
  });
  renderControls();
  await act(async () => {
    await Promise.resolve();
  });
  await confirmRestart();
  expect(screen.getByRole("status")).toHaveTextContent("unknown");
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Operation status: Status unavailable",
  );
  expect(
    screen.getByRole("button", { name: "Terminate worker (PID 12)" }),
  ).toBeDisabled();
  outcome = "unknown";
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Restart host" })).toBeDisabled();
  outcome = "succeeded";
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(screen.getByRole("button", { name: "Restart host" })).toBeEnabled();
});

test("a rejected request remains visible without trapping unrelated controls", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (path, options) =>
    options?.method === "POST"
      ? json(
          { detail: "Service permission changed. Review configuration." },
          403,
        )
      : inventory(path),
  );
  renderControls();
  await screen.findByRole("button", {
    name: "Restart backup.service (user service)",
  });
  await confirmRestart();
  expect(screen.getByRole("alert")).toHaveTextContent("permission changed");
  expect(
    screen.queryByRole("button", { name: "Retry submission" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Restart host" })).toBeEnabled();
});

test("unknown outcome requires explicit review before another operation", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (path, options) =>
    options?.method === "POST" ? json(job) : inventory(path),
  );
  renderControls();
  await screen.findByRole("button", {
    name: "Restart backup.service (user service)",
  });
  await confirmRestart();
  expect(screen.getByRole("button", { name: "Restart host" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I have checked the host/ }),
  );
  expect(screen.getByRole("button", { name: "Restart host" })).toBeEnabled();
});
