import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import startupHtml from "../index.html?raw";

import AppearanceControls from "./AppearanceControls";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-contrast");
  document.documentElement.removeAttribute("data-palette");
  document.documentElement.style.removeProperty("color-scheme");
  document.querySelector('meta[name="theme-color"]')?.remove();
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
  fireEvent.click(screen.getByRole("radio", { name: "Copper" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(document.documentElement).toHaveAttribute("data-contrast", "more");
  expect(document.documentElement).toHaveAttribute("data-palette", "copper");
});

test("palette selection is immediate, independent of mode, and restored", () => {
  window.localStorage.setItem("ark-cloud-theme", "light");
  window.localStorage.setItem("ark-cloud-contrast", "more");
  render(<AppearanceControls />);
  expect(screen.getAllByRole("radio")).toHaveLength(5);
  expect(screen.getByRole("radio", { name: "Graphite Default" })).toBeChecked();

  fireEvent.click(screen.getByRole("radio", { name: "Iris" }));
  expect(document.documentElement).toHaveAttribute("data-palette", "iris");
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(document.documentElement).toHaveAttribute("data-contrast", "more");
  expect(window.localStorage.getItem("ark-cloud-palette")).toBe("iris");

  fireEvent.click(screen.getByRole("switch", { name: "Light mode" }));
  fireEvent.click(screen.getByRole("switch", { name: "High contrast" }));
  cleanup();
  render(<AppearanceControls />);
  expect(screen.getByRole("radio", { name: "Iris" })).toBeChecked();
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(document.documentElement).toHaveAttribute("data-contrast", "normal");
});

test("unknown palettes fall back to Graphite without discarding mode preferences", () => {
  window.localStorage.setItem("ark-cloud-palette", "unknown");
  window.localStorage.setItem("ark-cloud-theme", "light");
  render(<AppearanceControls />);
  expect(screen.getByRole("radio", { name: "Graphite Default" })).toBeChecked();
  expect(document.documentElement).toHaveAttribute("data-palette", "graphite");
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
});

test("saved Spruce remains selectable after the default changes to Graphite", () => {
  window.localStorage.setItem("ark-cloud-palette", "spruce");
  render(<AppearanceControls />);
  expect(screen.getByRole("radio", { name: "Spruce" })).toBeChecked();
  expect(document.documentElement).toHaveAttribute("data-palette", "spruce");
});

test("appearance can restore saved preferences without rendering customization controls", () => {
  window.localStorage.setItem("ark-cloud-palette", "copper");
  window.localStorage.setItem("ark-cloud-theme", "light");
  const { container } = render(<AppearanceControls showControls={false} />);
  expect(container).toBeEmptyDOMElement();
  expect(document.documentElement).toHaveAttribute("data-palette", "copper");
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
});

test("choosing a palette does not override OS-following mode and contrast", () => {
  const listeners = new Map<string, () => void>();
  const queries = new Map<string, boolean>();
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      return queries.get(query) ?? false;
    },
    addEventListener: (_: string, listener: () => void) =>
      listeners.set(query, listener),
    removeEventListener: () => listeners.delete(query),
  }));
  render(<AppearanceControls />);
  fireEvent.click(screen.getByRole("radio", { name: "Harbor" }));
  act(() => {
    for (const [query, listener] of listeners) {
      queries.set(query, true);
      listener();
    }
  });
  expect(document.documentElement).toHaveAttribute("data-palette", "harbor");
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(document.documentElement).toHaveAttribute("data-contrast", "more");
  expect(window.localStorage.getItem("ark-cloud-theme")).toBeNull();
  expect(window.localStorage.getItem("ark-cloud-contrast")).toBeNull();
});

const startup = startupHtml.match(/<script>([\s\S]*?)<\/script>/)![1];

test.each([
  ["spruce", "#111b22", "#f2f5f2"],
  ["harbor", "#121b2a", "#f2f5fa"],
  ["iris", "#1b1826", "#f5f3fa"],
  ["copper", "#231b18", "#f8f4f0"],
  ["graphite", "#1b1d21", "#f4f5f6"],
])(
  "startup restores %s in all mode/contrast combinations before React",
  (palette, dark, light) => {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.appendChild(meta);
    window.localStorage.setItem("ark-cloud-palette", palette);
    for (const theme of ["dark", "light"]) {
      for (const contrast of ["normal", "more"]) {
        window.localStorage.setItem("ark-cloud-theme", theme);
        window.localStorage.setItem("ark-cloud-contrast", contrast);
        new Function(startup)();
        expect(document.documentElement).toHaveAttribute(
          "data-palette",
          palette,
        );
        expect(document.documentElement).toHaveAttribute("data-theme", theme);
        expect(document.documentElement).toHaveAttribute(
          "data-contrast",
          contrast,
        );
        expect(meta.content).toBe(
          contrast === "more"
            ? theme === "light"
              ? "#ffffff"
              : "#000000"
            : theme === "light"
              ? light
              : dark,
        );
      }
    }
  },
);

test.each(["unknown", "toString", "__proto__", null])(
  "startup rejects invalid palette %s",
  (palette) => {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.appendChild(meta);
    if (palette !== null)
      window.localStorage.setItem("ark-cloud-palette", palette);
    new Function(startup)();
    expect(document.documentElement).toHaveAttribute(
      "data-palette",
      "graphite",
    );
    expect(meta.content).toBe("#1b1d21");
  },
);
