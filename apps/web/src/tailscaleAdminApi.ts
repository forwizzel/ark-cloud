export type TailscaleStatus = {
  configured: boolean;
  source: "ui" | "environment" | "none";
  integration_state: "available" | "unavailable" | "not_configured";
  integration_message: string | null;
  desired_enabled: boolean;
  revision: number;
  state:
    | "offline"
    | "connecting"
    | "approval_required"
    | "connected"
    | "disabled"
    | "disconnected"
    | "error";
  message: string;
  serve_url: string | null;
  approval_url: string | null;
  dns_name: string | null;
  node_id: string | null;
  controller_online: boolean;
};

export type TailscaleAction =
  "connect" | "enable" | "disable" | "disconnect" | "test";

export class TailscaleRequestError extends Error {
  constructor(public status: number) {
    super(
      status === 401
        ? "Your Ark session expired. Sign in again to manage Tailscale."
        : status === 403
          ? "Administrator access or a valid Ark session is required. Sign in again."
          : "Tailscale could not complete this request. Check the connection and try again.",
    );
  }
}

export async function tailscaleRequest(
  csrfToken: string,
  signal: AbortSignal,
  action?: TailscaleAction,
  apiKey?: string,
): Promise<TailscaleStatus> {
  const response = await fetch(
    `/api/admin/tailscale${action ? `/${action}` : ""}`,
    {
      method: action ? "POST" : "GET",
      headers: {
        "X-CSRF-Token": csrfToken,
        ...(action === "connect" ? { "Content-Type": "application/json" } : {}),
      },
      ...(action === "connect"
        ? { body: JSON.stringify({ api_key: apiKey }) }
        : {}),
      cache: "no-store",
      signal,
    },
  );
  // Never surface upstream error bodies: they can contain submitted credentials.
  if (!response.ok) throw new TailscaleRequestError(response.status);
  return (await response.json()) as TailscaleStatus;
}

export function privateHttpsUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
