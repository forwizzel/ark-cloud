import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import LocalFiles from "./LocalFiles";
import * as api from "./localStorageApi";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

vi.mock("./localStorageApi", async (original) => ({
  ...(await original<typeof api>()),
  fetchStorageRoots: vi.fn(),
  fetchStoragePreference: vi.fn(),
  saveStoragePreference: vi.fn(),
  fetchLocalItems: vi.fn(),
  localMutation: vi.fn(),
  uploadLocalFile: vi.fn(),
}));

const root: api.StorageRoot = {
  id: "personal",
  label: "My files",
  read_only: false,
  state: "healthy",
  message: "Ready",
  total_bytes: 1024,
  available_bytes: 512,
};
const item: api.LocalItem = {
  name: "notes.txt",
  path: "notes.txt",
  kind: "file",
  size_bytes: 12,
  modified_at: "2026-09-29T12:00:00Z",
  revision: "a".repeat(32),
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchStoragePreference).mockResolvedValue({
    root_id: "personal",
    path: "",
    upload_max_bytes: 1024,
  });
  vi.mocked(api.fetchStorageRoots).mockResolvedValue({
    roots: [root],
    message: "",
  });
  vi.mocked(api.fetchLocalItems).mockResolvedValue({
    items: [item],
    revision: "b".repeat(32),
    next_offset: null,
    skipped_count: 0,
  });
  vi.mocked(api.localMutation).mockResolvedValue(undefined);
});

test("browses and downloads through the authenticated same-origin route", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  expect(
    await screen.findByRole("link", { name: "Download notes.txt" }),
  ).toHaveAttribute(
    "href",
    expect.stringContaining("/api/storage/personal/download?path=notes.txt"),
  );
  expect(screen.getByText("512 B available")).toBeInTheDocument();
});

test("a linked folder takes precedence over the saved starting folder", async () => {
  window.history.replaceState(
    {},
    "",
    "/?files-path=Reports%2F2026#local-files/personal",
  );
  render(<LocalFiles csrfToken="csrf" />);
  await screen.findByRole("link", { name: "Download notes.txt" });
  expect(api.fetchLocalItems).toHaveBeenCalledWith(
    "personal",
    "Reports/2026",
    expect.any(AbortSignal),
  );
});

test("requires explicit deletion confirmation and includes the item revision", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete notes.txt" }),
  );
  expect(api.localMutation).not.toHaveBeenCalled();
  expect(
    screen.getByText("This cannot be undone. Folders must be empty."),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  await waitFor(() =>
    expect(api.localMutation).toHaveBeenCalledWith(
      "personal",
      "delete",
      "csrf",
      expect.objectContaining({ path: "notes.txt", revision: item.revision }),
    ),
  );
});

