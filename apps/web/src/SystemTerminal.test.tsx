import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import SystemTerminal from "./SystemTerminal";

const emulator = vi.hoisted(() => ({
  open: vi.fn(),
  blur: vi.fn(),
  key: null as ((event: KeyboardEvent) => boolean) | null,
}));
vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    options = {};
    cols = 80;
    rows = 24;
    open = emulator.open;
    blur = emulator.blur;
    attachCustomKeyEventHandler(handler: (event: KeyboardEvent) => boolean) {
      emulator.key = handler;
    }
    loadAddon() {}
    onData() {
      return { dispose() {} };
    }
    write() {}
    writeln() {}
    dispose() {}
  },
}));
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit() {}
    dispose() {}
  },
}));

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  send = vi.fn();
  constructor() {
    Socket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}
const policy = {
  terminal: true,
  processes: true,
  power: false,
  shell: "/bin/bash",
  account: "owner",
  services: [],
};
const grant = { id: "session-1", grant: "token", reconnect_seconds: 12 };
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status });
}
function renderTerminal() {
  return render(
    <SystemTerminal csrf="csrf" policy={policy} live hidden={false} />,
  );
}
async function connect() {
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() => expect(Socket.instances).toHaveLength(1));
  act(() => Socket.instances[0].open());
  expect(screen.getByRole("status")).toHaveTextContent("Connected");
}
beforeEach(() => {
  Socket.instances = [];
  emulator.key = null;
  emulator.open.mockReset().mockImplementation((target: HTMLElement) => {
    const input = document.createElement("textarea");
    input.setAttribute("aria-label", "Shell input");
    target.appendChild(input);
  });
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
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
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("transient attach failure preserves the session for retry and cleanup", async () => {
  let attaches = 0;
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (path) => {
      if (String(path).endsWith("/attach") && ++attaches === 1)
        return json({ detail: "Host temporarily offline" }, 503);
      return json(grant);
    });
  const view = renderTerminal();
  await connect();
  act(() => Socket.instances[0].close());
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Host temporarily offline",
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Connection interrupted",
  );
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(Socket.instances).toHaveLength(2));
  expect(
    fetch.mock.calls.filter(([path]) => String(path).endsWith("/attach")),
  ).toHaveLength(2);
  expect(
    fetch.mock.calls.filter(
      ([path]) => String(path) === "/api/admin/system/terminal/sessions",
    ),
  ).toHaveLength(1);
  view.unmount();
  expect(
    fetch.mock.calls.some(
      ([path]) =>
        String(path) === "/api/admin/system/terminal/sessions/session-1/end",
    ),
  ).toBe(true);
});

test("initialization failure leaves connecting and allows reconnect or end", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(grant));
  emulator.open.mockImplementationOnce(() => {
    throw new Error("Emulator unavailable");
  });
  renderTerminal();
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "could not initialize",
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Connection interrupted",
  );
  expect(screen.getByRole("button", { name: "Reconnect" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "End session" })).toBeEnabled();
});

test("a confirmed ended session clears reconnect state and permits a new session", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (path) =>
    String(path).endsWith("/attach")
      ? json({ detail: "This terminal session has ended." }, 404)
      : json(grant),
  );
  renderTerminal();
  await connect();
  act(() => Socket.instances[0].close());
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "session has ended",
  );
  expect(screen.getByRole("status")).toHaveTextContent("Ended");
  expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "End session" })).toBeDisabled();
});

test("reconnect countdown uses the grant and does not reset on an unsuccessful retry", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (path) =>
    String(path).endsWith("/attach")
      ? json({ detail: "Still offline" }, 503)
      : json(grant),
  );
  renderTerminal();
  await connect();
  vi.useFakeTimers();
  act(() => Socket.instances[0].close());
  expect(screen.getByText(/Reconnect within 12 seconds/)).toBeInTheDocument();
  await act(async () => vi.advanceTimersByTimeAsync(4000));
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.getByText(/Reconnect within 8 seconds/)).toBeInTheDocument();
  await act(async () => vi.advanceTimersByTimeAsync(8000));
  expect(screen.getByRole("button", { name: "Reconnect" })).toBeDisabled();
  expect(screen.getByText(/Reconnect window expired/)).toBeInTheDocument();
});

test("End is busy and prevents duplicate end or connect requests", async () => {
  let finish!: (value: Response) => void;
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (path) =>
      String(path).endsWith("/end")
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : json(grant),
    );
  renderTerminal();
  await connect();
  fireEvent.click(screen.getByRole("button", { name: "End session" }));
  expect(
    screen.getByRole("button", { name: "Ending session…" }),
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "Reconnect" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Ending session…" }));
  expect(
    fetch.mock.calls.filter(([path]) => String(path).endsWith("/end")),
  ).toHaveLength(1);
  await act(async () => finish(json({ state: "ended" })));
  expect(screen.getByRole("status")).toHaveTextContent("Ended");
  expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
});

test("expanded terminal uses a native modal, preserves Escape to shell, and provides keyboard and touch exits", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(grant));
  renderTerminal();
  await connect();
  const input = screen.getByLabelText("Shell input");
  fireEvent.click(screen.getByRole("button", { name: "Expand" }));
  const dialog = screen.getByRole("dialog", { name: "Expanded terminal" });
  expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalledOnce();
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(screen.getByLabelText("Shell input")).toBe(input);
  input.focus();
  expect(emulator.key!(new KeyboardEvent("keydown", { key: "Escape" }))).toBe(
    true,
  );
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
  act(() => {
    expect(
      emulator.key!(
        new KeyboardEvent("keydown", {
          key: "Escape",
          ctrlKey: true,
          shiftKey: true,
        }),
      ),
    ).toBe(false);
  });
  expect(screen.getByRole("button", { name: "End session" })).toHaveFocus();
  input.focus();
  fireEvent.click(screen.getByRole("button", { name: "Exit terminal input" }));
  expect(emulator.blur).toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "End session" })).toHaveFocus();
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  expect(screen.getByRole("button", { name: "Expand" })).toHaveFocus();
  expect(dialog).not.toHaveAttribute("aria-modal");
});

test("leaving Overview closes the overlay while retaining the connected shell", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(grant));
  const view = renderTerminal();
  await connect();
  fireEvent.click(screen.getByRole("button", { name: "Expand" }));
  const dialog = screen.getByRole("dialog", { name: "Expanded terminal" });
  view.rerender(<SystemTerminal csrf="csrf" policy={policy} live hidden />);
  expect(dialog).not.toHaveAttribute("open");
  expect(Socket.instances[0].readyState).toBe(Socket.OPEN);
  view.rerender(
    <SystemTerminal csrf="csrf" policy={policy} live hidden={false} />,
  );
  expect(screen.getByRole("button", { name: "Expand" })).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Connected");
  expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalledOnce();
});
