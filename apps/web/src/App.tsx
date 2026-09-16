import { FormEvent, useEffect, useState } from "react";

import {
  fetchDashboard,
  fetchSession,
  login,
  logout,
  refreshGoogleDrive,
  disconnectGoogleDrive,
  type Dashboard,
  type AuthSession,
  type GoogleDriveSummary,
  type IntegrationState,
  type ResourceUsage,
  type TailscaleDevice,
} from "./api";

type DashboardState =
  | { phase: "loading" }
  | { phase: "ready"; dashboard: Dashboard }
  | { phase: "error"; message: string };

type SessionState =
  | { phase: "loading" }
  | { phase: "unauthenticated" }
  | { phase: "authenticated"; session: AuthSession };

const stateLabels: Record<IntegrationState, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  unavailable: "Unavailable",
  not_configured: "Not configured",
};

function App() {
  const [sessionState, setSessionState] = useState<SessionState>({
    phase: "loading",
  });
  const [dashboardState, setDashboardState] = useState<DashboardState>({
    phase: "loading",
  });
  const [requestNumber, setRequestNumber] = useState(0);

  useEffect(() => {
    fetchSession()
      .then((session) => {
        setSessionState(
          session.authenticated
            ? { phase: "authenticated", session }
            : { phase: "unauthenticated" },
        );
      })
      .catch(() => setSessionState({ phase: "unauthenticated" }));
  }, []);

  useEffect(() => {
    if (sessionState.phase !== "authenticated") return;
    const controller = new AbortController();
    fetchDashboard(controller.signal)
      .then((dashboard) => setDashboardState({ phase: "ready", dashboard }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setDashboardState({
            phase: "error",
            message:
              error instanceof Error
                ? error.message
                : "Dashboard data is unavailable.",
          });
        }
      });
    return () => controller.abort();
  }, [requestNumber, sessionState.phase]);

  const refresh = () => {
    setDashboardState({ phase: "loading" });
    setRequestNumber((value) => value + 1);
  };

  const onLogin = (session: AuthSession) => {
    setSessionState({ phase: "authenticated", session });
    setDashboardState({ phase: "loading" });
    setRequestNumber((value) => value + 1);
  };

  const onLogout = async () => {
    if (
      sessionState.phase !== "authenticated" ||
      !sessionState.session.csrf_token
    )
      return;
    await logout(sessionState.session.csrf_token);
    setSessionState({ phase: "unauthenticated" });
    setDashboardState({ phase: "loading" });
  };

  if (sessionState.phase === "loading") {
    return <div className="auth-frame">Checking Ark session</div>;
  }

  if (sessionState.phase === "unauthenticated") {
    return <LoginScreen onLogin={onLogin} />;
  }

  return (
    <div className="app-frame">
      <aside className="side-rail">
        <a className="brand" href="/" aria-label="Ark Cloud overview">
          <span className="brand-mark" aria-hidden="true">
            A
          </span>
          <span className="brand-type">
            <strong>ARK</strong>
            <small>CLOUD</small>
          </span>
        </a>

        <nav aria-label="Primary navigation">
          <a
            className="nav-item nav-item--active"
            href="#overview"
            aria-current="page"
          >
            <span aria-hidden="true">01</span>
            Overview
          </a>
        </nav>

        <div className="rail-foot">
          <span className="rail-pulse" aria-hidden="true" />
          http://127.0.0.1:5173
          <small>Phase 2 / v0.2</small>
        </div>
      </aside>

      <main className="main-content" id="overview">
        <header className="topbar">
          <div>
            <p className="eyebrow">Cloud</p>
            <h1>Dashboard</h1>
          </div>
          <div className="topbar-actions">
            <span className="last-check">
              {dashboardState.phase === "ready"
                ? `Checked ${formatTime(dashboardState.dashboard.generated_at)}`
                : dashboardState.phase === "error"
                  ? "Collection failed"
                  : "Collecting telemetry"}
            </span>
            <button className="refresh-button" type="button" onClick={refresh}>
              Refresh
            </button>
            <button
              className="logout-button"
              type="button"
              onClick={() => void onLogout()}
            >
              Log out
            </button>
          </div>
        </header>

        {dashboardState.phase === "loading" && <LoadingDashboard />}
        {dashboardState.phase === "error" && (
          <ErrorDashboard message={dashboardState.message} onRetry={refresh} />
        )}
        {dashboardState.phase === "ready" && (
          <DashboardView
            dashboard={dashboardState.dashboard}
            csrfToken={sessionState.session.csrf_token ?? ""}
            onDashboardRefresh={refresh}
          />
        )}
      </main>
    </div>
  );
}

