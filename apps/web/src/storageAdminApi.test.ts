import { afterEach, expect, test, vi } from "vitest";
import { storageRequest, StorageRequestError } from "./storageAdminApi";

afterEach(() => vi.unstubAllGlobals());

test.each([500, 502, 503, 504, 401, 403, 409])(
  "storage failures preserve HTTP status %s for reconnect handling",
  async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("Proxy unavailable", { status })),
    );
    await expect(storageRequest("admin/storage", "csrf")).rejects.toMatchObject(
      {
        status,
        retryable: status >= 500,
      },
    );
  },
);

test("network failures are retryable but aborted requests are preserved", async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"));
  vi.stubGlobal("fetch", fetch);
  await expect(storageRequest("admin/storage", "csrf")).rejects.toBeInstanceOf(
    StorageRequestError,
  );
  const aborted = new DOMException("Aborted", "AbortError");
  fetch.mockRejectedValueOnce(aborted);
  await expect(storageRequest("admin/storage", "csrf")).rejects.toBe(aborted);
});
