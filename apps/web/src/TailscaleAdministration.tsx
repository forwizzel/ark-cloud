import { useEffect, useRef, useState } from "react";
import {
  privateHttpsUrl,
  tailscaleRequest,
  TailscaleRequestError,
  type TailscaleAction,
  type TailscaleStatus,
} from "./tailscaleAdminApi";
import useUnsavedChanges from "./useUnsavedChanges";
import "./tailscale-administration.css";

const labels: Record<TailscaleStatus["state"], string> = {
  offline: "Controller offline",
  connecting: "Connecting",
  approval_required: "HTTPS approval required",
  connected: "Connected",
  disabled: "Disabled",
  disconnected: "Disconnected",
  error: "Connection error",
};
const integrationLabels = {
  available: "Available",
  unavailable: "Unavailable",
  not_configured: "Not configured",
};

export default function TailscaleAdministration({
  csrfToken,
}: {
  csrfToken: string;
}) {
  const [status, setStatus] = useState<TailscaleStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [pollError, setPollError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [acting, setActing] = useState<TailscaleAction | null>(null);
  const [accessDenied, setAccessDenied] = useState(false);
  const request = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const authFailed = useRef(false);
  const errorMessage = useRef<HTMLParagraphElement | null>(null);
  useUnsavedChanges(Boolean(apiKey));

  useEffect(() => {
    if (actionError) errorMessage.current?.focus();
  }, [actionError]);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    authFailed.current = false;
    const poll = async () => {
      if (!busy.current && !authFailed.current) {
        const controller = new AbortController();
        request.current = controller;
        try {
          const next = await tailscaleRequest(csrfToken, controller.signal);
          if (!disposed && !controller.signal.aborted) {
            setStatus(next);
            setPollError(null);
            setAccessDenied(false);
          }
        } catch (error) {
          if (!disposed && !controller.signal.aborted) {
            authFailed.current =
              error instanceof TailscaleRequestError &&
              [401, 403].includes(error.status);
            setAccessDenied(authFailed.current);
            setPollError(
              authFailed.current
                ? (error as Error).message
                : "Live status is unavailable. The last known state may be out of date. Retrying automatically…",
            );
          }
        }
      }
      if (!disposed) timer = setTimeout(() => void poll(), 3000);
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
      request.current?.abort();
    };
  }, [csrfToken]);

  const act = async (action: TailscaleAction) => {
    if (busy.current || authFailed.current) return;
    if (action === "connect" && !apiKey.trim()) {
      setActionError("Enter a Tailscale API key, then try again.");
      return;
    }
    if (
      (action === "disable" || action === "disconnect") &&
      !window.confirm(
        action === "disable"
          ? "Disable private access? Sessions using the Tailscale URL will lose access, including this session if you are connected remotely. The saved API key is kept."
          : "Disconnect Tailscale? This removes the saved credentials and logs out the managed node. Sessions using the Tailscale URL will lose access, including this session if you are connected remotely.",
      )
    )
      return;
    busy.current = true;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setActing(action);
    setActionError(null);
    setNotice("");
    try {
      const next = await tailscaleRequest(
        csrfToken,
        controller.signal,
        action,
        action === "connect" ? apiKey : undefined,
      );
      if (controller.signal.aborted) return;
      setStatus(next);
      setPollError(null);
      if (action === "connect") setApiKey("");
      setNotice(
        action === "test"
          ? "Stored API key tested. Integration status updated."
          : action === "connect"
            ? "API key saved. Private access is enabled; Ark is connecting automatically."
            : "Private access settings updated.",
      );
    } catch (error) {
      if (controller.signal.aborted) return;
      const denied =
        error instanceof TailscaleRequestError &&
        [401, 403].includes(error.status);
      const validationFailed =
        action === "connect" &&
        error instanceof TailscaleRequestError &&
        [400, 422].includes(error.status);
      if (denied) {
        authFailed.current = true;
        setAccessDenied(true);
      }
      setActionError(
        denied
          ? (error as Error).message
          : validationFailed
            ? "Could not validate and save this API key. Any existing saved key is retained. Check the key and try again."
            : "Could not confirm the change. Remote access may have been interrupted. Check the current status from local access before retrying.",
      );
      if (!validationFailed)
        setPollError(
          denied
            ? (error as Error).message
            : "Live status is unavailable. The last known state may be out of date. Retrying automatically…",
        );
    } finally {
      busy.current = false;
      if (!controller.signal.aborted) setActing(null);
    }
  };

  const serveUrl = privateHttpsUrl(status?.serve_url ?? null);
  const approvalUrl = privateHttpsUrl(status?.approval_url ?? null);
  const copyUrl = async () => {
    if (!serveUrl) return;
    try {
      await navigator.clipboard.writeText(serveUrl);
      setNotice("Private URL copied.");
    } catch {
      setNotice("Could not copy the URL. Select and copy it above.");
    }
  };
  const blocked = Boolean(acting) || accessDenied;
  return (
    <div className="storage-admin tailscale-admin">
      <header className="storage-admin-intro">
        <div>
          <h2>Tailscale</h2>
          <p>
            Private HTTPS access to Ark Cloud from devices on your tailnet. An
            Ark sign-in is still required.
          </p>
        </div>
      </header>
      {pollError && (
        <p className="auth-error" role="alert">
          {pollError}
        </p>
      )}
      {!status && !pollError && <p role="status">Checking Tailscale…</p>}
      {status && (
        <section
          className="panel storage-section"
          aria-labelledby="tailscale-access-heading"
        >
          <div className="storage-section-heading">
            <h3 id="tailscale-access-heading">Private access</h3>
            <span
              className={`status-pill status-pill--${pollError || !status.controller_online ? "unavailable" : status.state === "connected" ? "healthy" : status.state === "error" ? "unavailable" : "not_configured"}`}
              role="status"
            >
              {pollError
                ? "Status unknown"
                : !status.controller_online
                  ? "Controller offline"
                  : labels[status.state]}
            </span>
          </div>
          <p>{status.message}</p>
          {pollError && <p>Details below show the last known state.</p>}
          <dl className="tailscale-facts">
            <div>
              <dt>Controller</dt>
              <dd>{status.controller_online ? "Online" : "Offline"}</dd>
            </div>
            <div>
              <dt>Private access setting</dt>
              <dd>{status.desired_enabled ? "Enabled" : "Disabled"}</dd>
            </div>
            {status.dns_name && (
              <div>
                <dt>Managed node</dt>
                <dd translate="no">{status.dns_name}</dd>
              </div>
            )}
          </dl>
          {status.state === "approval_required" && (
            <div className="tailscale-approval">
              <h4>Approve HTTPS in Tailscale</h4>
              <p>
                Tailscale needs your approval before Ark can finish enabling
                private HTTPS. Return here after approval; status updates
                automatically.
              </p>
              {approvalUrl ? (
                <a
                  className="workspace-link"
                  href={approvalUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Approve HTTPS in Tailscale (opens in a new tab)
                </a>
              ) : (
                <p>
                  An approval link is not available yet. Ark will show it here
                  when the controller provides one.
                </p>
              )}
            </div>
          )}
          {serveUrl && (
            <div className="tailscale-url">
              <h4>Private URL</h4>
              <p translate="no">{serveUrl}</p>
              <div className="workspace-actions">
                <a
                  className="workspace-link"
                  href={serveUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open private URL
                </a>
                <button type="button" onClick={() => void copyUrl()}>
                  Copy private URL
                </button>
              </div>
            </div>
          )}
          {status.configured && (
            <div className="workspace-actions">
              <button
                type="button"
                disabled={blocked || !status.controller_online}
                onClick={() =>
                  void act(status.desired_enabled ? "disable" : "enable")
                }
              >
                {acting === "enable" || acting === "disable"
                  ? "Updating…"
                  : status.desired_enabled
                    ? "Disable private access"
                    : "Enable private access"}
              </button>
              <button
                type="button"
                disabled={blocked}
                onClick={() => void act("disconnect")}
              >
                {acting === "disconnect"
                  ? "Disconnecting…"
                  : "Disconnect Tailscale"}
              </button>
            </div>
          )}
        </section>
      )}
      <section
        className="panel storage-section"
        aria-labelledby="tailscale-key-heading"
      >
        <div className="storage-section-heading">
          <h3 id="tailscale-key-heading">
            {status?.configured ? "API key" : "Connect Tailscale"}
          </h3>
        </div>
        {actionError && (
          <p
            className="auth-error"
            role="alert"
            ref={errorMessage}
            tabIndex={-1}
            id="tailscale-action-error"
          >
            {actionError}
          </p>
        )}
        <p>
          Enter a Tailscale API key. Ark validates and saves it server-side,
          connects a dedicated managed node, and enables Tailscale Serve
          automatically. Occasionally, Tailscale may ask you to approve HTTPS
          through a link shown here.
        </p>
        {status?.source === "environment" && (
          <p>
            Device inventory currently uses an environment-provided key. Saving
            a key here replaces that integration with UI-managed configuration
            and enables private access.
          </p>
        )}
        {status?.source === "ui" && (
          <p>
            An API key is saved server-side. Replace it below; the existing key
            is retained if validation fails.
          </p>
        )}
        {status && (
          <div className="tailscale-integration">
            <h4>API integration</h4>
            <span
              className={`status-pill status-pill--${status.integration_state === "available" ? "healthy" : status.integration_state}`}
            >
              {integrationLabels[status.integration_state]}
            </span>
            <p>
              {status.integration_message ??
                "This status describes API access, separately from the managed node’s private connection."}
            </p>
            {status.configured && (
              <button
                type="button"
                disabled={blocked}
                onClick={() => void act("test")}
              >
                {acting === "test" ? "Testing…" : "Test saved API key"}
              </button>
            )}
          </div>
        )}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void act("connect");
          }}
        >
          <label htmlFor="tailscale-api-key">
            {status?.configured ? "New Tailscale API key" : "Tailscale API key"}
          </label>
          <input
            id="tailscale-api-key"
            name="tailscale-api-key"
            type="password"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            required
            value={apiKey}
            onChange={(event) => {
              setApiKey(event.target.value);
              setActionError(null);
            }}
            aria-describedby={
              actionError
                ? "tailscale-key-note tailscale-action-error"
                : "tailscale-key-note"
            }
            disabled={Boolean(acting)}
          />
          <p id="tailscale-key-note">
            The key is never shown again after saving.
          </p>
          <div className="workspace-actions">
            <button
              className="refresh-button"
              type="submit"
              disabled={blocked || !status}
              aria-busy={acting === "connect"}
            >
              {acting === "connect"
                ? "Validating and connecting…"
                : status?.configured
                  ? "Replace key and connect"
                  : "Connect Tailscale"}
            </button>
            {apiKey && (
              <button
                type="button"
                disabled={Boolean(acting)}
                onClick={() => setApiKey("")}
              >
                Clear input
              </button>
            )}
          </div>
        </form>
      </section>
      <p role="status">{notice}</p>
    </div>
  );
}
