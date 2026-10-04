import { useEffect, useId, useRef, useState } from "react";

type Theme = "light" | "dark";

const themeKey = "ark-cloud-theme";
const contrastKey = "ark-cloud-contrast";
const paletteKey = "ark-cloud-palette";
const palettes = ["graphite", "spruce", "harbor", "iris", "copper"] as const;
type Palette = (typeof palettes)[number];

function initialPalette(): Palette {
  const saved = preference(paletteKey);
  return palettes.find((palette) => palette === saved) ?? "graphite";
}

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

function applyAppearance(
  theme: Theme,
  highContrast: boolean,
  palette: Palette,
) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.contrast = highContrast ? "more" : "normal";
  document.documentElement.dataset.palette = palette;
  document.documentElement.style.colorScheme = theme;
  const canvas = getComputedStyle(document.documentElement)
    .getPropertyValue("--canvas")
    .trim();
  if (canvas) {
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", canvas);
  }
}

function savePreference(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Appearance still changes for the current page when storage is unavailable.
  }
}

export default function AppearanceControls({
  showControls = true,
}: {
  showControls?: boolean;
}) {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [highContrast, setHighContrast] = useState(initialContrast);
  const [palette, setPalette] = useState<Palette>(initialPalette);
  const paletteGroup = useId();
  const manualTheme = useRef(
    ["dark", "light"].includes(preference(themeKey) ?? ""),
  );
  const manualContrast = useRef(
    ["more", "normal"].includes(preference(contrastKey) ?? ""),
  );

  useEffect(() => {
    applyAppearance(theme, highContrast, palette);
  }, [theme, highContrast, palette]);

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
    applyAppearance(next, highContrast, palette);
  };

  const toggleContrast = () => {
    const next = !highContrast;
    manualContrast.current = true;
    savePreference(contrastKey, next ? "more" : "normal");
    setHighContrast(next);
    applyAppearance(theme, next, palette);
  };

  const choosePalette = (next: Palette) => {
    savePreference(paletteKey, next);
    setPalette(next);
    applyAppearance(theme, highContrast, next);
  };

  // Keep saved appearance and OS preferences active on authentication screens.
  if (!showControls) return null;

  return (
    <fieldset className="appearance-controls">
      <legend>Appearance</legend>
      <fieldset className="theme-picker">
        <legend>Themes</legend>
        {palettes.map((option) => (
          <label className="theme-option" key={option}>
            <input
              type="radio"
              name={paletteGroup}
              value={option}
              aria-label={
                option === "graphite" ? "Graphite Default" : undefined
              }
              checked={palette === option}
              onChange={() => choosePalette(option)}
            />
            <span
              className={`theme-swatches theme-swatches--${option}`}
              aria-hidden="true"
            >
              <span />
              <span />
              <span />
            </span>
            <span className="theme-name">
              {option.charAt(0).toUpperCase() + option.slice(1)}
              {option === "graphite" && <small> Default</small>}
            </span>
          </label>
        ))}
      </fieldset>
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
      <p className="appearance-note">Saved in this browser.</p>
    </fieldset>
  );
}
