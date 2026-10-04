import { useEffect, useRef } from "react";
import { administrationRoute } from "./administrationRoutes";
import { revealDestination } from "./navigation";

const sections = [
  { id: "overview", label: "Overview", hash: "#administration" },
  { id: "storage", label: "Storage", hash: "#administration/storage" },
  { id: "system", label: "System", hash: "#administration/system" },
  { id: "tailscale", label: "Tailscale", hash: "#administration/tailscale" },
  { id: "users", label: "Users", hash: "#administration/users" },
] as const;

export default function AdministrationTabs({ route }: { route: string }) {
  const buttons = useRef<(HTMLAnchorElement | null)[]>([]);
  const page = administrationRoute(route).page;
  const selected =
    route === "#administration/users" || route === "#administration-users"
      ? "users"
      : page === "system"
        ? "system"
        : page === "tailscale"
          ? "tailscale"
          : page === "overview"
            ? "overview"
            : "storage";

  useEffect(() => {
    const button =
      buttons.current[sections.findIndex((section) => section.id === selected)];
    const strip = button?.parentElement;
    if (button && strip) revealDestination(strip, button);
  }, [selected]);

  return (
    <div
      className="administration-tabs"
      role="tablist"
      aria-label="Administration sections"
    >
      {sections.map((section, index) => (
        <a
          key={section.id}
          ref={(element) => {
            buttons.current[index] = element;
          }}
          href={section.hash}
          role="tab"
          id={`administration-tab-${section.id}`}
          aria-selected={selected === section.id}
          aria-controls="administration-panel"
          tabIndex={selected === section.id ? 0 : -1}
          onKeyDown={(event) => {
            let next: number;
            if (event.key === "ArrowRight")
              next = (index + 1) % sections.length;
            else if (event.key === "ArrowLeft")
              next = (index + sections.length - 1) % sections.length;
            else if (event.key === "Home") next = 0;
            else if (event.key === "End") next = sections.length - 1;
            else return;
            event.preventDefault();
            buttons.current[next]?.focus();
            window.location.hash = sections[next].hash;
          }}
        >
          {section.label}
        </a>
      ))}
    </div>
  );
}
