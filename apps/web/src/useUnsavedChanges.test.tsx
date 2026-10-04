import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import useUnsavedChanges, { useNavigationGuard } from "./useUnsavedChanges";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

function Editor({
  dirty,
  onNavigate,
}: {
  dirty: boolean;
  onNavigate: () => void;
}) {
  useNavigationGuard();
  useUnsavedChanges(dirty);
  return (
    <>
      <a href="#account" onClick={onNavigate}>
        Account
      </a>
      <button
        role="tab"
        aria-selected="false"
        onClick={onNavigate}
        onKeyDown={onNavigate}
      >
        Users
      </button>
      <select
        aria-label="Location"
        data-discard-changes
        data-current-value="first"
        defaultValue="first"
        onChange={onNavigate}
      >
        <option value="first">First</option>
        <option value="second">Second</option>
      </select>
    </>
  );
}

test("canceled navigation preserves drafts across links, tabs, and location changes", () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  const navigate = vi.fn();
  render(<Editor dirty onNavigate={navigate} />);
  fireEvent.click(screen.getByRole("link"));
  fireEvent.keyDown(screen.getByRole("tab"), { key: "ArrowRight" });
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "second" },
  });
  expect(navigate).not.toHaveBeenCalled();
  expect(screen.getByRole("combobox")).toHaveValue("first");
});

test("history traversal is stopped before route listeners can discard a draft", () => {
  window.history.replaceState({ arkNavigationIndex: 2 }, "", "/#account");
  vi.spyOn(window, "confirm").mockReturnValue(false);
  const go = vi.spyOn(window.history, "go").mockImplementation(() => {});
  render(<Editor dirty onNavigate={() => {}} />);
  const route = vi.fn();
  window.addEventListener("hashchange", route);
  window.history.replaceState({ arkNavigationIndex: 1 }, "", "/#overview");
  fireEvent(
    window,
    new PopStateEvent("popstate", { state: { arkNavigationIndex: 1 } }),
  );
  fireEvent(
    window,
    new HashChangeEvent("hashchange", {
      oldURL: "http://localhost/#account",
      newURL: window.location.href,
    }),
  );
  expect(go).toHaveBeenCalledWith(1);
  expect(route).not.toHaveBeenCalled();
  // Simulate the browser restoring the rejected history traversal.
  window.history.replaceState({ arkNavigationIndex: 2 }, "", "/#account");
  fireEvent(
    window,
    new PopStateEvent("popstate", { state: { arkNavigationIndex: 2 } }),
  );
  fireEvent(window, new HashChangeEvent("hashchange"));
  expect(route).not.toHaveBeenCalled();
  window.removeEventListener("hashchange", route);
});

test("only dirty drafts prevent unloading and clean forms do not prompt", () => {
  const confirm = vi.spyOn(window, "confirm");
  const { rerender } = render(<Editor dirty onNavigate={() => {}} />);
  const dirtyUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(dirtyUnload);
  expect(dirtyUnload.defaultPrevented).toBe(true);
  rerender(<Editor dirty={false} onNavigate={() => {}} />);
  const cleanUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(cleanUnload);
  expect(cleanUnload.defaultPrevented).toBe(false);
  fireEvent.click(screen.getByRole("tab"));
  expect(confirm).not.toHaveBeenCalled();
});
