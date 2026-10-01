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
afterEach(cleanup);
const inventory: api.StorageAdministration = {
  configuration_error: null,
  setup: { default_path: "~/Ark-Files", repository_path: null, job: null },
  manager: {
    enrolled: true,
    online: true,
    last_seen_at: "2026-09-30T12:00:00Z",
    approved_paths: ["/disk/files"],
  },
  roots: [],
  jobs: [],
  upload_max_bytes: 1024 ** 3,
  upload_limit_source: "environment",
  users: [
    { id: "account-id", username: "alice", active: true, pending: false },
  ],
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue(inventory);
  vi.mocked(api.storageRequest).mockResolvedValue({});
});

test("connect flow chooses account by name and reviews before applying", async () => {
  let current = inventory;
  vi.mocked(api.fetchStorageAdministration).mockImplementation(
    async () => current,
  );
  vi.mocked(api.submitStorageOperation).mockImplementation(async (body) => {
    const job: api.StorageJob = {
      id: "job",
      action: body.action,
      payload: body,
      state: "completed",
      message: "Checked",
      result: { message: "Eligible path", api_host_uid: 1000 },
      created_at: "2026-09-30T12:00:00Z",
    };
    current = { ...inventory, jobs: [job] };
    return job;
  });
  render(<StorageAdministration csrfToken="csrf" />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Connect existing folder" }),
  );
  fireEvent.change(screen.getByLabelText("Location name"), {
    target: { value: "Photos" },
  });
  fireEvent.change(screen.getByLabelText("Existing folder on the server"), {
    target: { value: "/disk/files/photos" },
  });
  fireEvent.change(screen.getByLabelText("Access for alice"), {
    target: { value: "write" },
  });
  expect(api.submitStorageOperation).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Review folder" }));
  await waitFor(() =>
    expect(api.submitStorageOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "preflight",
        shared: true,
        grants: [{ user_id: "account-id", level: "write" }],
        path: "/disk/files/photos",
      }),
      "csrf",
    ),
  );
  expect(
    await screen.findByText("Ready to connect", {}, { timeout: 4500 }),
  ).toBeInTheDocument();
  const buttons = screen.getAllByRole("button", { name: "Connect folder" });
  fireEvent.click(buttons.at(-1)!);
  await waitFor(() =>
    expect(api.submitStorageOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        action: "add",
        confirmed: true,
        shared: true,
        grants: [{ user_id: "account-id", level: "write" }],
      }),
      "csrf",
    ),
  );
}, 10000);

test("offline manager gives inline setup guidance and disables provisioning", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    manager: { ...inventory.manager, enrolled: false, online: false },
  });
  render(<StorageAdministration csrfToken="csrf" />);
  expect(await screen.findByText("Set up Local Files")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Connect existing folder" }),
  ).toBeDisabled();
  expect(screen.getByText("./scripts/ark storage setup")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("File size"), {
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
});

test("disconnect explains file retention and requires confirmation", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    roots: [
      {
        id: "photos",
        label: "Photos",
        source: "/disk/files/photos",
        kind: "assigned",
        owner: "account-id",
        username: "alice",
        read_only: true,
        selinux: "preserve",
        state: "healthy",
        message: "Connected",
      },
    ],
  });
  vi.mocked(api.submitStorageOperation).mockResolvedValue({
    id: "disconnect",
    action: "remove",
    payload: { action: "remove" },
    state: "queued",
    message: "Waiting",
    result: {},
    created_at: "2026-09-30T12:00:00Z",
  });
  render(<StorageAdministration csrfToken="csrf" />);
  fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  expect(api.submitStorageOperation).not.toHaveBeenCalled();
  expect(
    screen.getByText(
      /Files stay on the server; permissions and labels are not undone/,
    ),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
  await waitFor(() =>
    expect(api.submitStorageOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "remove",
        root_id: "photos",
        confirmed: true,
      }),
      "csrf",
    ),
  );
});

