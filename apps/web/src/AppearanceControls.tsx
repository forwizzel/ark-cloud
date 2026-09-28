import { useEffect, useRef, useState } from "react";

type Theme = "light" | "dark";

const themeKey = "ark-cloud-theme";
const contrastKey = "ark-cloud-contrast";

function preference(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function systemPrefers(query: string): boolean {
  return window.matchMedia?.(query).matches ?? false;
}

function initialTheme(): Theme {
  const saved = preference(themeKey);
  if (saved === "dark" || saved === "light") return saved;
  return systemPrefers("(prefers-color-scheme: light)") ? "light" : "dark";
}

function initialContrast(): boolean {
  const saved = preference(contrastKey);
  if (saved === "more" || saved === "normal") return saved === "more";
  return systemPrefers("(prefers-contrast: more)");
}

function applyAppearance(theme: Theme, highContrast: boolean) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.contrast = highContrast ? "more" : "normal";
  document.documentElement.style.colorScheme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute(
      "content",
      highContrast
        ? theme === "light"
          ? "#ffffff"
          : "#000000"
        : theme === "light"
          ? "#f2f5f2"
          : "#111b22",
    );
}

function savePreference(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Appearance still changes for the current page when storage is unavailable.
  }
}

export default function AppearanceControls() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [highContrast, setHighContrast] = useState(initialContrast);
  const manualTheme = useRef(
    ["dark", "light"].includes(preference(themeKey) ?? ""),
  );
  const manualContrast = useRef(
    ["more", "normal"].includes(preference(contrastKey) ?? ""),
  );

  useEffect(() => {
    applyAppearance(theme, highContrast);
  }, [theme, highContrast]);

  useEffect(() => {
    if (!window.matchMedia) return;
    const colorScheme = window.matchMedia("(prefers-color-scheme: light)");
    const contrast = window.matchMedia("(prefers-contrast: more)");
    const onColorChange = () => {
      if (manualTheme.current) return;
      setTheme(colorScheme.matches ? "light" : "dark");
    };
    const onContrastChange = () => {
      if (manualContrast.current) return;
      setHighContrast(contrast.matches);
    };
    colorScheme.addEventListener("change", onColorChange);
    contrast.addEventListener("change", onContrastChange);
    return () => {
      colorScheme.removeEventListener("change", onColorChange);
      contrast.removeEventListener("change", onContrastChange);
    };
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    manualTheme.current = true;
    savePreference(themeKey, next);
    setTheme(next);
    applyAppearance(next, highContrast);
  };

  const toggleContrast = () => {
    const next = !highContrast;
    manualContrast.current = true;
    savePreference(contrastKey, next ? "more" : "normal");
    setHighContrast(next);
    applyAppearance(theme, next);
  };

  return (
    <fieldset className="appearance-controls">
      <legend>Appearance</legend>
      <button
        type="button"
        role="switch"
        aria-checked={theme === "light"}
        onClick={toggleTheme}
      >
        <span>Light mode</span>
        <span className="appearance-switch" aria-hidden="true" />
      </button>
      <button
        type="button"
        role="switch"
        aria-checked={highContrast}
        onClick={toggleContrast}
      >
        <span>High contrast</span>
        <span className="appearance-switch" aria-hidden="true" />
      </button>
    </fieldset>
  );
}
