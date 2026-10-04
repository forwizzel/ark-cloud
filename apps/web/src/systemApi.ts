import type { ResourceUsage } from "./api";

export type HostPolicy = {
  terminal: boolean;
  power: boolean;
  processes: boolean;
  shell: string;
  account: string;
  services: { unit: string; scope: "user" | "system"; actions: string[] }[];
};
export type HostSnapshot = {
  scope: "host";
  boot_id: string;
  collected_at: string;
  identity: {
    hostname: string;
    os: string;
    kernel: string;
    architecture: string;
    boot_time: string;
    uptime_seconds: number;
  };
  compute: {
    model: string | null;
    physical_cores: number | null;
    logical_cores: number | null;
    sockets: number | null;
    percent: number | null;
    per_core: number[];
    frequency_mhz: number | null;
    load_average: number[] | null;
    gpus: string[];
  };
  memory: {
    usage: ResourceUsage | null;
    swap: ResourceUsage | null;
    cached_bytes: number | null;
    buffers_bytes: number | null;
    swap_in_bytes: number | null;
    swap_out_bytes: number | null;
  };
  temperatures: {
    id: string;
    group: string;
    label: string;
    source_name: string;
    celsius: number;
    high: number | null;
    critical: number | null;
  }[];
  mounts: {
    id: string;
    path: string;
    device: string;
    filesystem: string;
    options: string;
    usage: ResourceUsage | null;
  }[];
  omitted_mounts: string[];
  disk_io: {
    device: string;
    read_bytes: number;
    write_bytes: number;
    read_bytes_per_second: number | null;
    write_bytes_per_second: number | null;
  }[];
  warnings: string[];
};
export type HostInformation = {
  state: "not_enrolled" | "connected" | "offline" | "revoked";
  scope: "host";
  collected_at: string | null;
  snapshot: HostSnapshot | null;
  history: {
    collected_at: string;
    cpu: number | null;
    memory: number | null;
  }[];
};
export type HostStatus = { state: string; policy: HostPolicy | null };
export type HostService = {
  unit: string;
  scope: "user" | "system";
  state: string;
  actions: string[];
};
export type HostProcess = {
  pid: number;
  started_at: number;
  owner: string;
  name: string;
  percent: number | null;
  memory_bytes: number;
  state: string;
};
export type HostAction =
  | {
      action: "service";
      unit: string;
      scope: "user" | "system";
      operation: string;
    }
  | { action: "terminate"; pid: number; started_at: number }
  | { action: "restart" | "shutdown" };
export type HostJob = {
  id: string;
  state: string;
  message: string;
  payload: HostAction;
};
export type TerminalGrant = {
  id: string;
  grant: string;
  reconnect_seconds: number;
};

export class SystemRequestError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "SystemRequestError";
  }
}

export async function systemRequest<T>(
  path: string,
  csrf = "",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok)
    throw new SystemRequestError(
      payload?.detail ?? "System request failed. Try again.",
      response.status,
    );
  if (payload === null)
    throw new Error(
      "System returned an unreadable response. Retry to verify the result.",
    );
  return payload as T;
}

export function bytes(value: number | null | undefined): string {
  if (value == null) return "—";
  const exponent =
    value > 0 ? Math.min(4, Math.floor(Math.log(value) / Math.log(1024))) : 0;
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value / 1024 ** exponent)}\u00a0${["B", "KiB", "MiB", "GiB", "TiB"][exponent]}`;
}

export function number(value: number | null | undefined, suffix = ""): string {
  return value == null
    ? "—"
    : `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value)}${suffix}`;
}

export function timestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}