function DashboardView({
  dashboard,
  csrfToken,
  onDashboardRefresh,
}: {
  dashboard: Dashboard;
  csrfToken: string;
  onDashboardRefresh: () => void;
}) {
  const system = dashboard.system;
  const systemHealth = dashboard.integrations.find(
    (integration) => integration.id === "system",
  );
  return (
    <div className="dashboard-grid">
      <section className="system-banner panel" aria-labelledby="system-heading">
        <div className="system-identity">
          <div className="system-beacon" aria-hidden="true">
            <span />
          </div>
          <div>
            <p className="section-label">Server</p>
            <div className="system-title-row">
              <h2 id="system-heading">{system?.hostname ?? "Ark"}</h2>
              <StatusPill state={systemHealth?.state ?? "unavailable"} />
            </div>
            <p className="system-meta">
              {system
                ? `${system.os} · Kernel ${system.kernel}`
                : systemHealth?.message || "System telemetry is unavailable."}
            </p>
          </div>
        </div>
        <div className="system-uptime">
          <span>Uptime</span>
          <strong>{system ? formatUptime(system.uptime_seconds) : "--"}</strong>
          <small>{system ? "API runtime" : "no telemetry"}</small>
        </div>
      </section>

      <section
        className="telemetry-grid"
        aria-label="System resource utilization"
      >
        <MetricCard
          label="CPU"
          value={system?.cpu_percent ?? null}
          detail={system ? `${system.cpu_count} logical cores` : "Unavailable"}
        />
        <MetricCard
          label="Memory"
          value={system?.memory.percent ?? null}
          detail={system ? usageDetail(system.memory) : "Unavailable"}
        />
        <MetricCard
          label="Storage"
          value={system?.storage.percent ?? null}
          detail={system ? usageDetail(system.storage) : "Unavailable"}
        />
      </section>

      <section
        className="services-panel panel"
        aria-labelledby="services-heading"
      >
        <PanelHeading
          eyebrow="Control panel"
          title="Services"
          aside={`${dashboard.integrations.length + 2} checks`}
          id="services-heading"
        />
        <div className="service-list">
          <ServiceRow
            name="Ark API"
            detail={dashboard.platform.service}
            state="healthy"
          />
          <ServiceRow
            name="PostgreSQL"
            detail="Database"
            state={
              dashboard.platform.database === "connected"
                ? "healthy"
                : "unavailable"
            }
          />
          {dashboard.integrations.map((integration) => (
            <ServiceRow
              key={integration.id}
              name={integration.name}
              detail={integration.message}
              state={integration.state}
            />
          ))}
        </div>
      </section>

      <TailscalePanel tailscale={dashboard.tailscale} />
      <GoogleDrivePanel
        drive={dashboard.google_drive}
        csrfToken={csrfToken}
        onDashboardRefresh={onDashboardRefresh}
      />

      <p className="scope-note">
        Metrics are the API runtime's view: CPU, memory, and uptime can be
        host-global, while storage can reflect the container filesystem. A
        dedicated host agent is planned for exact host telemetry.
      </p>
    </div>
  );
}

