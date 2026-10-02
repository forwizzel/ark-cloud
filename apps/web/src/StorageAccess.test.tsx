import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import StorageAccess from "./StorageAccess";
import StorageAdministration from "./StorageAdministration";
import * as api from "./storageAdminApi";

vi.mock("./storageAdminApi", async (original) => ({
  ...(await original<typeof api>()),
  storageRequest: vi.fn(),
  fetchStorageAdministration: vi.fn(),
}));
afterEach(cleanup);
const root: api.ManagedLocation = {
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
  access_count: 2,
};
const access: api.LocationAccess = {
  root_id: "personal",
  registration: "00000000-0000-0000-0000-000000000001",
  kind: "managed",
  host_read_only: false,
  revision: 0,
  accounts: [
    {
      id: "admin",
      username: "admin",
      active: true,
      pending: false,
      level: "write",
      effective_level: "write",
      ready: true,
      message: "Private folder ready",
    },
    {
      id: "member",
      username: "member",
      active: true,
      pending: false,
      level: "write",
      effective_level: "write",
      ready: true,
      message: "Private folder ready",
    },
  ],
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.storageRequest).mockResolvedValue(access);
});

test("access editor shows member's existing private access and saves explicit revocation", async () => {
  const onChanged = vi.fn().mockResolvedValue(undefined);
  vi.mocked(api.storageRequest).mockImplementation(
    async (_path, _csrf, method) =>
      method === "PUT"
        ? {
            ...access,
            revision: 1,
            accounts: access.accounts.map((account) =>
              account.id === "member"
                ? {
                    ...account,
                    level: "none",
                    effective_level: "none",
                    message: "No access",
                  }
                : account,
            ),
          }
        : access,
  );
  render(
    <StorageAccess
      root={root}
      csrfToken="csrf"
      onClose={vi.fn()}
      onChanged={onChanged}
    />,
  );
  expect(await screen.findByLabelText("Access for member")).toHaveValue(
    "write",
  );
  expect(
    screen.getByText(/Each enabled account sees only its own private folder/),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Access for member"), {
    target: { value: "none" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save access for member" }),
  );
  await waitFor(() =>
    expect(api.storageRequest).toHaveBeenCalledWith(
      "admin/storage/roots/personal/access",
      "csrf",
      "PUT",
      {
        user_id: "member",
        level: "none",
        revision: 0,
        registration: access.registration,
      },
    ),
  );
  expect(
    await screen.findByText("Access saved for member. No restart needed."),
  ).toBeInTheDocument();
  expect(onChanged).toHaveBeenCalledOnce();
});

test("Manage access remains available with the host helper offline", async () => {
  vi.mocked(api.fetchStorageAdministration).mockResolvedValue({
    configuration_error: null,
    manager: {
      enrolled: true,
      online: false,
      last_seen_at: null,
      approved_paths: [],
    },
    setup: { default_path: "~/Ark-Files", repository_path: null, job: null },
    roots: [root],
    jobs: [],
    upload_max_bytes: 1024,
    upload_limit_source: "environment",
    users: [],
  });
  render(
    <StorageAdministration
      csrfToken="csrf"
      route="#administration/storage/locations/personal/access"
    />,
  );
  expect(await screen.findByLabelText("Access for member")).toHaveValue(
    "write",
  );
  expect(
    screen.getByRole("link", { name: "Configuration" }),
  ).toBeInTheDocument();
});

test("shared access editor explains shared files and respects the host read-only ceiling", async () => {
  vi.mocked(api.storageRequest).mockResolvedValue({
    ...access,
    kind: "shared",
    host_read_only: true,
  });
  render(
    <StorageAccess
      root={{ ...root, kind: "shared" }}
      csrfToken="csrf"
      onClose={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  const select = await screen.findByLabelText("Access for member");
  expect(select.querySelector('option[value="write"]')).toBeDisabled();
  expect(
    screen.getByText(/These accounts share the same files/),
  ).toBeInTheDocument();
});
