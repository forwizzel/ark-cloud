import {
  act,
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
  vi.restoreAllMocks();
  vi.useRealTimers();
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
  expect(screen.getByRole("link", { name: "Manage" })).toHaveAttribute(
    "href",
    "#administration/storage/locations/second/overview",
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
  fireEvent.click(screen.getByRole("button", { name: "Connect location" }));
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

test("connecting a new shared folder reconnects without a false failure", async () => {
  vi.useFakeTimers();
  await act(async () => {
    render(
      <StorageAdministration
        csrfToken="csrf"
        route="#administration/storage/new"
      />,
    );
  });
  fireEvent.change(screen.getByLabelText("Location name"), {
    target: { value: "Second Directory" },
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Connect location" }));
  });
  expect(screen.getByText("Preparing access")).toBeInTheDocument();
  expect(api.submitStorageOperation).toHaveBeenCalledWith(
    expect.objectContaining({ create_directory: true, shared: true }),
    "csrf",
  );
  vi.mocked(api.fetchStorageAdministration).mockRejectedValue(
    new api.StorageRequestError(
      "Storage request failed. Refresh and retry.",
      500,
    ),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(
    screen.getByText("Applying storage mounts. Reconnecting automatically…"),
  ).toBeInTheDocument();
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    roots: [root],
    jobs: [
      { ...job, state: "completed", message: "Storage operation completed." },
    ],
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(
    screen.queryByText("Applying storage mounts. Reconnecting automatically…"),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(window.location.hash).toBe(
    "#administration/storage/locations/second/overview",
  );
});

test.each([
  { name: "idle outage", jobs: [], status: 503, delay: 3000 },
  { name: "permission failure", jobs: [job], status: 403, delay: 3000 },
  {
    name: "prolonged provisioning outage",
    jobs: [job],
    status: 502,
    delay: 33_000,
  },
])("$name still displays an error", async ({ jobs, status, delay }) => {
  vi.useFakeTimers();
  vi.mocked(api.fetchStorageAdministration)
    .mockResolvedValueOnce({ ...inventory, jobs })
    .mockRejectedValue(
      new api.StorageRequestError("Connection unavailable", status),
    );
  await act(async () => {
    render(
      <StorageAdministration
        csrfToken="csrf"
        route="#administration/storage"
      />,
    );
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(delay);
  });
  expect(screen.getByRole("alert")).toHaveTextContent("Connection unavailable");
  expect(
    screen.queryByText("Applying storage mounts. Reconnecting automatically…"),
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

test("settings failures are inline alerts with focus and retained input", async () => {
  vi.mocked(api.storageRequest).mockRejectedValueOnce(
    new Error("Upload policy could not be saved. Retry the request."),
  );
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
  const error = await screen.findByRole("alert");
  expect(error).toHaveTextContent(
    "Upload policy could not be saved. Retry the request.",
  );
  await waitFor(() => expect(error).toHaveFocus());
  expect(screen.getByLabelText("File size (MiB)")).toHaveValue(20);
  expect(screen.getByLabelText("File size (MiB)")).toHaveAttribute(
    "aria-describedby",
    "storage-settings-error",
  );
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
  const trigger = await screen.findByRole("button", { name: "Disconnect" });
  trigger.focus();
  fireEvent.click(trigger);
  expect(
    screen.getByRole("heading", { name: "Review disconnection" }),
  ).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(trigger).toHaveFocus();
  fireEvent.click(trigger);
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
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Confirm disconnect" }),
    ).not.toBeInTheDocument(),
  );
  expect(
    screen.getByRole("heading", { name: "Location configuration" }),
  ).toHaveFocus();
  expect(
    screen.getByText(
      "Storage request accepted. Follow its progress in Activity.",
    ),
  ).toHaveAttribute("role", "status");
});

test("failed confirmation stays available for retry", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    roots: [root],
  });
  vi.mocked(api.submitStorageOperation).mockRejectedValueOnce(
    new Error("Connection unavailable"),
  );
  render(
    <StorageAdministration
      csrfToken="csrf"
      route="#administration/storage/locations/second/configuration"
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Accept reviewed disk identity",
    }),
  );
  expect(
    screen.getByRole("heading", { name: "Review disk identity" }),
  ).toHaveFocus();
  fireEvent.click(
    screen.getByRole("button", { name: "Confirm reviewed identity" }),
  );
  await screen.findByText("Connection unavailable");
  expect(
    screen.getByRole("button", { name: "Confirm reviewed identity" }),
  ).toBeEnabled();
});

test("deployment reset replaces the settings draft and clears its dirty baseline", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(
    <StorageAdministration
      csrfToken="csrf"
      route="#administration/storage/settings"
    />,
  );
  const limit = await screen.findByLabelText("File size (MiB)");
  fireEvent.change(limit, { target: { value: "20" } });
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    upload_max_bytes: 128 * 1024 ** 2,
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Use deployment default" }),
  );
  await screen.findByText("Upload policy saved. No restart needed.");
  expect(limit).toHaveValue(128);
  expect(fireEvent.click(screen.getByRole("link", { name: "Locations" }))).toBe(
    true,
  );
  expect(confirm).not.toHaveBeenCalled();
});

test("settings polling updates clean fields but preserves active drafts", async () => {
  vi.useFakeTimers();
  await act(async () => {
    render(
      <StorageAdministration
        csrfToken="csrf"
        route="#administration/storage/settings"
      />,
    );
  });
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    upload_max_bytes: 128 * 1024 ** 2,
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(screen.getByLabelText("File size (MiB)")).toHaveValue(128);
  const cleanLeave = new Event("beforeunload", { cancelable: true });
  fireEvent(window, cleanLeave);
  expect(cleanLeave.defaultPrevented).toBe(false);
  fireEvent.change(screen.getByLabelText("File size (MiB)"), {
    target: { value: "20" },
  });
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    upload_max_bytes: 256 * 1024 ** 2,
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(screen.getByLabelText("File size (MiB)")).toHaveValue(20);
  expect(screen.getByText(/Effective limit:/)).toHaveTextContent("268,435,456");
  const dirtyLeave = new Event("beforeunload", { cancelable: true });
  fireEvent(window, dirtyLeave);
  expect(dirtyLeave.defaultPrevented).toBe(true);
  fireEvent.change(screen.getByLabelText("File size (MiB)"), {
    target: { value: "256" },
  });
  const reconciledLeave = new Event("beforeunload", { cancelable: true });
  fireEvent(window, reconciledLeave);
  expect(reconciledLeave.defaultPrevented).toBe(false);
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    upload_max_bytes: 512 * 1024 ** 2,
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(screen.getByLabelText("File size (MiB)")).toHaveValue(512);
});

test("Open my files clears stale folder query parameters", async () => {
  window.history.replaceState(
    {},
    "",
    "/?files-root=other&files-path=Private&keep=value#administration/storage/locations/second/overview",
  );
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    ...inventory,
    roots: [{ ...root, state: "healthy" }],
  });
  render(
    <StorageAdministration
      csrfToken="csrf"
      route="#administration/storage/locations/second/overview"
    />,
  );
  fireEvent.click(await screen.findByRole("link", { name: "Open my files" }));
  expect(window.location.search).toBe("?keep=value");
});