test("unreadable manifest keeps diagnostics visible while pausing changes", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    configuration_error:
      "The API cannot read or validate its storage manifest.",
    roots: [
      {
        id: "photos",
        label: "Photos",
        source: "/disk/files/photos",
        kind: "assigned",
        owner: "account-id",
        username: "alice",
        read_only: true,
        selinux: "preserve",
        state: "unavailable",
        message: "The API cannot read or validate its storage manifest.",
      },
    ],
    jobs: [
      {
        id: "failed",
        action: "update",
        payload: { action: "update" },
        state: "failed",
        disposition: "attention",
        can_retry: false,
        can_dismiss: true,
        retry_reason: "Restore manifest access before retrying.",
        message: "Configuration was applied, but verification failed.",
        result: {},
        created_at: "2026-09-30T12:00:00Z",
      },
    ],
  });
  render(<StorageAdministration csrfToken="csrf" />);
  expect(
    await screen.findByRole("heading", {
      name: "Storage configuration needs host attention",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Activity & diagnostics" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Configuration was applied, but verification failed."),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Retry configure location" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText("Restore manifest access before retrying."),
  ).toBeInTheDocument();
});

test("wizard copies the setup command and explains host context without manual mkdir", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  render(<StorageAdministration csrfToken="csrf" />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Copy setup command" }),
  );
  await waitFor(() =>
    expect(writeText).toHaveBeenCalledWith("./scripts/ark storage setup"),
  );
  expect(
    screen.getByText(/You do not need to create the directory yourself/),
  ).toBeInTheDocument();
  expect(screen.getByText(/not inside a container/)).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Connect an existing folder"));
  expect(
    screen.getByRole("button", { name: "Choose existing folder" }),
  ).toBeInTheDocument();
});

test("wizard follows host progress and opens a verified private location", async () => {
  const job: api.StorageJob = {
    id: "setup",
    action: "setup",
    payload: { action: "init" },
    state: "verifying",
    message: "Verifying access as the API user.",
    result: {},
    created_at: "2026-09-30T12:00:00Z",
  };
  let current: api.StorageAdministration = {
    ...inventory,
    setup: { ...inventory.setup, job },
    jobs: [job],
  };
  vi.mocked(api.fetchStorageAdministration).mockImplementation(
    async () => current,
  );
  render(<StorageAdministration csrfToken="csrf" />);
  expect(
    (await screen.findAllByText("Verifying access as the API user.")).length,
  ).toBeGreaterThan(0);
  current = {
    ...inventory,
    setup: { ...inventory.setup, job: { ...job, state: "completed" } },
    roots: [
      {
        id: "personal",
        label: "My files",
        source: "/home/owner/Ark-Files",
        kind: "managed",
        owner: null,
        username: null,
        read_only: false,
        selinux: "private",
        state: "healthy",
        message: "Connected",
      },
    ],
  };
  expect(
    await screen.findByText("Local Files is ready", {}, { timeout: 4500 }),
  ).toBeInTheDocument();
  expect(
    screen
      .getAllByRole("link", { name: "Open my files" })
      .some((link) => link.getAttribute("href") === "#local-files/personal"),
  ).toBe(true);
}, 10000);

test("obsolete failures are history and dismiss without retrying a removed location", async () => {
  const job: api.StorageJob = {
    id: "obsolete",
    action: "update",
    payload: { action: "update", root_id: "personal" },
    state: "failed",
    disposition: "obsolete",
    can_retry: false,
    can_dismiss: true,
    message: "Old configuration failure",
    result: {},
    created_at: "2026-09-30T12:00:00Z",
  };
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    jobs: [job],
  });
  render(<StorageAdministration csrfToken="csrf" />);
  expect(
    await screen.findByText(
      "No pending operations or current failure notifications.",
    ),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByText("History", { selector: "summary" }));
  expect(
    screen.queryByRole("button", { name: "Retry configure location" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Dismiss configure location" }),
  );
  await waitFor(() =>
    expect(api.storageRequest).toHaveBeenCalledWith(
      "admin/storage/jobs/obsolete/dismiss",
      "csrf",
      "POST",
    ),
  );
  expect(api.submitStorageOperation).not.toHaveBeenCalled();
});

test("stalled host setup explains how to resume instead of waiting indefinitely", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    setup: {
      ...inventory.setup,
      interrupted: true,
      job: {
        id: "stalled",
        action: "setup",
        payload: {},
        state: "applying",
        message: "Applying mounts",
        result: {},
        created_at: "2026-09-30T12:00:00Z",
      },
    },
  });
  render(<StorageAdministration csrfToken="csrf" />);
  expect(
    await screen.findByText("Resume the host setup command"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/If the host command stopped, rerun the same command/),
  ).toBeInTheDocument();
});
