import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import App from "./App";
import type { Dashboard } from "./api";

const dashboard: Dashboard = {
  platform: {
    status: "healthy",
    service: "ark-cloud-api",
    database: "connected",
  },
  system: {
    hostname: "Ark",
    os: "Fedora Linux",
    kernel: "6.18.7",
    uptime_seconds: 392_400,
    cpu_percent: 12,
    cpu_count: 8,
    memory: {
      total_bytes: 34_359_738_368,
      used_bytes: 8_589_934_592,
      available_bytes: 25_769_803_776,
      percent: 25,
    },
    storage: {
      total_bytes: 2_199_023_255_552,
      used_bytes: 861_140_942_848,
      available_bytes: 1_337_882_312_704,
      percent: 39.2,
    },
    storage_path: "/",
    scope: "api-runtime-view",
    collected_at: "2026-09-13T12:00:00Z",
  },
  tailscale: {
    state: "not_configured",
    device_count: 0,
    online_count: 0,
    devices: [],
    message: "Add a Tailscale access token to enable device status.",
    collected_at: "2026-09-13T12:00:00Z",
  },
  google_drive: {
    state: "not_configured",
    account_email: null,
    account_name: null,
    used_bytes: null,
    total_bytes: null,
    available_bytes: null,
    percent: null,
    message: "Connect a Google Drive account to enable Drive status.",
    checked_at: "2026-09-13T12:00:00Z",
    web_url: "https://drive.google.com/",
  },
  integrations: [
    {
      id: "system",
      name: "Ark system",
      state: "healthy",
      message: "System metrics are available.",
      checked_at: "2026-09-13T12:00:00Z",
    },
    {
      id: "tailscale",
      name: "Tailscale",
      state: "not_configured",
      message: "Add a Tailscale access token to enable device status.",
      checked_at: "2026-09-13T12:00:00Z",
    },
  ],
  generated_at: "2026-09-13T12:00:00Z",
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("renders normalized system and integration health", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          authenticated: true,
          username: "ark",
          csrf_token: "csrf",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(dashboard), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

  render(<App />);

  expect(
    await screen.findByRole("heading", { name: "Ark" }),
  ).toBeInTheDocument();
  expect(screen.getByText("4d 13h")).toBeInTheDocument();
  expect(screen.getByText("12%")).toBeInTheDocument();
  expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
  expect(screen.getByText("Primary storage")).toBeInTheDocument();
  expect(screen.getAllByText("Not configured")).toHaveLength(5);
});

test("renders normalized Tailscale devices", async () => {
  const withDevice: Dashboard = {
    ...dashboard,
    tailscale: {
      state: "healthy",
      device_count: 1,
      online_count: 1,
      message: "Device status is current.",
      collected_at: "2026-09-13T12:00:00Z",
      devices: [
        {
          id: "device-1",
          hostname: "Laptop",
          os: "windows",
          addresses: ["100.64.0.2"],
          online: true,
          last_seen: "2026-09-13T11:59:00Z",
        },
      ],
    },
  };
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          authenticated: true,
          username: "ark",
          csrf_token: "csrf",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(withDevice), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

  render(<App />);

  expect(await screen.findByText("Laptop")).toBeInTheDocument();
  expect(screen.getByText("100.64.0.2")).toBeInTheDocument();
  expect(screen.getByText("1 / 1 online")).toBeInTheDocument();
});