test("renames in the current directory and reports conflicts", async () => {
  vi.mocked(api.localMutation).mockRejectedValue(
    new Error("The destination already exists. Choose another name."),
  );
  render(<LocalFiles csrfToken="csrf" />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Rename notes.txt" }),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
    target: { value: "new.txt" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Rename item" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "destination already exists",
  );
  expect(api.localMutation).toHaveBeenCalledWith("personal", "move", "csrf", {
    path: item.path,
    revision: item.revision,
    destination: "new.txt",
  });
});

test("read-only roots expose downloads without write controls", async () => {
  vi.mocked(api.fetchStorageRoots).mockResolvedValue({
    roots: [{ ...root, read_only: true }],
    message: "",
  });
  render(<LocalFiles csrfToken="csrf" />);
  await screen.findByRole("link", { name: "Download notes.txt" });
  expect(
    screen.queryByRole("button", { name: "Upload file" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Delete notes.txt" }),
  ).not.toBeInTheDocument();
});

test("unconfigured storage guides members to their administrator", async () => {
  vi.mocked(api.fetchStorageRoots).mockResolvedValue({
    roots: [],
    message: "Local files need configuration.",
  });
  render(<LocalFiles csrfToken="csrf" />);
  expect(
    await screen.findByText(
      "Ask your administrator to connect a folder for your account.",
    ),
  ).toBeInTheDocument();
  expect(api.fetchLocalItems).not.toHaveBeenCalled();
});

test("uploads with progress and offers cancellation", async () => {
  let reject: (error: Error) => void = () => {};
  const cancel = vi.fn(() => reject(new Error("Upload cancelled.")));
  vi.mocked(api.uploadLocalFile).mockImplementation(
    (_root, _path, _file, _csrf, progress) => {
      progress(50);
      return {
        cancel,
        done: new Promise<void>((_resolve, fail) => {
          reject = fail;
        }),
      };
    },
  );
  render(<LocalFiles csrfToken="csrf" />);
  await screen.findByRole("button", { name: "Upload file" });
  const file = new File(["contents"], "upload.txt");
  fireEvent.change(screen.getByLabelText("File to upload"), {
    target: { files: [file] },
  });
  expect(
    screen.getByRole("progressbar", { name: "Upload progress" }),
  ).toHaveAttribute("value", "50");
  fireEvent.click(screen.getByRole("button", { name: "Cancel upload" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Upload cancelled",
  );
  expect(cancel).toHaveBeenCalled();
  expect(screen.queryByText("Uploading upload.txt")).not.toBeInTheDocument();
});

test("does not silently select a default and saves an explicit starting folder", async () => {
  vi.mocked(api.fetchStoragePreference).mockResolvedValue({
    root_id: null,
    path: "",
    upload_max_bytes: 1024,
  });
  vi.mocked(api.saveStoragePreference).mockResolvedValue({
    root_id: "personal",
    path: "",
    upload_max_bytes: 1024,
  });
  render(<LocalFiles csrfToken="csrf" />);
  await screen.findByText("Choose your starting location");
  expect(api.fetchLocalItems).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Storage location"), {
    target: { value: "personal" },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Set as starting folder" }),
  );
  await waitFor(() =>
    expect(api.saveStoragePreference).toHaveBeenCalledWith(
      "personal",
      "",
      "csrf",
    ),
  );
});

test("oversized files are rejected before starting transfer", async () => {
  vi.mocked(api.fetchStoragePreference).mockResolvedValue({
    root_id: "personal",
    path: "",
    upload_max_bytes: 3,
  });
  render(<LocalFiles csrfToken="csrf" />);
  await screen.findByRole("button", { name: "Upload file" });
  fireEvent.change(screen.getByLabelText("File to upload"), {
    target: { files: [new File(["1234"], "large.txt")] },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "exceeds the 3 B upload limit",
  );
  expect(api.uploadLocalFile).not.toHaveBeenCalled();
});

test("administrator empty state links directly to setup", async () => {
  vi.mocked(api.fetchStorageRoots).mockResolvedValue({
    roots: [],
    message: "No locations assigned.",
  });
  render(<LocalFiles csrfToken="csrf" isAdmin />);
  expect(
    await screen.findByRole("link", { name: "Set up storage" }),
  ).toHaveAttribute("href", "#administration");
});

test("delete confirmation receives focus and cancel returns to its trigger", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  const trigger = await screen.findByRole("button", {
    name: "Delete notes.txt",
  });
  trigger.focus();
  fireEvent.click(trigger);
  expect(
    screen.getByRole("heading", { name: "Permanently delete this item?" }),
  ).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(trigger).toHaveFocus());
});

test("failed folder navigation moves focus to the location heading", async () => {
  vi.mocked(api.fetchLocalItems)
    .mockResolvedValueOnce({
      items: [
        {
          ...item,
          name: "Reports",
          path: "Reports",
          kind: "folder",
          size_bytes: null,
        },
      ],
      revision: "b".repeat(32),
      next_offset: null,
      skipped_count: 0,
    })
    .mockRejectedValueOnce(new Error("Folder unavailable."));
  render(<LocalFiles csrfToken="csrf" />);
  const folder = await screen.findByRole("button", { name: "Reports" });
  folder.focus();
  fireEvent.click(folder);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Folder unavailable",
  );
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Reports" })).toHaveFocus(),
  );
});
