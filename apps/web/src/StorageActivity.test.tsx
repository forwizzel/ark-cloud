import { useState } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import StorageActivity from "./StorageActivity";
import * as api from "./storageAdminApi";

vi.mock("./storageAdminApi", async (original) => ({
  ...(await original<typeof api>()),
  storageRequest: vi.fn(),
}));
afterEach(cleanup);

test("dismissing a current issue announces the response and focuses a surviving heading", async () => {
  const issue: api.StorageJob = {
    id: "issue",
    action: "repair",
    payload: {},
    state: "failed",
    disposition: "attention",
    can_dismiss: true,
    message: "Repair failed",
    result: {},
    created_at: "2026-10-01T12:00:00Z",
  };
  vi.mocked(api.storageRequest).mockResolvedValue({
    message: "Notification dismissed.",
  });
  function Harness() {
    const [jobs, setJobs] = useState([issue]);
    const [notice, setNotice] = useState("");
    return (
      <>
        <p role="status">{notice}</p>
        <StorageActivity
          jobs={jobs}
          csrfToken="csrf"
          busy={false}
          titles={{ repair: "Repair connection" }}
          onNotice={setNotice}
          onRefresh={async () => {
            setJobs([]);
          }}
          onRetry={vi.fn()}
        />
      </>
    );
  }
  render(<Harness />);
  const dismiss = screen.getByRole("button", {
    name: "Dismiss repair connection",
  });
  dismiss.focus();
  fireEvent.click(dismiss);
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: "Current issues & progress" }),
    ).toHaveFocus(),
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Notification dismissed.",
  );
  expect(
    screen.queryByRole("button", { name: "Dismiss repair connection" }),
  ).not.toBeInTheDocument();
});
