import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import AccountPage from "./AccountPage";
import App from "./App";
import type { AuthSession, LocalUser } from "./api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

const adminSession: AuthSession = {
  authenticated: true,
  username: "owner",
  role: "admin",
  csrf_token: "csrf",
};

const accountFixtures: LocalUser[] = [
  {
    id: "owner-id",
    username: "owner",
    role: "admin",
    active: true,
    pending: false,
  },
  {
    id: "alice-id",
    username: "alice",
    role: "member",
    active: true,
    pending: false,
  },
  {
    id: "admin-id",
    username: "other.admin",
    role: "admin",
    active: true,
    pending: false,
  },
  {
    id: "disabled-id",
    username: "disabled",
    role: "member",
    active: false,
    pending: false,
  },
  {
    id: "pending-id",
    username: "invited",
    role: "member",
    active: true,
    pending: true,
  },
];

function accountServer(
  override?: (
    url: string,
    init?: RequestInit,
  ) => Response | Promise<Response> | undefined,
) {
  let users = accountFixtures.map((user) => ({ ...user }));
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      const overridden = override?.(url, init);
      if (overridden) return overridden;
      if (url === "/api/auth/users" && !init?.method) return json(users);
      if (url === "/api/auth/users" && init?.method === "POST")
        return json({ token: "one-time-secret" });
      if (url.endsWith("/invite")) return json({ token: "replacement-secret" });
      const id = url.split("/").at(-1);
      if (init?.method === "PATCH") {
        const changes = JSON.parse(String(init.body)) as Partial<LocalUser>;
        users = users.map((user) =>
          user.id === id ? { ...user, ...changes } : user,
        );
        return json(users.find((user) => user.id === id)!);
      }
      if (init?.method === "DELETE") {
        users = users.filter((user) => user.id !== id);
        return new Response(null, { status: 204 });
      }
      throw new Error(`Unexpected account request: ${url}`);
    });
}

async function renderAdmin() {
  const result = render(
    <AccountPage
      session={adminSession}
      onUpdate={vi.fn()}
      onPasswordChanged={vi.fn()}
      usersOnly
    />,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Disable alice" })).toBeEnabled(),
  );
  return result;
}

function mutations(fetcher: ReturnType<typeof accountServer>) {
  return fetcher.mock.calls.filter(([, init]) => init?.method);
}

async function createInvitation() {
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "new.member" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
  await screen.findByRole("heading", { name: "One-time invitation code" });
  await waitFor(() =>
    expect(screen.queryByText("Loading accounts…")).not.toBeInTheDocument(),
  );
}

test.each([
  ["alice", "admin", "administrator", "gain", "an administrator"],
  ["other.admin", "member", "member", "lose", "a member"],
])(
  "role change for %s has focused, named confirmation before the mutation",
  async (name, role, roleLabel, consequence, outcome) => {
    const fetcher = accountServer();
    await renderAdmin();
    const trigger = screen.getByRole("button", {
      name: `Make ${role} for ${name}`,
    });
    fireEvent.click(trigger);
    const panel = screen.getByRole("region", {
      name: `Make ${name} ${role === "admin" ? "an" : "a"} ${roleLabel}?`,
    });
    expect(within(panel).getByRole("heading")).toHaveFocus();
    expect(panel).toHaveAccessibleDescription(
      expect.stringContaining(consequence),
    );
    expect(mutations(fetcher)).toHaveLength(0);
    fireEvent.click(within(panel).getByRole("button", { name: "Cancel" }));
    expect(trigger).toHaveFocus();
    expect(mutations(fetcher)).toHaveLength(0);
    fireEvent.click(trigger);
    fireEvent.click(
      screen.getByRole("button", { name: `Confirm make ${name} ${roleLabel}` }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      `${name} is now ${outcome}.`,
    );
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(mutations(fetcher)).toEqual([
      [
        expect.stringMatching(/\/api\/auth\/users\//),
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ role }),
          headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
        }),
      ],
    ]);
  },
);

