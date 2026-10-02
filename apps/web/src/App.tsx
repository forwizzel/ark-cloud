import { FormEvent, useEffect, useRef, useState } from "react";
import { formatNumber } from "./formatNumber";

import {
  fetchDashboard,
  fetchSession,
  login,
  logout,
  redeemInvite,
  refreshGoogleDrive,
  setupAccount,
  disconnectGoogleDrive,
  type Dashboard,
  type AuthSession,
  type GoogleDriveSummary,
  type IntegrationState,
  type ResourceUsage,
  type TailscaleDevice,
} from "./api";
import AppearanceControls from "./AppearanceControls";
import AccountPage from "./AccountPage";
import DriveWorkspace from "./DriveWorkspace";
import LocalFiles, { LocalStorageSummary } from "./LocalFiles";
import SystemInformationPage from "./SystemInformationPage";
import StorageAdministration from "./StorageAdministration";
import AdministrationTabs from "./AdministrationTabs";
import { administrationRoute } from "./administrationRoutes";
import arkCloudLogo from "../../../graphics/arkcloud-logo.svg?raw";

type DashboardState =
  | { phase: "loading" }
  | { phase: "ready"; dashboard: Dashboard }
  | { phase: "error"; message: string };

type SessionState =
  | { phase: "loading" }
  | { phase: "unauthenticated"; setupRequired?: boolean }
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
  const [activePage, setActivePage] = useState<
    | "overview"
    | "files"
    | "drive"
    | "system"
    | "account"
    | "administration"
    | "users"
  >("overview");
  const [connectionNotice, setConnectionNotice] = useState(readOAuthNotice);
  const [activeHash, setActiveHash] = useState(window.location.hash);
  const [signInNotice, setSignInNotice] = useState("");

  useEffect(() => {
    const onHashChange = () => {
      setActivePage(pageFromHash());
      setActiveHash(window.location.hash);
      scrollPageToTop();
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const showDashboard = () => {
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}`,
    );
    setActivePage("overview");
    setActiveHash("");
    scrollPageToTop();
  };

  useEffect(() => {
    fetchSession()
      .then((session) => {
        if (session.authenticated) {
          setActivePage(pageFromHash());
          setActiveHash(window.location.hash);
        }
        setSessionState(
          session.authenticated
            ? { phase: "authenticated", session }
            : {
                phase: "unauthenticated",
                setupRequired: session.setup_required,
              },
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

  const onLogin = (session: AuthSession, firstSetup = false) => {
    if (window.location.hash.startsWith("#administration") && !firstSetup) {
      setActivePage(pageFromHash());
      setActiveHash(window.location.hash);
    } else showDashboard();
    if (firstSetup) {
      window.location.hash = "administration";
      setActivePage("administration");
      setActiveHash("#administration");
    }
    setSignInNotice("");
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
    showDashboard();
    setSignInNotice("");
    setSessionState({ phase: "unauthenticated" });
    setDashboardState({ phase: "loading" });
  };

  if (sessionState.phase === "loading") {
    return (
      <main className="auth-frame auth-frame--loading">
        <p role="status">Checking Ark session…</p>
      </main>
    );
  }

  if (sessionState.phase === "unauthenticated") {
    return (
      <LoginScreen
        onLogin={onLogin}
        setupRequired={sessionState.setupRequired ?? false}
        notice={signInNotice}
      />
    );
  }

  return (
    <div className="app-frame">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          const main = document.getElementById("main-content");
          main?.focus();
          main?.scrollIntoView({ block: "start" });
        }}
      >
        Skip to main content
      </a>
      <aside className="side-rail">
        <a className="brand" href="/" aria-label="Ark Cloud dashboard">
          <span
            className="brand-logo brand-logo--rail"
            aria-hidden="true"
            dangerouslySetInnerHTML={{ __html: arkCloudLogo }}
          />
          <span className="brand-type" translate="no">
            <strong>ARK</strong>
            <small>CLOUD</small>
          </span>
        </a>

        <nav aria-label="Primary navigation">
          <a
            className={`nav-item ${activePage === "overview" ? "nav-item--active" : ""}`}
            href="#overview"
            aria-current={activePage === "overview" ? "page" : undefined}
            onClick={() => setActivePage("overview")}
          >
            <span className="nav-symbol" aria-hidden="true" />
            Dashboard
          </a>
          <a
            className={`nav-item ${activePage === "files" ? "nav-item--active" : ""}`}
            href="#local-files"
            aria-current={activePage === "files" ? "page" : undefined}
            onClick={() => setActivePage("files")}
          >
            <span className="nav-symbol" aria-hidden="true" />
            Local Files
          </a>
          <a
            className={`nav-item ${activePage === "drive" ? "nav-item--active" : ""}`}
            href="#drive-workspace"
            aria-current={activePage === "drive" ? "page" : undefined}
            onClick={() => setActivePage("drive")}
          >
            <span className="nav-symbol" aria-hidden="true" />
            Drive Workspace
          </a>
          <a
            className={`nav-item ${activePage === "system" ? "nav-item--active" : ""}`}
            href="#system-information"
            aria-label="System Information"
            aria-current={activePage === "system" ? "page" : undefined}
            onClick={() => setActivePage("system")}
          >
            <span className="nav-symbol" aria-hidden="true" />
            System Information
          </a>
          <a
            className={`nav-item ${activePage === "account" ? "nav-item--active" : ""}`}
            href="#account"
            aria-current={activePage === "account" ? "page" : undefined}
            onClick={() => setActivePage("account")}
          >
            Account
          </a>
          {sessionState.session.role === "admin" && (
            <a
              className={`nav-item ${activePage === "administration" || activePage === "users" ? "nav-item--active" : ""}`}
              href="#administration"
              aria-current={
                activePage === "administration" || activePage === "users"
                  ? "page"
                  : undefined
              }
            >
              Administration
            </a>
          )}
        </nav>

        <AppearanceControls />
      </aside>

      <main className="main-content" id="main-content" tabIndex={-1}>
        <header className="topbar">
          <div>
            <h1>
              {activePage === "overview"
                ? "Dashboard"
                : activePage === "files"
                  ? "Local Files"
                  : activePage === "drive"
                    ? "Drive Workspace"
                    : activePage === "system"
                      ? "System Information"
                      : activePage === "administration" ||
                          activePage === "users"
                        ? "Administration"
                        : "Account"}
            </h1>
          </div>
          <div className="topbar-actions">
            {activePage === "overview" && (
              <span className="last-check">
                {dashboardState.phase === "ready"
                  ? `Checked ${formatTime(dashboardState.dashboard.generated_at)}`
                  : dashboardState.phase === "error"
                    ? "Collection failed"
                    : "Collecting telemetry"}
              </span>
            )}
            {activePage === "overview" && (
              <button
                className="refresh-button"
                type="button"
                onClick={refresh}
              >
                Refresh
              </button>
            )}
            <button
              className="logout-button"
              data-discard-changes
              type="button"
              onClick={() => void onLogout()}
            >
              Log out
            </button>
          </div>
        </header>

        {connectionNotice && (
          <div
            className={`connection-notice connection-notice--${connectionNotice.tone}`}
            role="status"
          >
            <span>{connectionNotice.message}</span>
            <button
              type="button"
              onClick={() => setConnectionNotice(null)}
              aria-label="Dismiss connection notice"
            >
              Dismiss
            </button>
          </div>
        )}

        {activePage === "system" && <SystemInformationPage />}
        {activePage === "files" && (
          <LocalFiles
            csrfToken={sessionState.session.csrf_token ?? ""}
            isAdmin={sessionState.session.role === "admin"}
          />
        )}
        {(activePage === "administration" || activePage === "users") &&
          (sessionState.session.role === "admin" ? (
            <div className="administration-workspace">
              <AdministrationTabs route={activeHash} />
              <div
                id="administration-panel"
                role="tabpanel"
                aria-labelledby={`administration-tab-${activePage === "users" ? "users" : administrationRoute(activeHash).page === "overview" ? "overview" : "storage"}`}
                tabIndex={0}
              >
                {activePage === "administration" ? (
                  <StorageAdministration
                    csrfToken={sessionState.session.csrf_token ?? ""}
                    route={activeHash}
                  />
                ) : (
                  <AccountPage
                    session={sessionState.session}
                    usersOnly
                    onUpdate={(session) =>
                      setSessionState({ phase: "authenticated", session })
                    }
                    onPasswordChanged={() =>
                      setSessionState({ phase: "unauthenticated" })
                    }
                  />
                )}
              </div>
            </div>
          ) : (
            <p role="alert">
              Administrator access is required to manage storage and accounts.
            </p>
          ))}
        {activePage === "account" && (
          <AccountPage
            session={sessionState.session}
            onUpdate={(session) =>
              setSessionState({ phase: "authenticated", session })
            }
            onPasswordChanged={() => {
              setSignInNotice(
                "Password changed. Sign in with your new password.",
              );
              setSessionState({ phase: "unauthenticated" });
            }}
          />
        )}
        {activePage !== "system" &&
          activePage !== "files" &&
          activePage !== "account" &&
          activePage !== "administration" &&
          activePage !== "users" &&
          dashboardState.phase === "loading" && <LoadingDashboard />}
        {activePage !== "system" &&
          activePage !== "files" &&
          activePage !== "account" &&
          activePage !== "administration" &&
          activePage !== "users" &&
          dashboardState.phase === "error" && (
            <ErrorDashboard
              message={dashboardState.message}
              onRetry={refresh}
            />
          )}
        {dashboardState.phase === "ready" && activePage === "overview" && (
          <DashboardView
            dashboard={dashboardState.dashboard}
            csrfToken={sessionState.session.csrf_token ?? ""}
            onDashboardRefresh={refresh}
          />
        )}
        {dashboardState.phase === "ready" && activePage === "drive" && (
          <DriveWorkspace
            connected={
              dashboardState.dashboard.google_drive.state === "healthy" ||
              dashboardState.dashboard.google_drive.state === "unavailable"
            }
            csrfToken={sessionState.session.csrf_token ?? ""}
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
  const needsAttention =
    dashboard.integrations.filter(
      (integration) =>
        integration.state === "degraded" || integration.state === "unavailable",
    ).length + (dashboard.platform.database === "connected" ? 0 : 1);
  const unconfigured = dashboard.integrations.filter(
    (integration) => integration.state === "not_configured",
  ).length;
  return (
    <div className="dashboard-grid">
      <section className="system-banner panel" aria-labelledby="system-heading">
        <div className="system-identity">
          <div className="system-beacon" aria-hidden="true">
            <span />
          </div>
          <div>
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
        </div>
      </section>

      <section
        className="overview-panel panel"
        aria-labelledby="overview-heading"
      >
        <div className="overview-panel-head">
          <h2 id="overview-heading">Operational state</h2>
        </div>
        <p className="overview-summary">
          {needsAttention === 0
            ? "No active service issues"
            : `${needsAttention} ${needsAttention === 1 ? "check needs" : "checks need"} attention`}
        </p>
        {unconfigured > 0 && (
          <p className="overview-optional">
            {unconfigured} optional{" "}
            {unconfigured === 1 ? "integration" : "integrations"} not configured
          </p>
        )}
        <div className="overview-facts">
          <span>
            <i className="status-dot status-dot--healthy" aria-hidden="true" />
            API online
          </span>
          <span>
            <i
              className={`status-dot status-dot--${dashboard.platform.database === "connected" ? "healthy" : "unavailable"}`}
              aria-hidden="true"
            />
            Database{" "}
            {dashboard.platform.database === "connected"
              ? "connected"
              : "unavailable"}
          </span>
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
      <LocalStorageSummary />
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

function LoginScreen({
  onLogin,
  setupRequired,
  notice,
}: {
  onLogin: (session: AuthSession, firstSetup?: boolean) => void;
  setupRequired: boolean;
  notice: string;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [code, setCode] = useState("");
  const [mode, setMode] = useState<"login" | "setup" | "invite">(
    setupRequired ? "setup" : "login",
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const confirmationInput = useRef<HTMLInputElement>(null);
  const errorMessage = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (error && !error.startsWith("Passwords do not match."))
      errorMessage.current?.focus();
  }, [error]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (mode !== "login" && password !== confirmation) {
        setError("Passwords do not match. Re-enter the confirmation password.");
        confirmationInput.current?.focus();
        return;
      }
      onLogin(
        mode === "setup"
          ? await setupAccount(code, username, password)
          : mode === "invite"
            ? await redeemInvite(code, password)
            : await login(username, password),
        mode === "setup",
      );
    } catch (loginError: unknown) {
      setError(
        loginError instanceof Error ? loginError.message : "Unable to log in.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-frame" id="main-content">
      <form className="login-panel" onSubmit={(event) => void submit(event)}>
        <span
          className="brand-logo brand-logo--login"
          aria-hidden="true"
          dangerouslySetInnerHTML={{ __html: arkCloudLogo }}
        />
        <h1>
          {mode === "setup"
            ? "Set up Ark Cloud"
            : mode === "invite"
              ? "Accept invitation"
              : "Sign in"}
        </h1>
        {notice && <p role="status">{notice}</p>}
        {mode === "setup" && (
          <p>
            From this machine, run <code>./scripts/ark bootstrap</code> and
            enter the one-time code to create the first administrator.
          </p>
        )}
        {mode === "invite" && (
          <p>
            Ask your administrator for an invitation code. Choose a password for
            your new account.
          </p>
        )}
        {mode !== "invite" && (
          <label>
            Username
            <input
              name="username"
              spellCheck={false}
              autoCapitalize="none"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              maxLength={mode === "setup" ? 64 : 128}
              required
            />
          </label>
        )}
        {mode !== "login" && (
          <label>
            {mode === "setup" ? "Setup code" : "Invitation code"}
            <input
              name={mode === "setup" ? "setup-code" : "invitation-code"}
              spellCheck={false}
              autoCapitalize="none"
              required
              value={code}
              onChange={(event) => setCode(event.target.value)}
              autoComplete="off"
            />
          </label>
        )}
        <label>
          {mode === "login" ? "Password" : "New password"}
          <input
            name="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={
              mode === "login" ? "current-password" : "new-password"
            }
            minLength={mode === "login" ? undefined : 12}
            required
          />
        </label>
        {mode !== "login" && (
          <label>
            Confirm password
            <input
              ref={confirmationInput}
              name="password-confirmation"
              aria-invalid={Boolean(error && password !== confirmation)}
              aria-describedby={error ? "sign-in-error" : undefined}
              required
              type="password"
              autoComplete="new-password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </label>
        )}
        {error && (
          <p
            className="auth-error"
            role="alert"
            id="sign-in-error"
            ref={errorMessage}
            tabIndex={-1}
          >
            {error}
          </p>
        )}
        <button
          className="refresh-button"
          type="submit"
          disabled={submitting}
          aria-busy={submitting}
        >
          {submitting
            ? "Please wait…"
            : mode === "setup"
              ? "Create administrator"
              : mode === "invite"
                ? "Create account"
                : "Sign in"}
        </button>
        {!setupRequired && (
          <button
            type="button"
            className="auth-mode-switch"
            onClick={() => {
              setMode(mode === "invite" ? "login" : "invite");
              setError(null);
            }}
          >
            {mode === "invite" ? "Back to sign in" : "Redeem invitation"}
          </button>
        )}
        <AppearanceControls />
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
        description="Tailscale"
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
    if (
      !window.confirm(
        "Disconnect Google Drive? You’ll need to reconnect to access its metadata. Files in Google Drive stay unchanged.",
      )
    )
      return;
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
        title="Google Drive"
        aside={drive.state === "healthy" ? undefined : stateLabels[drive.state]}
        id="drive-heading"
      />
      <div className="drive-panel-body">
        <div className="drive-summary">
          <strong>
            {drive.account_name ?? drive.account_email ?? "Google Drive"}
          </strong>
          <p>{drive.message}</p>
        </div>
        {drive.used_bytes !== null && drive.total_bytes !== null && (
          <div className="drive-quota">
            <div>
              <span>Storage used</span>
              <strong>
                {formatBytes(drive.used_bytes)} /{" "}
                {formatBytes(drive.total_bytes)}
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
              <a className="drive-link" href="#drive-workspace">
                Open Drive workspace
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
  description,
  title,
  aside,
  id,
}: {
  description?: string;
  title: string;
  aside?: string;
  id: string;
}) {
  return (
    <div className="panel-heading">
      <div>
        <h2 id={id}>{title}</h2>
        {description && <p className="panel-description">{description}</p>}
      </div>
      {aside && <span>{aside}</span>}
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
  if (bytes < 1024) return `${formatNumber(bytes)}\u00a0B`;
  const units = ["KiB", "MiB", "GiB", "TiB", "PiB"];
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length,
  );
  const value = bytes / 1024 ** exponent;
  return `${formatNumber(value, value >= 10 ? 0 : 1)}\u00a0${units[exponent - 1]}`;
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

function pageFromHash():
  | "overview"
  | "files"
  | "drive"
  | "system"
  | "account"
  | "administration"
  | "users" {
  if (
    window.location.hash === "#administration-users" ||
    window.location.hash === "#administration/users"
  )
    return "users";
  if (
    window.location.hash === "#administration" ||
    window.location.hash.startsWith("#administration/")
  )
    return "administration";
  if (
    window.location.hash === "#local-files" ||
    window.location.hash.startsWith("#local-files/")
  )
    return "files";
  if (window.location.hash === "#drive-workspace") return "drive";
  if (window.location.hash === "#system-information") return "system";
  if (window.location.hash === "#account") return "account";
  return "overview";
}

function scrollPageToTop() {
  document.scrollingElement?.scrollTo?.({ top: 0, behavior: "instant" });
}

function readOAuthNotice(): {
  tone: "success" | "error";
  message: string;
} | null {
  const url = new URL(window.location.href);
  const outcome = url.searchParams.get("google_drive");
  const catalog = url.searchParams.get("catalog");
  if (!outcome) return null;

  url.searchParams.delete("google_drive");
  url.searchParams.delete("catalog");
  window.history.replaceState(
    {},
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );

  if (outcome === "connected") {
    return catalog === "failed"
      ? {
          tone: "error",
          message:
            "Google Drive connected, but the initial catalog sync failed. Open Drive Workspace to retry.",
        }
      : {
          tone: "success",
          message:
            "Google Drive connected. Ark Cloud is ready to index owned My Drive metadata.",
        };
  }
  const failures: Record<string, string> = {
    denied:
      "Google Drive access was not granted. Reconnect when you are ready.",
    invalid_state:
      "The Google Drive connection expired or could not be verified. Start the connection again.",
    failed:
      "Google Drive could not be connected. Check the server configuration and try again.",
  };
  return {
    tone: "error",
    message: failures[outcome] ?? "Google Drive connection did not complete.",
  };
}
