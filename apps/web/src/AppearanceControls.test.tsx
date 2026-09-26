import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import AppearanceControls from "./AppearanceControls";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-contrast");
  document.documentElement.style.removeProperty("color-scheme");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("toggles theme and contrast independently and restores saved choices", () => {
  render(<AppearanceControls />);

  const light = screen.getByRole("switch", { name: "Light mode" });
  const contrast = screen.getByRole("switch", { name: "High contrast" });
  expect(light).toHaveAttribute("aria-checked", "false");
  expect(contrast).toHaveAttribute("aria-checked", "false");

  fireEvent.click(contrast);
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(document.documentElement).toHaveAttribute("data-contrast", "more");
  fireEvent.click(light);
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(document.documentElement).toHaveAttribute("data-contrast", "more");
  fireEvent.click(contrast);
  expect(document.documentElement).toHaveAttribute("data-contrast", "normal");
  expect(window.localStorage.getItem("ark-cloud-theme")).toBe("light");
  expect(window.localStorage.getItem("ark-cloud-contrast")).toBe("normal");

  cleanup();
  render(<AppearanceControls />);
  expect(screen.getByRole("switch", { name: "Light mode" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("switch", { name: "High contrast" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
});

test("follows system preferences until the user chooses an override", () => {
  const listeners = new Map<string, (event: MediaQueryListEvent) => void>();
  const queries = new Map<string, boolean>([
    ["(prefers-color-scheme: light)", true],
    ["(prefers-contrast: more)", true],
  ]);
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      get matches() {
        return queries.get(query);
      },
      addEventListener: (
        event: string,
        listener: (event: MediaQueryListEvent) => void,
      ) => {
        if (event === "change") listeners.set(query, listener);
      },
      removeEventListener: () => listeners.delete(query),
    })),
  );

  render(<AppearanceControls />);
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(document.documentElement).toHaveAttribute("data-contrast", "more");

  queries.set("(prefers-contrast: more)", false);
  act(() => {
    listeners.get("(prefers-contrast: more)")?.({} as MediaQueryListEvent);
  });
  expect(document.documentElement).toHaveAttribute("data-contrast", "normal");

  queries.set("(prefers-color-scheme: light)", false);
  act(() => {
    listeners.get("(prefers-color-scheme: light)")?.({} as MediaQueryListEvent);
  });
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");

  fireEvent.click(screen.getByRole("switch", { name: "Light mode" }));
  queries.set("(prefers-color-scheme: light)", false);
  act(() => {
    listeners.get("(prefers-color-scheme: light)")?.({} as MediaQueryListEvent);
  });
  expect(document.documentElement).toHaveAttribute("data-theme", "light");

  fireEvent.click(screen.getByRole("switch", { name: "High contrast" }));
  act(() => {
    listeners.get("(prefers-contrast: more)")?.({} as MediaQueryListEvent);
  });
  expect(document.documentElement).toHaveAttribute("data-contrast", "more");
});

test("still changes appearance when browser storage is blocked", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("Storage blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Storage blocked");
  });

  render(<AppearanceControls />);
  fireEvent.click(screen.getByRole("switch", { name: "Light mode" }));
  fireEvent.click(screen.getByRole("switch", { name: "High contrast" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(document.documentElement).toHaveAttribute("data-contrast", "more");
});
