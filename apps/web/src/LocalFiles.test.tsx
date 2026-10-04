import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import LocalFiles from "./LocalFiles";
import * as api from "./localStorageApi";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
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

async function findFileAction(role: "button" | "link", name: string) {
  const filename = name.replace(/^(Download|Rename|Move|Delete) /, "");
  const summary = await screen.findByLabelText(`Actions for ${filename}`, {
    selector: "summary",
  });
  if (!summary.closest("details")?.open) fireEvent.click(summary);
  return screen.findByRole(role, { name });
}

test("browses and downloads through the authenticated same-origin route", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  expect(await findFileAction("link", "Download notes.txt")).toHaveAttribute(
    "href",
    expect.stringContaining("/api/storage/personal/download?path=notes.txt"),
  );
  expect(screen.getByText("512 B available")).toBeInTheDocument();
  expect(
    screen.getByRole("navigation", { name: "File breadcrumbs" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Up one folder" })).toBeDisabled();
});

test("a linked folder takes precedence over the saved starting folder", async () => {
  window.history.replaceState(
    {},
    "",
    "/?files-path=Reports%2F2026#local-files/personal",
  );
  render(<LocalFiles csrfToken="csrf" />);
  await findFileAction("link", "Download notes.txt");
  expect(api.fetchLocalItems).toHaveBeenCalledWith(
    "personal",
    "Reports/2026",
    expect.any(AbortSignal),
  );
  expect(
    screen.getByRole("navigation", { name: "File breadcrumbs" }),
  ).toBeInTheDocument();
});

test("Up traverses one folder at a time and breadcrumbs identify the current folder", async () => {
  window.history.replaceState(
    {},
    "",
    "/?files-path=Reports%2F2026#local-files/personal",
  );
  render(<LocalFiles csrfToken="csrf" />);
  await screen.findByRole("link", { name: "notes.txt" });
  const breadcrumbs = screen.getByRole("navigation", {
    name: "File breadcrumbs",
  });
  expect(breadcrumbs.querySelector('[aria-current="page"]')).toHaveTextContent(
    "2026",
  );
  fireEvent.click(screen.getByRole("button", { name: "Up one folder" }));
  await waitFor(() =>
    expect(api.fetchLocalItems).toHaveBeenLastCalledWith(
      "personal",
      "Reports",
      expect.any(AbortSignal),
    ),
  );
  expect(breadcrumbs.querySelector('[aria-current="page"]')).toHaveTextContent(
    "Reports",
  );
  fireEvent.click(
    within(breadcrumbs).getByRole("button", { name: "My files" }),
  );
  await waitFor(() =>
    expect(api.fetchLocalItems).toHaveBeenLastCalledWith(
      "personal",
      "",
      expect.any(AbortSignal),
    ),
  );
  expect(screen.getByRole("button", { name: "Up one folder" })).toBeDisabled();
});

test("requires explicit deletion confirmation and includes the item revision", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  fireEvent.click(await findFileAction("button", "Delete notes.txt"));
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
  fireEvent.click(await findFileAction("button", "Rename notes.txt"));
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
  await findFileAction("link", "Download notes.txt");
  expect(
    screen.queryByRole("button", { name: "Upload file" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Delete notes.txt" }),
  ).not.toBeInTheDocument();
});

test("refresh detects a deleted host location and removes file controls", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  await findFileAction("link", "Download notes.txt");
  vi.mocked(api.fetchStorageRoots).mockResolvedValue({
    roots: [
      {
        ...root,
        state: "unavailable",
        message: "Host storage directory is missing.",
      },
    ],
    message: "",
  });
  fireEvent.click(
    screen.getByText("Location options", { selector: "summary" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh locations" }));
  await screen.findByText("Host storage directory is missing.");
  expect(api.fetchStorageRoots).toHaveBeenLastCalledWith(
    expect.any(AbortSignal),
    true,
  );
  expect(
    screen.queryByRole("link", { name: "Download notes.txt" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Upload file" }),
  ).not.toBeInTheDocument();
});

test("failed host refresh does not leave old connected file controls usable", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  await findFileAction("link", "Download notes.txt");
  vi.mocked(api.fetchStorageRoots).mockRejectedValue(
    new Error("Host storage refresh timed out."),
  );
  fireEvent.click(
    screen.getByText("Location options", { selector: "summary" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh locations" }));
  await screen.findByText("Host storage refresh timed out.");
  expect(
    screen.queryByRole("button", { name: "Upload file" }),
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
  await screen.findByLabelText("Folder options", { selector: "summary" });
  fireEvent.click(
    screen.getByLabelText("Folder options", { selector: "summary" }),
  );
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
  const trigger = await findFileAction("button", "Delete notes.txt");
  trigger.focus();
  fireEvent.click(trigger);
  expect(
    screen.getByRole("heading", { name: "Permanently delete this item?" }),
  ).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() =>
    expect(
      screen.getByLabelText("Actions for notes.txt", { selector: "summary" }),
    ).toHaveFocus(),
  );
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

test("folder queries belong to their root while legacy linked folders remain supported", async () => {
  window.history.replaceState(
    {},
    "",
    "/?files-root=other&files-path=Private#local-files/personal",
  );
  render(<LocalFiles csrfToken="csrf" />);
  await findFileAction("link", "Download notes.txt");
  expect(api.fetchLocalItems).toHaveBeenCalledWith(
    "personal",
    "",
    expect.any(AbortSignal),
  );
  expect(new URLSearchParams(window.location.search).get("files-root")).toBe(
    "personal",
  );
});

test("refresh after a stale rename preserves the draft and retries with the fresh revision", async () => {
  vi.mocked(api.localMutation).mockRejectedValueOnce(
    new Error("Item changed. Refresh and retry."),
  );
  render(<LocalFiles csrfToken="csrf" />);
  fireEvent.click(await findFileAction("button", "Rename notes.txt"));
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "draft.txt" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Rename item" }));
  await screen.findByRole("alert");
  vi.mocked(api.fetchLocalItems).mockResolvedValue({
    items: [{ ...item, revision: "fresh" }],
    revision: "fresh-list",
    next_offset: null,
    skipped_count: 0,
  });
  fireEvent.click(
    within(screen.getByRole("form", { name: "Rename item" })).getByRole(
      "button",
      { name: "Refresh files" },
    ),
  );
  await screen.findByText("Item refreshed. Your draft has been preserved.");
  expect(screen.getByLabelText("Name")).toHaveValue("draft.txt");
  fireEvent.click(screen.getByRole("button", { name: "Rename item" }));
  await waitFor(() =>
    expect(api.localMutation).toHaveBeenLastCalledWith(
      "personal",
      "move",
      "csrf",
      { path: "notes.txt", revision: "fresh", destination: "draft.txt" },
    ),
  );
});

test("refreshed deletion requires renewed review and uses the fresh item revision", async () => {
  vi.mocked(api.localMutation).mockRejectedValueOnce(
    new Error("Item changed. Refresh and retry."),
  );
  render(<LocalFiles csrfToken="csrf" />);
  fireEvent.click(await findFileAction("button", "Delete notes.txt"));
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  await screen.findByRole("alert");
  vi.mocked(api.fetchLocalItems).mockResolvedValue({
    items: [{ ...item, revision: "fresh" }],
    revision: "fresh-list",
    next_offset: null,
    skipped_count: 0,
  });
  fireEvent.click(
    within(
      screen.getByRole("form", { name: "Permanently delete this item?" }),
    ).getByRole("button", { name: "Refresh files" }),
  );
  await screen.findByText("Item refreshed. Review it again before deleting.");
  expect(
    screen.getByRole("button", { name: "Delete permanently" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("heading", { name: "Permanently delete this item?" }),
  ).toHaveFocus();
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I reviewed the refreshed item/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  await waitFor(() =>
    expect(api.localMutation).toHaveBeenLastCalledWith(
      "personal",
      "delete",
      "csrf",
      expect.objectContaining({ revision: "fresh" }),
    ),
  );
});

test("refresh reconciles edited items on later pages and closes a vanished item", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  fireEvent.click(await findFileAction("button", "Rename notes.txt"));
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "draft.txt" },
  });
  vi.mocked(api.fetchLocalItems)
    .mockResolvedValueOnce({
      items: [],
      revision: "new",
      next_offset: 1,
      skipped_count: 0,
    })
    .mockResolvedValueOnce({
      items: [{ ...item, revision: "later" }],
      revision: "new",
      next_offset: null,
      skipped_count: 0,
    });
  fireEvent.click(
    screen.getByLabelText("Folder options", { selector: "summary" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh files" }));
  await screen.findByText("Item refreshed. Your draft has been preserved.");
  expect(screen.getByLabelText("Name")).toHaveValue("draft.txt");
  vi.mocked(api.fetchLocalItems).mockResolvedValue({
    items: [],
    revision: "gone",
    next_offset: null,
    skipped_count: 0,
  });
  fireEvent.click(screen.getByRole("button", { name: "Refresh files" }));
  await screen.findByText(/This item is no longer in this folder/);
  expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
});

test("final pagination focuses the first added file and announces completion", async () => {
  vi.mocked(api.fetchLocalItems)
    .mockResolvedValueOnce({
      items: [item],
      revision: "list",
      next_offset: 1,
      skipped_count: 0,
    })
    .mockResolvedValueOnce({
      items: [{ ...item, name: "last.txt", path: "last.txt" }],
      revision: "list",
      next_offset: null,
      skipped_count: 0,
    });
  render(<LocalFiles csrfToken="csrf" />);
  const more = await screen.findByRole("button", { name: "Load more files" });
  expect(screen.getByText("1 item shown ·")).toBeInTheDocument();
  more.focus();
  fireEvent.click(more);
  await waitFor(() =>
    expect(screen.getByRole("link", { name: "last.txt" })).toHaveFocus(),
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "1 more item loaded. 2 items shown. All files loaded.",
  );
  expect(
    screen.queryByRole("button", { name: "Load more files" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("2 items shown ·")).toBeInTheDocument();
});

test("active upload warns on leaving, stays on declined navigation and cancels on unmount", async () => {
  const cancel = vi.fn();
  vi.mocked(api.uploadLocalFile).mockReturnValue({
    cancel,
    done: new Promise(() => {}),
  });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const view = render(<LocalFiles csrfToken="csrf" isAdmin />);
  await screen.findByRole("button", { name: "Upload file" });
  fireEvent.change(screen.getByLabelText("File to upload"), {
    target: { files: [new File(["contents"], "upload.txt")] },
  });
  fireEvent.click(
    screen.getByText("Location options", { selector: "summary" }),
  );
  const link = screen.getByRole("link", { name: "Manage storage" });
  expect(fireEvent.click(link)).toBe(false);
  expect(confirm).toHaveBeenCalledWith(
    "Leaving this page cancels the active upload. Leave and cancel upload?",
  );
  expect(cancel).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  expect(fireEvent.click(link)).toBe(true);
  view.unmount();
  expect(cancel).toHaveBeenCalledOnce();
});

test("a failed refresh blocks stale revision submission until refresh succeeds", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  fireEvent.click(await findFileAction("button", "Rename notes.txt"));
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "draft.txt" },
  });
  vi.mocked(api.fetchLocalItems).mockRejectedValueOnce(
    new Error("Refresh unavailable"),
  );
  fireEvent.click(
    screen.getByLabelText("Folder options", { selector: "summary" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh files" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "Rename item" })).toBeDisabled();
  expect(screen.getByLabelText("Name")).toHaveValue("draft.txt");
  fireEvent.click(
    within(screen.getByRole("form", { name: "Rename item" })).getByRole(
      "button",
      { name: "Refresh files" },
    ),
  );
  await screen.findByText("Item refreshed. Your draft has been preserved.");
  expect(screen.getByRole("button", { name: "Rename item" })).toBeEnabled();
});

test("declining an editor switch leaves the existing rename draft untouched", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<LocalFiles csrfToken="csrf" />);
  const rename = await findFileAction("button", "Rename notes.txt");
  fireEvent.click(rename);
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "draft.txt" },
  });
  fireEvent.click(await findFileAction("button", "Rename notes.txt"));
  expect(screen.getByLabelText("Name")).toHaveValue("draft.txt");
});

test("cancelling an editor during a paginated refresh does not reopen it", async () => {
  let resolve: (listing: api.LocalListing) => void = () => {};
  render(<LocalFiles csrfToken="csrf" />);
  fireEvent.click(await findFileAction("button", "Delete notes.txt"));
  vi.mocked(api.fetchLocalItems)
    .mockResolvedValueOnce({
      items: [],
      revision: "new",
      next_offset: 1,
      skipped_count: 0,
    })
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
  fireEvent.click(
    screen.getByLabelText("Folder options", { selector: "summary" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh files" }));
  await waitFor(() => expect(api.fetchLocalItems).toHaveBeenCalledTimes(3));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await act(async () => {
    resolve({
      items: [item],
      revision: "new",
      next_offset: null,
      skipped_count: 0,
    });
  });
  expect(
    screen.queryByRole("heading", { name: "Permanently delete this item?" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "My files" })).toHaveFocus();
});

test("accepted page navigation cancels the transfer and ignores its late rejection", async () => {
  let reject: (error: Error) => void = () => {};
  const cancel = vi.fn(() => reject(new Error("Upload cancelled.")));
  vi.mocked(api.uploadLocalFile).mockReturnValue({
    cancel,
    done: new Promise<void>((_done, fail) => {
      reject = fail;
    }),
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const view = render(<LocalFiles csrfToken="csrf" isAdmin />);
  await screen.findByRole("button", { name: "Upload file" });
  fireEvent.change(screen.getByLabelText("File to upload"), {
    target: { files: [new File(["contents"], "upload.txt")] },
  });
  fireEvent.click(
    screen.getByText("Location options", { selector: "summary" }),
  );
  expect(
    fireEvent.click(screen.getByRole("link", { name: "Manage storage" })),
  ).toBe(true);
  await act(async () => view.unmount());
  expect(cancel).toHaveBeenCalledOnce();
  expect(api.fetchLocalItems).toHaveBeenCalledOnce();
});

test("item actions start closed and return focus to the menu after editing", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  const summary = await screen.findByLabelText("Actions for notes.txt", {
    selector: "summary",
  });
  const disclosure = summary.closest("details");
  expect(summary).toHaveTextContent("Actions");
  expect(disclosure).not.toHaveAttribute("open");
  expect(screen.getByRole("link", { name: "notes.txt" })).toHaveAttribute(
    "download",
  );
  fireEvent.click(summary);
  expect(disclosure).toHaveAttribute("open");
  const rename = screen.getByRole("button", { name: "Rename notes.txt" });
  rename.focus();
  fireEvent.click(rename);
  expect(screen.getByRole("heading", { name: "Rename item" })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(summary).toHaveFocus();
  expect(disclosure).not.toHaveAttribute("open");
});

test("item menus dismiss on Escape and outside interaction", async () => {
  render(<LocalFiles csrfToken="csrf" />);
  const summary = await screen.findByLabelText("Actions for notes.txt", {
    selector: "summary",
  });
  const disclosure = summary.closest("details");
  expect(disclosure).not.toHaveAttribute("open");
  fireEvent.click(summary);
  expect(disclosure).toHaveAttribute("open");
  summary.focus();
  fireEvent.keyDown(summary, { key: "Escape" });
  expect(disclosure).not.toHaveAttribute("open");
  expect(summary).toHaveFocus();
  fireEvent.click(summary);
  fireEvent.pointerDown(screen.getByRole("heading", { name: "My files" }));
  expect(disclosure).not.toHaveAttribute("open");
});

test("read-only phone folders have no useless Actions disclosure", async () => {
  vi.mocked(api.fetchStorageRoots).mockResolvedValue({
    roots: [{ ...root, read_only: true }],
    message: "",
  });
  vi.mocked(api.fetchLocalItems).mockResolvedValue({
    items: [
      {
        ...item,
        name: "Reports",
        path: "Reports",
        kind: "folder",
        size_bytes: null,
      },
      item,
    ],
    revision: "list",
    next_offset: null,
    skipped_count: 0,
  });
  render(<LocalFiles csrfToken="csrf" />);
  expect(await screen.findByRole("button", { name: "Reports" })).toBeEnabled();
  expect(
    screen.queryByLabelText("Actions for Reports"),
  ).not.toBeInTheDocument();
  const fileActions = screen.getByLabelText("Actions for notes.txt", {
    selector: "summary",
  });
  fireEvent.click(fileActions);
  expect(
    screen.getByRole("link", { name: "Download notes.txt" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Rename notes.txt" }),
  ).not.toBeInTheDocument();
});

test("location options group secondary controls and remain expanded when refresh finds an unavailable location", async () => {
  render(<LocalFiles csrfToken="csrf" isAdmin />);
  await screen.findByRole("link", { name: "notes.txt" });
  const disclosure = screen.getByRole("group", { name: "Location options" });
  expect(disclosure).not.toHaveAttribute("open");
  fireEvent.click(
    within(disclosure).getByText("Location options", { selector: "summary" }),
  );
  expect(disclosure).toHaveAttribute("open");
  expect(
    within(disclosure).getByRole("link", { name: "Manage storage" }),
  ).toHaveAttribute("href", "#administration");
  expect(
    within(disclosure).getByRole("button", { name: "Clear default" }),
  ).toBeEnabled();
  vi.mocked(api.fetchStorageRoots).mockResolvedValue({
    roots: [{ ...root, state: "unavailable", message: "Mount missing" }],
    message: "",
  });
  fireEvent.click(
    within(disclosure).getByRole("button", { name: "Refresh locations" }),
  );
  await screen.findByText("Mount missing");
  expect(disclosure).toHaveAttribute("open");
  expect(
    within(disclosure).getByRole("button", { name: "Refresh locations" }),
  ).toBeEnabled();
});