function LoginScreen({ onLogin }: { onLogin: (session: AuthSession) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      onLogin(await login(username, password));
    } catch (loginError: unknown) {
      setError(
        loginError instanceof Error ? loginError.message : "Unable to log in.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-frame">
      <form className="login-panel" onSubmit={(event) => void submit(event)}>
        <p className="eyebrow">Ark Cloud</p>
        <h1>Sign in</h1>
        <label>
          Username
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && (
          <p className="auth-error" role="alert">
            {error}
          </p>
        )}
        <button className="refresh-button" type="submit" disabled={submitting}>
          {submitting ? "Signing in" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: number | null;
  detail: string;
}) {
  const safeValue = value === null ? 0 : Math.min(100, Math.max(0, value));
  const tone =
    safeValue >= 90 ? "critical" : safeValue >= 75 ? "warning" : "normal";

  return (
    <article className={`metric-card metric-card--${tone}`}>
      <div className="metric-head">
        <span>{label}</span>
        <strong>{value === null ? "--" : `${Math.round(value)}%`}</strong>
      </div>
      <div
        className="meter"
        role="progressbar"
        aria-label={`${label} percentage`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value === null ? undefined : Math.round(value)}
        aria-valuetext={
          value === null ? "Unavailable" : `${Math.round(value)} percent`
        }
      >
        <span style={{ width: `${safeValue}%` }} />
      </div>
      <small>{detail}</small>
    </article>
  );
}

function ServiceRow({
  name,
  detail,
  state,
}: {
  name: string;
  detail: string;
  state: IntegrationState;
}) {
  return (
    <div className="service-row">
      <span className={`status-dot status-dot--${state}`} aria-hidden="true" />
      <div>
        <strong>{name}</strong>
        <small>{detail}</small>
      </div>
      <StatusPill state={state} />
    </div>
  );
}

function TailscalePanel({ tailscale }: { tailscale: Dashboard["tailscale"] }) {
  return (
    <section className="devices-panel panel" aria-labelledby="devices-heading">
      <PanelHeading
        eyebrow="Private network"
        title="Devices"
        aside={
          tailscale.state === "healthy"
            ? `${tailscale.online_count} / ${tailscale.device_count} online`
            : stateLabels[tailscale.state]
        }
        id="devices-heading"
      />

      {tailscale.state !== "healthy" ? (
        <div className="integration-empty">
          <span className="empty-mark" aria-hidden="true">
            TS
          </span>
          <div>
            <strong>{stateLabels[tailscale.state]}</strong>
            <p>{tailscale.message}</p>
          </div>
        </div>
      ) : tailscale.devices.length === 0 ? (
        <div className="integration-empty">
          <div>
            <strong>No devices returned</strong>
            <p>
              The Tailscale connection is healthy, but the tailnet is empty.
            </p>
          </div>
        </div>
      ) : (
        <div className="device-list">
          {tailscale.devices.map((device) => (
            <DeviceRow key={device.id} device={device} />
          ))}
        </div>
      )}
    </section>
  );
}

function GoogleDrivePanel({
  drive,
  csrfToken,
  onDashboardRefresh,
}: {
  drive: GoogleDriveSummary;
  csrfToken: string;
  onDashboardRefresh: () => void;
}) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const connected = drive.state === "healthy" || drive.state === "unavailable";

  const refresh = async () => {
    setActing(true);
    setActionError(null);
    try {
      await refreshGoogleDrive(csrfToken);
      onDashboardRefresh();
    } catch (error: unknown) {
      setActionError(
        error instanceof Error
          ? error.message
          : "Unable to refresh Google Drive.",
      );
    } finally {
      setActing(false);
    }
  };

  const disconnect = async () => {
    setActing(true);
    setActionError(null);
    try {
      await disconnectGoogleDrive(csrfToken);
      onDashboardRefresh();
    } catch (error: unknown) {
      setActionError(
        error instanceof Error
          ? error.message
          : "Unable to disconnect Google Drive.",
      );
    } finally {
      setActing(false);
    }
  };

  return (
    <section className="drive-panel panel" aria-labelledby="drive-heading">
      <PanelHeading
        eyebrow="External storage"
        title="Google Drive"
        aside={stateLabels[drive.state]}
        id="drive-heading"
      />
      <div className="drive-summary">
        <StatusPill state={drive.state} />
        <div>
          <strong>
            {drive.account_name ?? drive.account_email ?? "Google Drive"}
          </strong>
          <p>{drive.message}</p>
        </div>
      </div>
      {drive.used_bytes !== null && drive.total_bytes !== null && (
        <div className="drive-quota">
          <div>
            <span>Storage used</span>
            <strong>
              {formatBytes(drive.used_bytes)} / {formatBytes(drive.total_bytes)}
            </strong>
          </div>
          <div
            className="meter"
            role="progressbar"
            aria-label="Google Drive storage used"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={
              drive.percent === null ? undefined : Math.round(drive.percent)
            }
          >
            <span
              style={{
                width: `${Math.min(100, Math.max(0, drive.percent ?? 0))}%`,
              }}
            />
          </div>
        </div>
      )}
      {actionError && (
        <p className="auth-error" role="alert">
          {actionError}
        </p>
      )}
      <div className="drive-actions">
        {connected ? (
          <>
            <button
              type="button"
              className="refresh-button"
              onClick={() => void refresh()}
              disabled={acting}
            >
              Refresh
            </button>
            <a
              className="drive-link"
              href={drive.web_url}
              target="_blank"
              rel="noreferrer"
            >
              Open Google Drive
            </a>
            <button
              type="button"
              className="quiet-button"
              onClick={() => void disconnect()}
              disabled={acting}
            >
              Disconnect
            </button>
          </>
        ) : (
          <a
            className="refresh-button drive-connect"
            href="/api/integrations/google-drive/connect"
          >
            Connect Google Drive
          </a>
        )}
      </div>
    </section>
  );
}

