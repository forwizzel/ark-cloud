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

export type SystemSection = {
  availability: "available" | "partial" | "unavailable";
  source: "configured" | "runtime" | "kernel_view" | "filesystem";
  warning: string | null;
};

export type SystemInformation = {
  scope: "api-runtime-view";
  collected_at: string;
  identity: SystemSection & {
    hostname: string;
    os: string;
    kernel: string | null;
    architecture: string | null;
    python_version: string;
    api_version: string;
    host_uptime_seconds: number | null;
  };
  compute: SystemSection & {
    model: string | null;
    gpus: string[];
    logical_cores: number | null;
    percent: number | null;
    load_average: [number, number, number] | null;
    frequency_mhz: number | null;
  };
  memory: SystemSection & {
    usage: ResourceUsage | null;
    swap: ResourceUsage | null;
  };
  storage: SystemSection & {
    path: string;
    usage: ResourceUsage | null;
    filesystem_type: string | null;
  };
  sensors: SystemSection & {
    temperatures: { label: string; source_name: string; celsius: number }[];
  };
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

export type AuthSession = {
  authenticated: boolean;
  username: string | null;
  csrf_token: string | null;
  role?: "admin" | "member" | null;
  setup_required?: boolean;
};

export type LocalUser = {
  id: string;
  username: string;
  role: "admin" | "member";
  active: boolean;
  pending: boolean;
};

async function apiResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(payload?.detail ?? "Ark API request failed.");
  }
  return (await response.json()) as T;
}

export async function fetchSession(): Promise<AuthSession> {
  return apiResponse<AuthSession>(await fetch("/api/auth/session"));
}

export async function login(
  username: string,
  password: string,
): Promise<AuthSession> {
  return apiResponse<AuthSession>(
    await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),
  );
}

export async function setupAccount(
  code: string,
  username: string,
  password: string,
): Promise<AuthSession> {
  return apiResponse<AuthSession>(
    await fetch("/api/auth/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, username, password }),
    }),
  );
}

export async function redeemInvite(
  token: string,
  password: string,
): Promise<AuthSession> {
  return apiResponse<AuthSession>(
    await fetch("/api/auth/invite/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password }),
    }),
  );
}

async function accountRequest<T>(
  path: string,
  method: string,
  csrfToken: string,
  body: object,
): Promise<T> {
  const response = await fetch(`/api/auth/${path}`, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  return apiResponse<T>(response);
}

export function changeUsername(
  username: string,
  currentPassword: string,
  csrf: string,
): Promise<AuthSession> {
  return accountRequest<AuthSession>("account/username", "PUT", csrf, {
    username,
    current_password: currentPassword,
  });
}

export function changePassword(
  currentPassword: string,
  newPassword: string,
  csrf: string,
): Promise<void> {
  return accountRequest<void>("account/password", "PUT", csrf, {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export async function listUsers(): Promise<LocalUser[]> {
  return apiResponse<LocalUser[]>(await fetch("/api/auth/users"));
}

export function inviteUser(
  username: string,
  role: "admin" | "member",
  csrf: string,
): Promise<{ token: string }> {
  return accountRequest<{ token: string }>("users", "POST", csrf, {
    username,
    role,
  });
}

export function reissueInvite(
  id: string,
  csrf: string,
): Promise<{ token: string }> {
  return accountRequest<{ token: string }>(
    `users/${encodeURIComponent(id)}/invite`,
    "POST",
    csrf,
    {},
  );
}

export function updateUser(
  id: string,
  changes: { role?: "admin" | "member"; active?: boolean },
  csrf: string,
): Promise<LocalUser> {
  return accountRequest<LocalUser>(
    `users/${encodeURIComponent(id)}`,
    "PATCH",
    csrf,
    changes,
  );
}

export function deleteUser(
  id: string,
  confirmUsername: string,
  currentPassword: string,
  csrf: string,
): Promise<void> {
  return accountRequest<void>(
    `users/${encodeURIComponent(id)}`,
    "DELETE",
    csrf,
    {
      confirm_username: confirmUsername,
      current_password: currentPassword,
    },
  );
}

export async function logout(csrfToken: string): Promise<void> {
  const response = await fetch("/api/auth/logout", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
  if (!response.ok && response.status !== 204) {
    throw new Error("Unable to log out.");
  }
}

export async function fetchDashboard(signal: AbortSignal): Promise<Dashboard> {
  const response = await fetch("/api/dashboard", { signal });
  if (!response.ok) {
    throw new Error("Ark API could not assemble the dashboard.");
  }
  return (await response.json()) as Dashboard;
}

export async function fetchSystemInformation(
  signal?: AbortSignal,
): Promise<SystemInformation> {
  return apiResponse<SystemInformation>(
    await fetch("/api/system/information", { signal }),
  );
}
