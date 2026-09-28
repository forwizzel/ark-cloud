import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import AccountPage from "./AccountPage";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
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
