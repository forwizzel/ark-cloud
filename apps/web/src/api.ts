export type IntegrationState =
  "healthy" | "degraded" | "unavailable" | "not_configured";

export type IntegrationHealth = {
  id: string;
  name: string;
  state: IntegrationState;
  message: string;
  checked_at: string;
};

export type ResourceUsage = {
  total_bytes: number;
  used_bytes: number;
  available_bytes: number;
  percent: number;
};

export type SystemSummary = {
  hostname: string;
  os: string;
  kernel: string;
  uptime_seconds: number;
  cpu_percent: number;
  cpu_count: number;
  memory: ResourceUsage;
  storage: ResourceUsage;
  storage_path: string;
  scope: "api-runtime-view";
  collected_at: string;
};

export type TailscaleDevice = {
  id: string;
  hostname: string;
  os: string;
  addresses: string[];
  online: boolean;
  last_seen: string | null;
};

export type Dashboard = {
  platform: {
    status: "healthy" | "unhealthy";
    service: string;
    database: "connected" | "disconnected";
  };
  system: SystemSummary | null;
  tailscale: {
    state: IntegrationState;
    device_count: number;
    online_count: number;
    devices: TailscaleDevice[];
    message: string;
    collected_at: string;
  };
  integrations: IntegrationHealth[];
  generated_at: string;
};

export async function fetchDashboard(signal: AbortSignal): Promise<Dashboard> {
  const response = await fetch("/api/dashboard", { signal });
  if (!response.ok) {
    throw new Error("Ark API could not assemble the dashboard.");
  }
  return (await response.json()) as Dashboard;
}
