import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import StorageConnection from "./StorageConnection";
import * as api from "./storageAdminApi";

vi.mock("./storageAdminApi", async (original) => ({
  ...(await original<typeof api>()),
  storageRequest: vi.fn(),
  submitStorageOperation: vi.fn(),
}));
const inventory: api.StorageAdministration = {
  configuration_error: null,
  manager: {
    enrolled: true,
    online: true,
    last_seen_at: null,
    approved_paths: [],
    managed_area: "/approved",
  },
  setup: { default_path: "/approved", repository_path: null, job: null },
  roots: [],
  jobs: [],
  upload_max_bytes: 1024,
  upload_limit_source: "environment",
  users: [
    {
      id: "alice",
      username: "alice",
      active: true,
      pending: false,
      current: true,
    },
  ],
};
const job: api.StorageJob = {
  id: "browse",
  action: "browse",
  payload: {},
  state: "completed",
  message: "Done",
  result: { path: "/approved", folders: [] },
  created_at: "2026-10-01T12:00:00Z",
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.submitStorageOperation).mockResolvedValue(job);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

test("connection grants reconcile added, disabled and removed accounts without losing edits", async () => {
  const view = render(
    <StorageConnection data={inventory} csrfToken="csrf" onQueued={vi.fn()} />,
  );
  fireEvent.change(screen.getByLabelText("Access for alice"), {
    target: { value: "read" },
  });
  const bob = { id: "bob", username: "bob", active: true, pending: false };
  view.rerender(
    <StorageConnection
      data={{ ...inventory, users: [...inventory.users, bob] }}
      csrfToken="csrf"
      onQueued={vi.fn()}
    />,
  );
  expect(screen.getByLabelText("Access for alice")).toHaveValue("read");
  fireEvent.change(screen.getByLabelText("Access for bob"), {
    target: { value: "write" },
  });
  view.rerender(
    <StorageConnection
      data={{
        ...inventory,
        users: [{ ...inventory.users[0], active: false }, bob],
      }}
      csrfToken="csrf"
      onQueued={vi.fn()}
    />,
  );
  expect(screen.queryByLabelText("Access for alice")).not.toBeInTheDocument();
  view.rerender(
    <StorageConnection
      data={{ ...inventory, users: [...inventory.users, bob] }}
      csrfToken="csrf"
      onQueued={vi.fn()}
    />,
  );
  expect(screen.getByLabelText("Access for alice")).toHaveValue("write");
  expect(screen.getByLabelText("Access for bob")).toHaveValue("write");
  view.rerender(
    <StorageConnection
      data={{ ...inventory, users: [bob] }}
      csrfToken="csrf"
      onQueued={vi.fn()}
    />,
  );
  expect(screen.queryByLabelText("Access for alice")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Location name"), {
    target: { value: "Shared" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Connect location" }));
  await waitFor(() =>
    expect(api.submitStorageOperation).toHaveBeenCalledWith(
      expect.objectContaining({ grants: [{ user_id: "bob", level: "write" }] }),
      "csrf",
    ),
  );
});

test("browse progress and empty result do not claim a connection is in progress", async () => {
  let resolve: (value: api.StorageJob) => void = () => {};
  vi.mocked(api.submitStorageOperation).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  render(
    <StorageConnection data={inventory} csrfToken="csrf" onQueued={vi.fn()} />,
  );
  fireEvent.change(screen.getByLabelText("Folder"), {
    target: { value: "existing" },
  });
  expect(screen.getByText(/No approved folders listed/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approved areas" }));
  expect(screen.getByText("Loading server folders…")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Connect location" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Connecting…" }),
  ).not.toBeInTheDocument();
  await act(async () => {
    resolve(job);
  });
  expect(
    screen.getByText(/No subfolders in this directory/),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Existing server folder")).toHaveValue(
    "/approved",
  );
  expect(
    screen.getByRole("button", { name: "Connect location" }),
  ).toBeEnabled();
});

test("browse failure supplies a working retry and retains the selected path", async () => {
  vi.mocked(api.submitStorageOperation)
    .mockRejectedValueOnce(new api.StorageRequestError("Offline", null))
    .mockResolvedValueOnce(job);
  render(
    <StorageConnection data={inventory} csrfToken="csrf" onQueued={vi.fn()} />,
  );
  fireEvent.change(screen.getByLabelText("Folder"), {
    target: { value: "existing" },
  });
  fireEvent.change(screen.getByLabelText("Existing server folder"), {
    target: { value: "/approved" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Browse folder" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "OfflineTry Approved areas or Browse folder again.",
  );
  expect(screen.getByLabelText("Existing server folder")).toHaveValue(
    "/approved",
  );
  fireEvent.click(screen.getByRole("button", { name: "Browse folder" }));
  await screen.findByText(/No subfolders in this directory/);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
