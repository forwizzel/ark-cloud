import { expect, test, vi } from "vitest";

import {
  createSavedSearch,
  driveQueryParameters,
  type SavedSearchFilters,
} from "./api";

const filters: SavedSearchFilters = {
  q: "roadmap",
  view: "starred",
  kind: "document",
  parent_id: null,
  modified_after: "2026-01-01T00:00:00Z",
  modified_before: null,
  min_size: 1024,
  max_size: 4096,
  starred: true,
  ownership: "owned_by_me",
  sort: "size",
  direction: "asc",
};

test("serializes practical Drive filters without null parameters", () => {
  const parameters = driveQueryParameters({
    ...filters,
    cursor: "revision-cursor",
    limit: 20,
  });

  expect(parameters.get("q")).toBe("roadmap");
  expect(parameters.get("view")).toBe("starred");
  expect(parameters.get("kind")).toBe("document");
  expect(parameters.get("modified_after")).toBe("2026-01-01T00:00:00Z");
  expect(parameters.get("min_size")).toBe("1024");
  expect(parameters.get("max_size")).toBe("4096");
  expect(parameters.get("starred")).toBe("true");
  expect(parameters.get("ownership")).toBe("owned_by_me");
  expect(parameters.get("sort")).toBe("size");
  expect(parameters.get("direction")).toBe("asc");
  expect(parameters.get("cursor")).toBe("revision-cursor");
  expect(parameters.has("parent_id")).toBe(false);
  expect(parameters.has("modified_before")).toBe(false);
});

test("sends the CSRF token when saving a search", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        id: "saved-1",
        name: "Roadmap",
        filters,
        created_at: "2026-09-23T12:00:00Z",
      }),
      { status: 201, headers: { "Content-Type": "application/json" } },
    ),
  );

  await createSavedSearch("Roadmap", filters, "csrf-value");

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/integrations/google-drive/saved-searches",
    expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "X-CSRF-Token": "csrf-value" }),
    }),
  );
});