function DeviceRow({ device }: { device: TailscaleDevice }) {
  return (
    <div className="device-row">
      <span
        className={`device-state ${device.online ? "device-state--online" : ""}`}
        aria-hidden="true"
      />
      <div className="device-name">
        <strong>{device.hostname}</strong>
        <small>{device.addresses[0] ?? "No address"}</small>
      </div>
      <span className="device-os">{device.os}</span>
      <span className="device-seen">
        <span className="visually-hidden">
          {device.online ? "Online" : "Offline"}:{" "}
        </span>
        {device.online ? "Now" : formatLastSeen(device.last_seen)}
      </span>
    </div>
  );
}

function PanelHeading({
  eyebrow,
  title,
  aside,
  id,
}: {
  eyebrow: string;
  title: string;
  aside: string;
  id: string;
}) {
  return (
    <div className="panel-heading">
      <div>
        <p className="section-label">{eyebrow}</p>
        <h2 id={id}>{title}</h2>
      </div>
      <span>{aside}</span>
    </div>
  );
}

function StatusPill({ state }: { state: IntegrationState }) {
  return (
    <span className={`status-pill status-pill--${state}`}>
      {stateLabels[state]}
    </span>
  );
}

function LoadingDashboard() {
  return (
    <div className="loading-dashboard" role="status">
      <span className="loading-line" />
      <strong>Reading Ark telemetry</strong>
      <small>Checking integrations and system resources</small>
    </div>
  );
}

function ErrorDashboard({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="error-dashboard" role="alert">
      <span className="empty-mark" aria-hidden="true">
        !
      </span>
      <h2>Dashboard unavailable</h2>
      <p>{message}</p>
      <button type="button" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

function usageDetail(usage: ResourceUsage): string {
  return `${formatBytes(usage.used_bytes)} of ${formatBytes(usage.total_bytes)} used`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB", "PiB"];
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length,
  );
  const value = bytes / 1024 ** exponent;
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[exponent - 1]}`;
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function formatLastSeen(value: string | null): string {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export default App;
