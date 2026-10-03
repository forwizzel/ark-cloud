import { useEffect, useRef, useState } from "react";
import {
  bytes,
  number,
  timestamp,
  systemRequest,
  type HostAction,
  type HostJob,
  type HostPolicy,
  type HostProcess,
  type HostService,
} from "./systemApi";

export default function SystemControls({
  csrf,
  policy,
  live,
  hostname,
}: {
  csrf: string;
  policy: HostPolicy | null;
  live: boolean;
  hostname: string;
}) {
  const [services, setServices] = useState<HostService[]>([]);
  const [processes, setProcesses] = useState<HostProcess[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("memory");
  const [shown, setShown] = useState(20);
  const [error, setError] = useState("");
  const [job, setJob] = useState<HostJob | null>(null);
  const [confirmation, setConfirmation] = useState<{
    action: HostAction;
    title: string;
    detail: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const pending =
    busy || job?.state === "accepted" || job?.state === "dispatched";

  useEffect(() => {
    const controller = new AbortController();
    let active = false;
    async function refresh() {
      if (!live || document.hidden || active) return;
      active = true;
      try {
        const [units, tasks] = await Promise.all([
          systemRequest<{ items: HostService[] }>(
            "/admin/system/services",
            csrf,
            undefined,
            controller.signal,
          ),
          policy?.processes
            ? systemRequest<{ items: HostProcess[] }>(
                "/admin/system/processes?limit=2048",
                csrf,
                undefined,
                controller.signal,
              )
            : Promise.resolve({ items: [] }),
        ]);
        setServices(units.items);
        setProcesses(tasks.items);
        setError("");
      } catch (cause) {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : "Host controls unavailable.",
          );
      } finally {
        active = false;
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [csrf, live, policy?.processes]);

  useEffect(() => {
    if (!job || !["accepted", "dispatched", "unknown"].includes(job.state))
      return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      void systemRequest<HostJob>(
        `/admin/system/jobs/${job.id}`,
        csrf,
        undefined,
        controller.signal,
      )
        .then(setJob)
        .catch((cause) => {
          if (!controller.signal.aborted)
            setError(
              cause instanceof Error
                ? cause.message
                : "Could not check operation.",
            );
        });
    }, 2000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [csrf, job]);

  useEffect(() => {
    if (confirmation) dialog.current?.showModal();
    else dialog.current?.close();
  }, [confirmation]);

  async function submit(action: HostAction) {
    setBusy(true);
    setError("");
    setConfirmation(null);
    try {
      setJob(
        await systemRequest<HostJob>("/admin/system/jobs", csrf, {
          payload: action,
          idempotency_key: crypto.randomUUID(),
        }),
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Host operation failed.",
      );
    } finally {
      setBusy(false);
    }
  }
  const rows = processes
    .filter((p) =>
      `${p.name} ${p.owner} ${p.pid}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "cpu"
        ? (b.percent ?? -1) - (a.percent ?? -1)
        : sort === "pid"
          ? a.pid - b.pid
          : b.memory_bytes - a.memory_bytes,
    );

  return (
    <section className="host-controls" aria-label="Host controls">
      <div className="host-panel-heading">
        <h2>Host controls</h2>
        <span className="host-caption">Administrator workspace</span>
      </div>
      {error && (
        <p role="alert" className="system-warning">
          {error}
        </p>
      )}
      {job && (
        <p role="status" className="host-job">
          <strong>{job.state}</strong> · {job.message}
        </p>
      )}
      <div className="host-pair">
        <section className="panel host-panel" aria-label="Selected services">
          <h3>Selected services</h3>
          {services.length === 0 ? (
            <p className="host-caption">
              No services selected.{" "}
              <a href="#administration/system">
                Manage services in Administration → System.
              </a>
            </p>
          ) : (
            services.map((service) => (
              <div
                className="host-service"
                key={`${service.scope}:${service.unit}`}
              >
                <div>
                  <strong>{service.unit}</strong>
                  <p>
                    {service.scope} · {service.state}
                  </p>
                </div>
                <div className="host-actions">
                  {service.actions.map((operation) => (
                    <button
                      key={operation}
                      disabled={!live || pending}
                      onClick={() =>
                        setConfirmation({
                          action: {
                            action: "service",
                            unit: service.unit,
                            scope: service.scope,
                            operation,
                          },
                          title: `${operation[0].toUpperCase()}${operation.slice(1)} ${service.unit}?`,
                          detail: `This changes the ${service.scope} service on ${hostname}. Connected clients may be interrupted.`,
                        })
                      }
                    >
                      {operation}
                    </button>
                  ))}
                </div>
              </div>
            ))
          )}
        </section>
        <section className="panel host-panel" aria-label="Processes">
          <header className="host-panel-heading">
            <h3>Processes</h3>
            <span>{processes.length} visible</span>
          </header>
          <div className="host-filters">
            <label>
              Search processes
              <input
                type="search"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setShown(20);
                }}
                placeholder="Name, account or PID"
              />
            </label>
            <label>
              Sort by
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value)}
              >
                <option value="memory">Memory</option>
                <option value="cpu">CPU</option>
                <option value="pid">PID</option>
              </select>
            </label>
          </div>
          <div className="host-process-list">
            {rows.slice(0, shown).map((process) => (
              <div
                className="host-process"
                key={`${process.pid}:${process.started_at}`}
              >
                <div>
                  <strong>{process.name}</strong>
                  <p>
                    PID {process.pid} · {process.owner} · {process.state}
                  </p>
                  <p>
                    Started{" "}
                    {timestamp(
                      new Date(process.started_at * 1000).toISOString(),
                    )}
                  </p>
                </div>
                <div className="host-process-measurements">
                  <span>{number(process.percent, "%")} CPU</span>
                  <span>{bytes(process.memory_bytes)}</span>
                  <button
                    disabled={!live || pending || !policy?.processes}
                    onClick={() =>
                      setConfirmation({
                        action: {
                          action: "terminate",
                          pid: process.pid,
                          started_at: process.started_at,
                        },
                        title: `Terminate ${process.name}?`,
                        detail: `Send SIGTERM to PID ${process.pid}, owned by ${process.owner}, on ${hostname}. Unsaved work may be lost.`,
                      })
                    }
                  >
                    Terminate
                  </button>
                </div>
              </div>
            ))}
          </div>
          {rows.length === 0 && (
            <p className="host-caption">
              {processes.length
                ? "No matching processes."
                : "No process readings available."}
            </p>
          )}
          {rows.length > shown && (
            <button onClick={() => setShown(shown + 50)}>
              Show more processes
            </button>
          )}
          <p className="host-caption">
            CPU is normalized to total host capacity. First readings may need
            one sampling interval.
          </p>
        </section>
      </div>
      <div className="panel host-power">
        <div>
          <h3>Host power</h3>
          <p>
            Restarting or shutting down {hostname} interrupts ArkCloud and other
            host services.
          </p>
        </div>
        <div className="host-actions">
          {(["restart", "shutdown"] as const).map((action) => (
            <button
              key={action}
              disabled={!live || !policy?.power || pending}
              onClick={() =>
                setConfirmation({
                  action: { action },
                  title: `${action === "restart" ? "Restart" : "Shut down"} ${hostname}?`,
                  detail:
                    "All host services will be interrupted and the connection will close. A shutdown requires another way to turn the machine back on.",
                })
              }
            >
              {action === "restart" ? "Restart host" : "Shut down host"}
            </button>
          ))}
        </div>
        {!policy?.power && (
          <p className="host-caption">
            Power controls are disabled or unavailable under the host account.{" "}
            <a href="#administration/system">View System configuration.</a>
          </p>
        )}
      </div>
      <dialog
        ref={dialog}
        className="host-confirmation"
        onCancel={() => setConfirmation(null)}
        onClose={() => setConfirmation(null)}
        aria-labelledby="host-confirmation-title"
      >
        <h2 id="host-confirmation-title">{confirmation?.title}</h2>
        <p>{confirmation?.detail}</p>
        <div className="host-actions">
          <button autoFocus onClick={() => setConfirmation(null)}>
            Cancel
          </button>
          <button
            onClick={() => {
              if (confirmation) void submit(confirmation.action);
            }}
          >
            Confirm operation
          </button>
        </div>
      </dialog>
    </section>
  );
}
