import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import useUnsavedChanges from "./useUnsavedChanges";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function Editor({
  dirty,
  onNavigate,
}: {
  dirty: boolean;
  onNavigate: () => void;
}) {
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
