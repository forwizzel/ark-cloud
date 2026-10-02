import type { SavedSearchFilters } from "./api";

export function readDriveFilters(
  defaults: SavedSearchFilters,
): SavedSearchFilters {
  const params = new URLSearchParams(window.location.search);
  const next = { ...defaults };
  const q = params.get("drive-q");
  if (q) next.q = q.slice(0, 200);
  const parent = params.get("drive-parent_id");
  if (parent) next.parent_id = parent;
  const view = params.get("drive-view");
  if (view === "all" || view === "recent" || view === "starred")
    next.view = view;
  const kind = params.get("drive-kind");
  if (
    kind &&
    [
      "all",
      "folder",
      "document",
      "image",
      "video",
      "audio",
      "archive",
      "other",
    ].includes(kind)
  )
    next.kind = kind as SavedSearchFilters["kind"];
  const sort = params.get("drive-sort");
  if (
    sort === "name" ||
    sort === "size" ||
    sort === "created" ||
    sort === "modified"
  )
    next.sort = sort;
  const direction = params.get("drive-direction");
  if (direction === "asc" || direction === "desc") next.direction = direction;
  if (params.get("drive-starred") === "true") next.starred = true;
  for (const key of ["min_size", "max_size"] as const) {
    const raw = params.get(`drive-${key}`);
    const value = raw === null ? NaN : Number(raw);
    if (Number.isSafeInteger(value) && value >= 0) next[key] = value;
  }
  for (const key of ["modified_after", "modified_before"] as const) {
    const raw = params.get(`drive-${key}`);
    if (raw && Number.isFinite(Date.parse(raw)))
      next[key] = new Date(raw).toISOString();
  }
  if (next.view !== "all") next.parent_id = null;
  return next;
}

export function writeDriveFilters(
  filters: SavedSearchFilters,
  defaults: SavedSearchFilters,
) {
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(filters)) {
    const param = `drive-${key}`;
    url.searchParams.delete(param);
    if (value !== null && value !== defaults[key as keyof SavedSearchFilters])
      url.searchParams.set(param, String(value));
  }
  window.history.replaceState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}
