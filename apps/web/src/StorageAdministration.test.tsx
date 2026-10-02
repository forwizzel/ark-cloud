import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import StorageAdministration from "./StorageAdministration";
import * as api from "./storageAdminApi";

vi.mock("./storageAdminApi", async (original) => ({
  ...(await original<typeof api>()),
  fetchStorageAdministration: vi.fn(),
  submitStorageOperation: vi.fn(),
  storageRequest: vi.fn(),
}));
afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
});
const inventory: api.StorageAdministration = {
  configuration_error: null,
  manager: {
    enrolled: true,
    online: true,
    last_seen_at: null,
    approved_paths: ["/host/area"],
    managed_area: "/host/area",
  },
  setup: { default_path: "~/Ark-Files", repository_path: null, job: null },
  roots: [],
  jobs: [],
  upload_max_bytes: 1024 ** 3,
  upload_limit_source: "environment",
  users: [
    {
      id: "account-id",
      username: "alice",
      active: true,
      pending: false,
      current: true,
    },
  ],
};
const root: api.ManagedLocation = {
  id: "second",
  label: "Second Directory",
  source: "/host/area/second",
  kind: "shared",
  owner: null,
  username: null,
  read_only: false,
  selinux: "preserve",
  state: "unavailable",
  message: "Runtime write access needs repair",
  registration: "00000000-0000-0000-0000-000000000001",
  blocked: true,
  access_count: 0,
  connection_state: "needs_repair",
};
const job: api.StorageJob = {
  id: "job",
  action: "add",
  payload: { root_id: "second" },
  state: "queued",
  message: "Preparing access",
  result: {},
  created_at: "2026-10-01T12:00:00Z",
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue(inventory);
  vi.mocked(api.storageRequest).mockResolvedValue({ message: "Saved" });
  vi.mocked(api.submitStorageOperation).mockResolvedValue(job);
});

test("overview is a landing page rather than a stack of storage panels", async () => {
  render(<StorageAdministration csrfToken="csrf" route="#administration" />);
  expect(
    await screen.findByRole("heading", { name: "Administration overview" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Storage/ })).toHaveAttribute(
    "href",
    "#administration/storage",
  );
  expect(
    screen.queryByRole("heading", { name: "Maximum file size" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Storage locations" }),
  ).not.toBeInTheDocument();
});

test("locations page only shows the ledger and task links", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    roots: [root],
  });
  render(
    <StorageAdministration csrfToken="csrf" route="#administration/storage" />,
  );
  expect(
    await screen.findByRole("heading", { name: "Storage locations" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Needs repair")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Manage access" })).toHaveAttribute(
    "href",
    "#administration/storage/locations/second/access",
  );
  expect(screen.queryByText("Maximum file size")).not.toBeInTheDocument();
  expect(
    screen.queryByText("Current issues & progress"),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/copy.*command/i)).not.toBeInTheDocument();
});

test("existing-folder connection submits once with automatic preparation", async () => {
  render(
    <StorageAdministration
      csrfToken="csrf"
      route="#administration/storage/new"
    />,
  );
  await screen.findByRole("heading", { name: "Add location" });
  fireEvent.change(screen.getByLabelText("Location name"), {
    target: { value: "Second Directory" },
  });
  fireEvent.change(screen.getByLabelText("Folder"), {
    target: { value: "existing" },
  });
  fireEvent.change(screen.getByLabelText("Existing server folder"), {
    target: { value: "/host/area/second" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() =>
    expect(api.submitStorageOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "add",
        path: "/host/area/second",
        shared: true,
        automatic_access: true,
        confirmed: true,
        grants: [{ user_id: "account-id", level: "write" }],
      }),
      "csrf",
    ),
  );
  expect(api.submitStorageOperation).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("Review folder")).not.toBeInTheDocument();
  expect(
    screen.queryByText("Grant API access to this folder and future content"),
  ).not.toBeInTheDocument();
});

test("failed location repairs the existing registration from its own page", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    roots: [root],
  });
  render(
    <StorageAdministration
      csrfToken="csrf"
      route="#administration/storage/locations/second/overview"
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Repair connection" }),
  );
  await waitFor(() =>
    expect(api.submitStorageOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "repair",
        root_id: "second",
        registration: root.registration,
        automatic_access: true,
      }),
      "csrf",
    ),
  );
  expect(
    screen.queryByRole("heading", { name: "Add location" }),
  ).not.toBeInTheDocument();
});

test("settings is a separate view and saves without restarting", async () => {
  render(
    <StorageAdministration
      csrfToken="csrf"
      route="#administration/storage/settings"
    />,
  );
  await screen.findByRole("heading", { name: "Storage settings" });
  fireEvent.change(screen.getByLabelText("File size (MiB)"), {
    target: { value: "20" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save limit" }));
  await waitFor(() =>
    expect(api.storageRequest).toHaveBeenCalledWith(
      "admin/storage/settings",
      "csrf",
      "PUT",
      { upload_max_bytes: 20 * 1024 ** 2 },
    ),
  );
  expect(
    screen.queryByRole("heading", { name: "Storage locations" }),
  ).not.toBeInTheDocument();
});

test("diagnostics stays reachable for invalid configuration and retains dismissible history", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    configuration_error: "Manifest access is invalid",
    jobs: [
      {
        ...job,
        action: "update",
        state: "failed",
        disposition: "obsolete",
        can_retry: false,
        can_dismiss: true,
      },
    ],
  });
  render(
    <StorageAdministration
      csrfToken="csrf"
      route="#administration/storage/diagnostics"
    />,
  );
  expect(
    await screen.findByRole("heading", {
      name: "Storage diagnostics & history",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Open diagnostics" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByText("History", { selector: "summary" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Dismiss configure location" }),
  );
  await waitFor(() =>
    expect(api.storageRequest).toHaveBeenCalledWith(
      "admin/storage/jobs/job/dismiss",
      "csrf",
      "POST",
    ),
  );
  expect(
    screen.queryByRole("button", { name: "Retry configure location" }),
  ).not.toBeInTheDocument();
});

test("disconnect requires confirmation and preserves files", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    roots: [root],
  });
  render(
    <StorageAdministration
      csrfToken="csrf"
      route="#administration/storage/locations/second/configuration"
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  expect(api.submitStorageOperation).not.toHaveBeenCalled();
  expect(screen.getByText(/files stay on the server/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
  await waitFor(() =>
    expect(api.submitStorageOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "remove",
        root_id: "second",
        confirmed: true,
      }),
      "csrf",
    ),
  );
});