test("disable is contextual and reversible; routine enabling runs immediately", async () => {
  const fetcher = accountServer();
  const confirm = vi.spyOn(window, "confirm");
  await renderAdmin();
  expect(screen.getByRole("button", { name: "Disable owner" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Delete owner" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Make member for owner" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Disable alice" }));
  const panel = screen.getByRole("region", { name: "Disable alice?" });
  expect(within(panel).getByRole("heading")).toHaveFocus();
  expect(panel).toHaveAccessibleDescription(
    expect.stringContaining("enable it again"),
  );
  expect(mutations(fetcher)).toHaveLength(0);
  fireEvent.click(
    within(panel).getByRole("button", { name: "Confirm disable alice" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Enable alice" })).toBeEnabled(),
  );
  expect(screen.getByRole("status")).toHaveTextContent("alice disabled.");
  fireEvent.click(screen.getByRole("button", { name: "Enable disabled" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Disable disabled" }),
    ).toBeEnabled(),
  );
  expect(
    screen.queryByRole("region", { name: /Enable disabled/ }),
  ).not.toBeInTheDocument();
  expect(confirm).not.toHaveBeenCalled();
  expect(mutations(fetcher).map(([, init]) => init?.body)).toEqual([
    JSON.stringify({ active: false }),
    JSON.stringify({ active: true }),
  ]);
});

test("a successful mutation survives failed refresh; retry only reloads the stale ledger", async () => {
  let reads = 0;
  const fetcher = accountServer((url, init) => {
    if (url === "/api/auth/users" && !init?.method && ++reads === 2)
      return new Response(JSON.stringify({ detail: "Ledger unavailable." }), {
        status: 503,
      });
  });
  await renderAdmin();
  fireEvent.click(screen.getByRole("button", { name: "Disable alice" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Confirm disable alice" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Account list may be out of date. Ledger unavailable.",
  );
  expect(screen.getByRole("status")).toHaveTextContent("alice disabled.");
  expect(screen.getByRole("button", { name: "Enable alice" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Retry loading accounts" }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: "Enable alice" })).toBeEnabled();
  expect(screen.getByRole("status")).toHaveTextContent("alice disabled.");
  expect(mutations(fetcher)).toHaveLength(1);
  expect(reads).toBe(3);
  expect(screen.getByRole("heading", { name: "Local accounts" })).toHaveFocus();
});

test("initial ledger failure has a retry and does not claim the account list is empty", async () => {
  let unavailable = true;
  accountServer((url, init) => {
    if (url === "/api/auth/users" && !init?.method && unavailable)
      return new Response(JSON.stringify({ detail: "Offline." }), {
        status: 503,
      });
  });
  render(
    <AccountPage
      session={adminSession}
      onUpdate={vi.fn()}
      onPasswordChanged={vi.fn()}
      usersOnly
    />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline.");
  expect(
    screen.queryByText("No local accounts are available."),
  ).not.toBeInTheDocument();
  unavailable = false;
  fireEvent.click(
    screen.getByRole("button", { name: "Retry loading accounts" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Disable alice" })).toBeEnabled(),
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("mutation failure stays in the confirmation context and permits retry", async () => {
  let attempts = 0;
  const fetcher = accountServer((url, init) => {
    if (
      url.endsWith("/alice-id") &&
      init?.method === "PATCH" &&
      ++attempts === 1
    )
      return new Response(
        JSON.stringify({ detail: "Account update refused." }),
        { status: 409 },
      );
  });
  await renderAdmin();
  fireEvent.click(screen.getByRole("button", { name: "Disable alice" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Confirm disable alice" }),
  );
  const error = await screen.findByRole("alert");
  expect(error).toHaveTextContent("Account update refused.");
  await waitFor(() => expect(error).toHaveFocus());
  expect(
    screen.getByRole("region", { name: "Disable alice?" }),
  ).toContainElement(error);
  expect(
    screen.queryByRole("button", { name: "Retry loading accounts" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Confirm disable alice" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Enable alice" })).toBeEnabled(),
  );
  expect(mutations(fetcher)).toHaveLength(2);
});

test("delete confirms next to its account, clears secrets on cancel, and restores focus", async () => {
  const fetcher = accountServer();
  await renderAdmin();
  const trigger = screen.getByRole("button", { name: "Delete alice" });
  fireEvent.click(trigger);
  const panel = screen.getByRole("region", { name: "Delete alice?" });
  expect(trigger.closest("li")).toContainElement(panel);
  expect(screen.getByLabelText("Type alice to confirm")).toHaveFocus();
  expect(panel).toHaveAccessibleDescription(
    expect.stringContaining("not inherited by a new account"),
  );
  expect(
    screen.getByRole("button", { name: "Delete account alice" }),
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Type alice to confirm"), {
    target: { value: "alice" },
  });
  fireEvent.change(screen.getByLabelText("Your current password"), {
    target: { value: "owner password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(trigger).toHaveFocus();
  expect(mutations(fetcher)).toHaveLength(0);
  fireEvent.click(trigger);
  expect(screen.getByLabelText("Type alice to confirm")).toHaveValue("");
  expect(screen.getByLabelText("Your current password")).toHaveValue("");
});

test("delete blocks cancellation while submitting and restores focus to the ledger after removal", async () => {
  let finish!: (response: Response) => void;
  let deleted = false;
  const fetcher = accountServer((url, init) => {
    if (url.endsWith("/alice-id") && init?.method === "DELETE")
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    if (url === "/api/auth/users" && !init?.method && deleted)
      return json(accountFixtures.filter((user) => user.username !== "alice"));
  });
  await renderAdmin();
  fireEvent.click(screen.getByRole("button", { name: "Delete alice" }));
  fireEvent.change(screen.getByLabelText("Type alice to confirm"), {
    target: { value: "wrong" },
  });
  fireEvent.change(screen.getByLabelText("Your current password"), {
    target: { value: "owner password" },
  });
  expect(
    screen.getByRole("button", { name: "Delete account alice" }),
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Type alice to confirm"), {
    target: { value: "alice" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Delete account alice" }));
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.getByLabelText("Your current password")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(
    screen.getByRole("region", { name: "Delete alice?" }),
  ).toBeInTheDocument();
  deleted = true;
  await act(async () => finish(new Response(null, { status: 204 })));
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: "Local accounts" }),
    ).toHaveFocus(),
  );
  expect(
    screen.queryByRole("button", { name: "Delete alice" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    "alice deleted. Local files remain on the host.",
  );
  expect(mutations(fetcher)).toEqual([
    [
      "/api/auth/users/alice-id",
      expect.objectContaining({
        method: "DELETE",
        body: JSON.stringify({
          confirm_username: "alice",
          current_password: "owner password",
        }),
        headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
      }),
    ],
  ]);
});

test("reissue explains invalidation before issuing and protects the new code from replacement", async () => {
  const fetcher = accountServer();
  await renderAdmin();
  fireEvent.click(screen.getByRole("button", { name: "New code for invited" }));
  const panel = screen.getByRole("region", {
    name: "Issue a new invitation code for invited?",
  });
  expect(within(panel).getByRole("heading")).toHaveFocus();
  expect(panel).toHaveAccessibleDescription(
    expect.stringContaining("old invitation code will stop working"),
  );
  expect(mutations(fetcher)).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(
    screen.getByRole("button", { name: "New code for invited" }),
  ).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "New code for invited" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Issue new code for invited" }),
  );
  expect(await screen.findByText("replacement-secret")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "One-time invitation code" }),
  ).toHaveFocus();
  await waitFor(() =>
    expect(screen.queryByText("Loading accounts…")).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "old code no longer works",
  );
  expect(
    screen.getByRole("button", { name: "New code for invited" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Create invitation" }),
  ).toBeDisabled();
  expect(mutations(fetcher)).toEqual([
    [
      "/api/auth/users/pending-id/invite",
      expect.objectContaining({ method: "POST" }),
    ],
  ]);
});

test("invitation Copy reports success, requires acknowledgment to dismiss, and keeps the token transient", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  accountServer();
  const page = await renderAdmin();
  await createInvitation();
  expect(
    screen.queryByText(/storage assignments lose access/),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Dismiss code" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Copy invitation code" }));
  expect(
    await screen.findByText(
      "Invitation code copied. Save and share it privately.",
    ),
  ).toHaveAttribute("role", "status");
  expect(writeText).toHaveBeenCalledWith("one-time-secret");
  expect(screen.getByRole("button", { name: "Dismiss code" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I have saved this code/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Dismiss code" }));
  expect(screen.queryByText("one-time-secret")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Create invitation" }),
  ).toHaveFocus();
  page.unmount();
  await renderAdmin();
  expect(
    screen.queryByRole("heading", { name: "One-time invitation code" }),
  ).not.toBeInTheDocument();
});

test("failed clipboard access leaves the code readable with manual recovery", async () => {
  const writeText = vi.fn().mockRejectedValue(new Error("Clipboard denied"));
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  accountServer();
  await renderAdmin();
  await createInvitation();
  fireEvent.click(screen.getByRole("button", { name: "Copy invitation code" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Select and copy it manually",
  );
  expect(screen.getByText("one-time-secret")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Copy invitation code" }),
  ).toBeEnabled();
  expect(screen.getByRole("button", { name: "Dismiss code" })).toBeDisabled();
});

test("unacknowledged invitation guards navigation and unload; acknowledgment releases the guard", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  accountServer();
  await renderAdmin();
  await createInvitation();
  const navigation = document.createElement("button");
  navigation.setAttribute("data-discard-changes", "");
  document.body.append(navigation);
  try {
    const leaving = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
    });
    navigation.dispatchEvent(leaving);
    expect(leaving.defaultPrevented).toBe(true);
    expect(confirm).toHaveBeenCalledOnce();
    expect(confirm.mock.calls[0][0]).not.toContain("one-time-secret");
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    fireEvent.click(
      screen.getByRole("checkbox", { name: /I have saved this code/ }),
    );
    const acknowledged = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
    });
    navigation.dispatchEvent(acknowledged);
    expect(acknowledged.defaultPrevented).toBe(false);
    expect(confirm).toHaveBeenCalledOnce();
    const cleanUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanUnload);
    expect(cleanUnload.defaultPrevented).toBe(false);
  } finally {
    navigation.remove();
  }
});

test("invitation success and one-time token survive a failed ledger refresh", async () => {
  let reads = 0;
  const fetcher = accountServer((url, init) => {
    if (url === "/api/auth/users" && !init?.method && ++reads === 2)
      return new Response(JSON.stringify({ detail: "Refresh unavailable." }), {
        status: 503,
      });
  });
  await renderAdmin();
  await createInvitation();
  expect(screen.getByRole("status")).toHaveTextContent("Invitation created.");
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Account list may be out of date.",
  );
  expect(screen.getByText("one-time-secret")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Retry loading accounts" }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
  );
  expect(screen.getByText("one-time-secret")).toBeInTheDocument();
  expect(mutations(fetcher)).toHaveLength(1);
});

function json(value: object) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

test("first-run setup requires the local bootstrap code and password confirmation", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url) => {
      if (url === "/api/auth/session")
        return json({ authenticated: false, setup_required: true });
      if (url === "/api/auth/setup")
        return json({
          authenticated: true,
          username: "owner",
          csrf_token: "csrf",
          role: "admin",
        });
      return json({});
    });
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Set up Ark Cloud" }),
  ).toBeInTheDocument();
  expect(screen.getByText("./scripts/ark bootstrap")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "owner" },
  });
  fireEvent.change(screen.getByLabelText("Setup code"), {
    target: { value: "example-setup-code" },
  });
  fireEvent.change(screen.getByLabelText("New password"), {
    target: { value: "a long password" },
  });
  fireEvent.change(screen.getByLabelText("Confirm password"), {
    target: { value: "different password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create administrator" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Passwords do not match",
  );
  expect(fetcher).not.toHaveBeenCalledWith(
    "/api/auth/setup",
    expect.anything(),
  );
  fireEvent.change(screen.getByLabelText("Confirm password"), {
    target: { value: "a long password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create administrator" }));
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      "/api/auth/setup",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});

test("account changes use CSRF and password change signs the user out", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url) => {
      if (url === "/api/auth/account/username")
        return json({
          authenticated: true,
          username: "new.name",
          role: "member",
          csrf_token: "csrf",
        });
      if (url === "/api/auth/account/password")
        return new Response(null, { status: 204 });
      return json([]);
    });
  const onUpdate = vi.fn();
  const onPasswordChanged = vi.fn();
  render(
    <AccountPage
      session={{
        authenticated: true,
        username: "old.name",
        role: "member",
        csrf_token: "csrf",
      }}
      onUpdate={onUpdate}
      onPasswordChanged={onPasswordChanged}
    />,
  );
  expect(
    screen.getByText(/Changing your password signs out every device/),
  ).toHaveTextContent(
    "Your account is stored on this Ark Cloud instance. Your files stay in their server storage locations when you update your login.",
  );
  fireEvent.change(screen.getByLabelText("New username"), {
    target: { value: "new.name" },
  });
  fireEvent.change(screen.getAllByLabelText("Current password")[0], {
    target: { value: "old password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save username" }));
  await waitFor(() =>
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ username: "new.name" }),
    ),
  );
  expect(fetcher).toHaveBeenCalledWith(
    "/api/auth/account/username",
    expect.objectContaining({
      headers: expect.objectContaining({ "X-CSRF-Token": "csrf" }),
    }),
  );
  fireEvent.change(screen.getAllByLabelText("Current password")[1], {
    target: { value: "old password" },
  });
  fireEvent.change(screen.getByLabelText("New password"), {
    target: { value: "new long password" },
  });
  fireEvent.change(screen.getByLabelText("Confirm new password"), {
    target: { value: "new long password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Change password" }));
  await waitFor(() => expect(onPasswordChanged).toHaveBeenCalled());
});
