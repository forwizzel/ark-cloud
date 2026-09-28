import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import App from "./App";
import SystemInformationPage from "./SystemInformationPage";
import type { SystemInformation } from "./api";

const section = (source: SystemInformation["compute"]["source"]) => ({
  availability: "available" as const,
  source,
  warning: null,
});

const information: SystemInformation = {
  scope: "api-runtime-view",
  collected_at: "2026-09-13T12:00:00Z",
  identity: {
    ...section("configured"),
    hostname: "Ark",
    os: "Fedora Linux",
    kernel: "6-test",
    architecture: "x86_64",
    python_version: "3.14.7",
    api_version: "0.4.0",
    host_uptime_seconds: 7200,
  },
  compute: {
    ...section("kernel_view"),
    model: null,
    gpus: ["NVIDIA GeForce RTX 3070"],
    logical_cores: 4,
    percent: 12,
    load_average: [0.1, 0.2, 0.3],
    frequency_mhz: null,
  },
  memory: { ...section("kernel_view"), usage: null, swap: null },
  storage: {
    ...section("filesystem"),
    path: "/",
    usage: null,
    filesystem_type: null,
  },
  sensors: {
    availability: "available",
    source: "kernel_view",
    temperatures: [
      {
        label: "CPU package 0",
        source_name: "coretemp / Package id 0",
        celsius: 53,
      },
      { label: "Memory module 1", source_name: "jc42", celsius: 47 },
      {
        label: "Motherboard CPU sensor",
        source_name: "asusec / CPU",
        celsius: 42,
      },
      {
        label: "ACPI thermal zone 1",
        source_name: "acpitz / temp1",
        celsius: 38.5,
      },
    ],
    warning: "Sensor placement may not be known.",
  },
};

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

test("system page survives dashboard failure and shows GPU and understandable sensors", async () => {
  window.history.replaceState({}, "", "/#system-information");
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/auth/session")
        return json({
          authenticated: true,
          username: "ark",
          csrf_token: "csrf",
        });
      if (path === "/api/dashboard")
        return json({ detail: "Dashboard unavailable" }, 503);
      if (path === "/api/system/information") return json(information);
      return json({}, 404);
    });

  render(<App />);

  expect(
    await screen.findByRole("heading", { name: "Dashboard unavailable" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "System Information" }));

  expect(
    await screen.findByRole("heading", { name: "Temperatures" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Readings come from the API container/),
  ).toBeInTheDocument();
  expect(
    await screen.findByText("NVIDIA GeForce RTX 3070"),
  ).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "CPU" })).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Memory", level: 3 }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Motherboard" }),
  ).toBeInTheDocument();
  expect(screen.getByText("53.0 °C")).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "About these readings" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Load · 1 / 5 / 15 min")).not.toBeInTheDocument();
  expect(screen.queryByText("API version")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Sensor IDs"));
  expect(screen.getByText("acpitz / temp1")).toBeVisible();
  expect(fetchMock.mock.calls.map(([url]) => String(url))).not.toContain(
    "/api/system/processes",
  );
  expect(
    screen.queryByRole("heading", { name: "Visible processes" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Dashboard unavailable")).not.toBeInTheDocument();
});

test("information retries independently and absent GPU is clearly unavailable", async () => {
  let informationCalls = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path === "/api/system/information") {
      informationCalls += 1;
      return informationCalls === 1
        ? json({ detail: "System unavailable" }, 503)
        : json({
            ...information,
            compute: { ...information.compute, gpus: [] },
            sensors: {
              ...information.sensors,
              availability: "unavailable",
              temperatures: [],
              warning:
                "Temperature sensors are not available to the API runtime.",
            },
          });
    }
    return json({}, 404);
  });

  render(<SystemInformationPage />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "System unavailable",
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh readings" }));
  expect(
    await screen.findByRole("heading", { name: "Identity" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Detected GPU")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Temperature sensors are not available to the API runtime.",
    ),
  ).toBeInTheDocument();
  expect(screen.getAllByText("—").length).toBeGreaterThan(0);
});

test("refresh keeps temperatures visible and recovers from a failed request", async () => {
  let requests = 0;
  let resolveRefresh: ((response: Response) => void) | undefined;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (String(input) !== "/api/system/information") return json({}, 404);
    requests += 1;
    if (requests === 1) return json(information);
    if (requests === 2) {
      return new Promise<Response>((resolve) => {
        resolveRefresh = resolve;
      });
    }
    return json({
      ...information,
      collected_at: "2026-09-14T13:30:00Z",
      sensors: {
        ...information.sensors,
        temperatures: information.sensors.temperatures.map((reading, index) =>
          index === 0 ? { ...reading, celsius: 55 } : reading,
        ),
      },
    });
  });

  render(<SystemInformationPage />);
  expect(await screen.findByText("53.0 °C")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh readings" }));

  expect(screen.getByText("53.0 °C")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Compute" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Updating…" })).toBeDisabled();

  resolveRefresh?.(json({ detail: "Unavailable" }, 503));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Showing values from",
  );
  expect(screen.getByText("53.0 °C")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Refresh readings" }));
  expect(await screen.findByText("55.0 °C")).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByText(/Updated Sep 14/)).toBeInTheDocument(),
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
