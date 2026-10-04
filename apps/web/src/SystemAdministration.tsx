import { useEffect, useEffectEvent, useRef, useState } from "react";
import { systemRequest, timestamp, type HostStatus } from "./systemApi";
import useUnsavedChanges from "./useUnsavedChanges";
import "./system-administration.css";

type Service = { unit: string; scope: "user" | "system"; actions: string[] };
type Configuration = {
  terminal: boolean;
  processes: boolean;
  power: boolean;
  shell: string;
  services: Service[];
};
type Job = {
  id: string;
  state: string;
  message: string;
  payload: { action: "connect" | "disconnect" };
};
export type SystemAdministrationStatus = {
  host: HostStatus & { collected_at: string | null };
  manager: {
    online: boolean;
    inventory: {
      supported: boolean;
      account: string;
      default_shell: string;
      shells: string[];
      services: Service[];
      power: boolean;
      message: string;
    } | null;
  };
  configuration: Configuration;
  jobs: Job[];
};
const active = (job: Job) =>
  ["queued", "applying", "verifying"].includes(job.state);
const failure = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "System configuration is unavailable. Try again.";

export default function SystemAdministration({
  csrfToken,
}: {
  csrfToken: string;
}) {
  const [status, setStatus] = useState<SystemAdministrationStatus | null>(null);
  const [draft, setDraft] = useState<Configuration | null>(null);
  const [dirty, setDirty] = useState(false);
  const [sending, setSending] = useState(false);
  const [pollError, setPollError] = useState("");
  const [actionError, setActionError] = useState("");
  const [query, setQuery] = useState("");
  const [refresh, setRefresh] = useState(0);
  const submitting = useRef(false);
  const mounted = useRef(true);
  const errorMessage = useRef<HTMLParagraphElement>(null);
  useUnsavedChanges(dirty);
  const accept = useEffectEvent((value: SystemAdministrationStatus) => {
    setStatus(value);
    setPollError("");
    if (!dirty) setDraft(value.configuration);
  });
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await systemRequest<SystemAdministrationStatus>(
          "/admin/system/configuration",
          csrfToken,
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted) accept(value);
      } catch (error) {
        if (!controller.signal.aborted) setPollError(failure(error));
      } finally {
        if (!controller.signal.aborted)
          timer = setTimeout(() => void poll(), 3000);
      }
    }
    void poll();
    return () => {
      mounted.current = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [csrfToken, refresh]);
  useEffect(() => {
    if (actionError) errorMessage.current?.focus();
  }, [actionError]);

  async function act(action: "connect" | "disconnect") {
    if (
      submitting.current ||
      !draft ||
      !status ||
      (action === "connect" && !status.manager.online)
    )
      return;
    if (
      action === "disconnect" &&
      !window.confirm(
        "Disconnect System? Active terminal sessions will close. Host files and saved settings are preserved.",
      )
    )
      return;
    if (
      action === "connect" &&
      status.host.state === "connected" &&
      !window.confirm(
        "Apply settings and reconnect System? This ends all active terminal sessions and briefly interrupts host readings and controls.",
      )
    )
      return;
    submitting.current = true;
    setSending(true);
    setActionError("");
    try {
      const job = await systemRequest<Job>(
        "/admin/system/configuration",
        csrfToken,
        {
          action,
          configuration: action === "connect" ? draft : undefined,
          idempotency_key: crypto.randomUUID(),
        },
      );
      if (!mounted.current) return;
      setStatus((current) =>
        current
          ? {
              ...current,
              jobs: [job, ...current.jobs],
              configuration:
                action === "connect" ? draft : current.configuration,
            }
          : current,
      );
      if (action === "connect") setDirty(false);
    } catch (error) {
      if (mounted.current) setActionError(failure(error));
    } finally {
      submitting.current = false;
      if (mounted.current) setSending(false);
    }
  }
  function change(value: Partial<Configuration>) {
    setDraft((current) => (current ? { ...current, ...value } : current));
    setDirty(true);
  }
  function select(service: Service, enabled: boolean) {
    if (!draft) return;
    change({
      services: [
        ...draft.services.filter(
          (item) => item.unit !== service.unit || item.scope !== service.scope,
        ),
        ...(enabled ? [{ ...service, actions: [...service.actions] }] : []),
      ],
    });
  }
  function selectAction(service: Service, action: string, enabled: boolean) {
    if (!draft) return;
    change({
      services: draft.services.map((item) =>
        item.unit === service.unit && item.scope === service.scope
          ? {
              ...item,
              actions: enabled
                ? [...item.actions, action]
                : item.actions.filter((value) => value !== action),
            }
          : item,
      ),
    });
  }

  if (!status || !draft)
    return (
      <section className="panel system-admin-panel">
        <h2>System configuration</h2>
        <p role={pollError ? "alert" : "status"}>
          {pollError || "Loading System configuration…"}
        </p>
        {pollError && (
          <button onClick={() => setRefresh(refresh + 1)}>Retry</button>
        )}
      </section>
    );
  const inventory = status.manager.inventory;
  const pending = status.jobs.find(active);
  const last = pending ?? status.jobs[0];
  const busy = sending || Boolean(pending);
  const ready =
    status.manager.online && Boolean(inventory?.supported) && !pollError;
  const connected = status.host.state === "connected";
  const configured = status.host.state !== "not_enrolled";
  const label = pending
    ? pending.payload.action === "disconnect"
      ? "Disconnecting"
      : "Connecting"
    : connected
      ? "Connected"
      : status.host.state === "offline"
        ? "Agent offline"
        : "Not connected";
  const available = [
    ...(inventory?.services ?? []),
    ...draft.services.filter(
      (item) =>
        !inventory?.services.some(
          (service) =>
            item.unit === service.unit && item.scope === service.scope,
        ),
    ),
  ];
  const applyLabel = busy
    ? "Applying…"
    : connected
      ? "Apply settings and reconnect"
      : last?.state === "failed"
        ? "Retry connection"
        : "Connect System";
  const reconnectWarning =
    "Applying settings reconnects the agent, ends active terminal sessions and briefly interrupts host readings and controls.";

  return (
    <div className="system-admin">
      <section
        className="panel system-admin-panel"
        aria-labelledby="system-admin-heading"
      >
        <header className="system-admin-heading">
          <div>
            <h2 id="system-admin-heading">System configuration</h2>
            <p>
              Connect ArkCloud to this host. ArkCloud prepares and manages the
              System agent automatically.
            </p>
          </div>
          <span
            className={`system-admin-state ${connected && !pending ? "system-admin-state--connected" : ""}`}
          >
            {label}
          </span>
        </header>
        <dl className="system-admin-facts">
          <div>
            <dt>Host account</dt>
            <dd>{inventory?.account ?? "Waiting for host management"}</dd>
          </div>
          <div>
            <dt>Host management</dt>
            <dd>
              {status.manager.online
                ? "Available"
                : pending
                  ? "Applying System settings"
                  : "Temporarily offline"}
            </dd>
          </div>
          <div>
            <dt>Last host reading</dt>
            <dd>
              {status.host.collected_at
                ? timestamp(status.host.collected_at)
                : "No readings yet"}
            </dd>
          </div>
        </dl>
        {!ready && !busy && (
          <p className="system-admin-notice" role="status">
            {inventory?.message ||
              "Waiting for deployment host management to reconnect. ArkCloud retries automatically."}
          </p>
        )}
        {pollError && (
          <p role="alert" className="system-admin-error">
            {pollError} Showing the last known configuration.
          </p>
        )}
        {actionError && (
          <p
            ref={errorMessage}
            tabIndex={-1}
            role="alert"
            className="system-admin-error"
          >
            {actionError}
          </p>
        )}
        {last && (
          <p
            role={last.state === "failed" ? "alert" : "status"}
            className={
              last.state === "failed"
                ? "system-admin-error"
                : "system-admin-notice"
            }
          >
            {last.message}
          </p>
        )}
        <div className="system-admin-actions">
          <a href="#system">Open System</a>
          {configured && (
            <button
              disabled={busy || Boolean(pollError)}
              onClick={() => void act("disconnect")}
            >
              Disconnect System
            </button>
          )}
          <button disabled={busy || !ready} onClick={() => void act("connect")}>
            {applyLabel}
          </button>
        </div>
        {configured && (
          <p className="system-admin-reconnect-warning">{reconnectWarning}</p>
        )}
      </section>
      <section
        className="panel system-admin-panel"
        aria-labelledby="system-access-heading"
      >
        <h2 id="system-access-heading">Host access</h2>
        <p>
          Host readings are available to signed-in users. Terminal and control
          actions are administrator-only.
        </p>
        <fieldset disabled={busy || !ready} className="system-admin-options">
          <legend className="sr-only">System access settings</legend>
          <div>
            <label className="system-admin-toggle">
              <input
                type="checkbox"
                checked={draft.terminal}
                onChange={(event) => change({ terminal: event.target.checked })}
              />
              <span>
                <strong>Terminal access</strong>
                <small>
                  Use the host account’s installed shell from System.
                </small>
              </span>
            </label>
            <label className="system-admin-shell">
              Installed shell
              <select
                value={draft.shell}
                onChange={(event) => change({ shell: event.target.value })}
              >
                <option value="">
                  Account default
                  {inventory?.default_shell
                    ? ` (${inventory.default_shell})`
                    : ""}
                </option>
                {inventory?.shells.map((shell) => (
                  <option key={shell} value={shell}>
                    {shell}
                  </option>
                ))}
                {draft.shell && !inventory?.shells.includes(draft.shell) && (
                  <option value={draft.shell}>
                    {draft.shell} (unavailable)
                  </option>
                )}
              </select>
            </label>
          </div>
          <div>
            <label className="system-admin-toggle">
              <input
                type="checkbox"
                checked={draft.processes}
                onChange={(event) =>
                  change({ processes: event.target.checked })
                }
              />
              <span>
                <strong>Process inspection and termination</strong>
                <small>
                  View host processes and send termination requests within the
                  account’s permissions.
                </small>
              </span>
            </label>
            <label className="system-admin-toggle">
              <input
                type="checkbox"
                checked={draft.power}
                disabled={!inventory?.power && !draft.power}
                onChange={(event) => change({ power: event.target.checked })}
              />
              <span>
                <strong>Restart and shutdown</strong>
                <small>
                  {inventory?.power
                    ? "Allow confirmed host power actions from System."
                    : "Unavailable under this host account’s current authorization."}
                </small>
              </span>
            </label>
          </div>
        </fieldset>
      </section>
      <section
        className="panel system-admin-panel"
        aria-labelledby="system-services-heading"
      >
        <div className="system-admin-heading">
          <div>
            <h2 id="system-services-heading">Selected services</h2>
            <p>
              Choose up to 32 available services administrators can control from
              System.
            </p>
          </div>
          <label className="system-admin-search">
            Find a service
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Service name or scope"
            />
          </label>
        </div>
        <fieldset disabled={busy || !ready} className="system-admin-services">
          <legend className="sr-only">
            Services available to the host account
          </legend>
          {available
            .filter((item) =>
              `${item.unit} ${item.scope}`
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map((service) => {
              const selected = draft.services.find(
                (item) =>
                  item.unit === service.unit && item.scope === service.scope,
              );
              const permitted = inventory?.services.find(
                (item) =>
                  item.unit === service.unit && item.scope === service.scope,
              );
              return (
                <div
                  className="system-admin-service"
                  key={`${service.scope}:${service.unit}`}
                >
                  <label className="system-admin-toggle">
                    <input
                      type="checkbox"
                      checked={Boolean(selected)}
                      disabled={
                        (!permitted && !selected) ||
                        (!selected && draft.services.length >= 32)
                      }
                      onChange={(event) =>
                        select(service, event.target.checked)
                      }
                    />
                    <span>
                      <strong>{service.unit}</strong>
                      <small>
                        {service.scope} service
                        {!permitted ? " · no longer available" : ""}
                      </small>
                    </span>
                  </label>
                  {selected && (
                    <div className="system-admin-service-actions">
                      {["start", "stop", "restart"].map((action) => (
                        <label key={action}>
                          <input
                            type="checkbox"
                            aria-label={`${action[0].toUpperCase() + action.slice(1)} ${service.unit} (${service.scope} service)`}
                            checked={selected.actions.includes(action)}
                            disabled={
                              !permitted?.actions.includes(action) &&
                              !selected.actions.includes(action)
                            }
                            onChange={(event) =>
                              selectAction(
                                service,
                                action,
                                event.target.checked,
                              )
                            }
                          />
                          {action[0].toUpperCase() + action.slice(1)}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
        </fieldset>
        {available.length === 0 && (
          <p className="system-admin-caption">
            {inventory
              ? "No controllable services are available under this host account."
              : "Waiting for host management to report available services."}
          </p>
        )}
        {available.length > 0 &&
          available.filter((item) =>
            `${item.unit} ${item.scope}`
              .toLowerCase()
              .includes(query.toLowerCase()),
          ).length === 0 && (
            <p className="system-admin-caption">
              No services match your search.
            </p>
          )}
      </section>
      <footer className="system-admin-footer">
        <p>
          {dirty
            ? `Unsaved changes. ${reconnectWarning}`
            : configured
              ? `Settings are saved. ${reconnectWarning}`
              : "Choose access options, then connect System. ArkCloud handles setup."}
        </p>
        <button
          disabled={busy || !ready || (!dirty && connected)}
          onClick={() => void act("connect")}
        >
          {applyLabel}
        </button>
      </footer>
    </div>
  );
}
