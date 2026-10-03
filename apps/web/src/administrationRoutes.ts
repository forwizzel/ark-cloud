export type AdministrationRoute = {
  page:
    | "overview"
    | "storage"
    | "tailscale"
    | "system"
    | "new"
    | "settings"
    | "diagnostics"
    | "location";
  rootId?: string;
  tab?: "overview" | "access" | "configuration" | "activity";
};

export function administrationRoute(hash: string): AdministrationRoute {
  const parts = hash.replace(/^#/, "").split("/");
  if (parts[0] === "administration" && parts[1] === "system")
    return { page: "system" };
  if (parts[0] === "administration" && parts[1] === "tailscale")
    return { page: "tailscale" };
  if (parts[0] !== "administration" || parts[1] !== "storage")
    return { page: "overview" };
  if (parts[2] === "new") return { page: "new" };
  if (parts[2] === "settings") return { page: "settings" };
  if (parts[2] === "diagnostics") return { page: "diagnostics" };
  if (
    parts[2] === "locations" &&
    /^[a-z][a-z0-9-]{0,39}$/.test(parts[3] ?? "")
  ) {
    const tab = ["overview", "access", "configuration", "activity"].includes(
      parts[4],
    )
      ? (parts[4] as "overview" | "access" | "configuration" | "activity")
      : "overview";
    return { page: "location", rootId: parts[3], tab };
  }
  return { page: "storage" };
}

export const locationHref = (id: string, tab = "overview") =>
  `#administration/storage/locations/${encodeURIComponent(id)}/${tab}`;
