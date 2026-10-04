import { useEffect, useRef, useState } from "react";
import {
  bytes,
  number,
  timestamp,
  systemRequest,
  SystemRequestError,
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
  const [services, setServices] = useState<HostService[] | null>(null);
  const [processes, setProcesses] = useState<HostProcess[] | null>(null);
  const [query, setQuery] = useState(
    () =>
      new URLSearchParams(window.location.search).get("process-query") ?? "",
  );
  const [sort, setSort] = useState(() => {
    const saved = new URLSearchParams(window.location.search).get(
      "process-sort",
    );
    return saved === "cpu" || saved === "pid" ? saved : "memory";
  });
  const [shown, setShown] = useState(20);
  const [serviceError, setServiceError] = useState("");
  const [processError, setProcessError] = useState("");
  const [submissionError, setSubmissionError] = useState("");
  const [unresolvedSubmission, setUnresolvedSubmission] = useState(false);
  const [jobError, setJobError] = useState("");
  const uncertain = useRef<{ action: HostAction; key: string } | null>(null);
  const submitting = useRef(false);
  const [job, setJob] = useState<HostJob | null>(null);
  const [reviewedUnknown, setReviewedUnknown] = useState("");
  const [previousJobs, setPreviousJobs] = useState<HostJob[]>([]);
  const [confirmation, setConfirmation] = useState<{
    action: HostAction;
    title: string;
    detail: string;
    label: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const pending =
    busy ||
    unresolvedSubmission ||
    (job &&
      (["accepted", "dispatched"].includes(job.state) ||
        (job.state === "unknown" && reviewedUnknown !== job.id)));

  useEffect(() => {
    const url = new URL(window.location.href);
    if (query) url.searchParams.set("process-query", query);
    else url.searchParams.delete("process-query");
    if (sort !== "memory") url.searchParams.set("process-sort", sort);
    else url.searchParams.delete("process-sort");
    window.history.replaceState(
      window.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  }, [query, sort]);

  useEffect(() => {
    const controller = new AbortController();
    let active = false;
    async function refresh() {
      if (!live || document.hidden || active) return;
      active = true;
      async function inventory<T>(
        path: string,
        accept: (items: T[]) => void,
        fail: (message: string) => void,
      ) {
        try {
          const result = await systemRequest<{ items: T[] }>(
            path,
            csrf,
            undefined,
            controller.signal,
          );
          if (!controller.signal.aborted) {
            accept(result.items);
            fail("");
          }
        } catch (cause) {
          if (!controller.signal.aborted)
            fail(
              cause instanceof Error
                ? cause.message
                : "Host inventory unavailable.",
            );
        }
      }
      await Promise.all([
        inventory<HostService>(
          "/admin/system/services",
          setServices,
          setServiceError,
        ),
        policy?.processes
          ? inventory<HostProcess>(
              "/admin/system/processes?limit=2048",
              setProcesses,
              setProcessError,
            )
          : Promise.resolve(),
      ]);
      active = false;
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
    let active = false;
    const timer = setInterval(() => {
      if (active) return;
      active = true;
      void systemRequest<HostJob>(
        `/admin/system/jobs/${job.id}`,
        csrf,
        undefined,
        controller.signal,
      )
        .then((value) => {
          if (!controller.signal.aborted) {
            setJob(value);
            setJobError("");
          }
        })
        .catch((cause) => {
          if (!controller.signal.aborted)
            setJobError(
              cause instanceof Error
                ? cause.message
                : "Could not check operation.",
            );
        })
        .finally(() => {
          active = false;
        });
    }, 2000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [csrf, job]);

  useEffect(() => {
    if (!confirmation) {
      dialog.current?.close();
      return;
    }
    dialog.current?.showModal();
    const keepFocusVisible = () => {
      const target = document.activeElement;
      if (target instanceof HTMLElement && dialog.current?.contains(target)) {
        target.scrollIntoView?.({
          block: "nearest",
          inline: "nearest",
          behavior: "instant",
        });
      }
    };
    window.addEventListener("resize", keepFocusVisible);
    window.visualViewport?.addEventListener("resize", keepFocusVisible);
    return () => {
      window.removeEventListener("resize", keepFocusVisible);
      window.visualViewport?.removeEventListener("resize", keepFocusVisible);
    };
  }, [confirmation]);

  async function submit(action: HostAction) {
    if (submitting.current || !live) return;
    submitting.current = true;
    const submission = uncertain.current ?? {
      action,
      key: crypto.randomUUID(),
    };
    uncertain.current = submission;
    setBusy(true);
    setSubmissionError("");
    setConfirmation(null);
    try {
      const result = await systemRequest<HostJob>("/admin/system/jobs", csrf, {
        payload: submission.action,
        idempotency_key: submission.key,
      });
      if (job) setPreviousJobs((items) => [...items, job].slice(-8));
      setJob(result);
      uncertain.current = null;
      setUnresolvedSubmission(false);
      setJobError("");
    } catch (cause) {
      if (
        cause instanceof SystemRequestError &&
        cause.status >= 400 &&
        cause.status < 500
      )
        uncertain.current = null;
      setUnresolvedSubmission(Boolean(uncertain.current));
      setSubmissionError(
        cause instanceof Error ? cause.message : "Host operation failed.",
      );
    } finally {
      setBusy(false);
      submitting.current = false;
    }
  }
  const rows = (processes ?? [])
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
      {submissionError && (
        <p role="alert" className="system-warning">
          {submissionError}{" "}
          {unresolvedSubmission &&
            "The submission outcome is unresolved. Retry this request to check the same operation."}
          {unresolvedSubmission && (
            <button
              disabled={!live || busy}
              onClick={() => {
                if (uncertain.current) void submit(uncertain.current.action);
              }}
            >
              Retry submission
            </button>
          )}
        </p>
      )}
      {jobError && (
        <p role="alert" className="system-warning">
          Operation status: {jobError} The operation remains unresolved;
          checking continues.
        </p>
      )}
      {job && (
        <p role="status" className="host-job">
          <strong>{job.state}</strong> · {job.message}
          {job.state === "unknown" &&
            " Outcome unresolved. Check the host before submitting another operation."}
        </p>
      )}
      {job?.state === "unknown" && (
        <label className="host-unknown-review">
          <input
            type="checkbox"
            name="review-unknown-operation"
            checked={reviewedUnknown === job.id}
            onChange={(event) =>
              setReviewedUnknown(event.target.checked ? job.id : "")
            }
          />
          I have checked the host and understand that this operation may already
          have run. Allow another operation.
        </label>
      )}
      {previousJobs.length > 0 && (
        <details className="host-previous-jobs">
          <summary>Previous operations</summary>
          <ul>
            {previousJobs.map((item) => (
              <li key={item.id}>
                {item.state} · {item.message}
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="host-pair">
        <section className="panel host-panel" aria-label="Selected services">
          <h3>Selected services</h3>
          {!live && services && (
            <p className="host-caption">
              Showing the last known service inventory. Controls are paused.
            </p>
          )}
          {serviceError && (
            <p role="alert" className="system-warning">
              Services: {serviceError}
              {services && " Showing the last known inventory."}
            </p>
          )}
          {!services ? (
            <p className="host-caption">
              {serviceError
                ? "Service inventory unavailable."
                : live
                  ? "Loading selected services…"
                  : "Waiting for the host connection to load services."}
            </p>
          ) : services.length === 0 ? (
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
                  <strong translate="no">{service.unit}</strong>
                  <p>
                    {service.scope} · {service.state}
                  </p>
                </div>
                <div className="host-actions">
                  {service.actions.map((operation) => (
                    <button
                      key={operation}
                      aria-label={`${operation[0].toUpperCase()}${operation.slice(1)} ${service.unit} (${service.scope} service)`}
                      disabled={
                        !live || Boolean(pending) || Boolean(serviceError)
                      }
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
                          label: `${operation[0].toUpperCase()}${operation.slice(1)} ${service.unit}`,
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
            {policy?.processes && processes && (
              <span>{processes.length} visible</span>
            )}
          </header>
          {!live && policy?.processes && processes && (
            <p className="host-caption">
              Showing the last known process inventory. Controls are paused.
            </p>
          )}
          {processError && (
            <p role="alert" className="system-warning">
              Processes: {processError}
              {processes && " Showing the last known inventory."}
            </p>
          )}
          {!policy?.processes && (
            <p className="host-caption">
              Process inspection is disabled or unavailable.{" "}
              <a href="#administration/system">View System configuration.</a>
            </p>
          )}
          {policy?.processes && !processes && (
            <p className="host-caption">
              {processError
                ? "Process inventory unavailable."
                : live
                  ? "Loading processes…"
                  : "Waiting for the host connection to load processes."}
            </p>
          )}
          {policy?.processes && (
            <>
              <div className="host-filters">
                <label>
                  Search processes
                  <input
                    type="search"
                    name="process-search"
                    autoComplete="off"
                    spellCheck={false}
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value);
                      setShown(20);
                    }}
                    placeholder="Name, account or PID…"
                  />
                </label>
                <label>
                  Sort by
                  <select
                    name="process-sort"
                    autoComplete="off"
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
                      <strong translate="no">{process.name}</strong>
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
                        aria-label={`Terminate ${process.name} (PID ${process.pid})`}
                        disabled={
                          !live || Boolean(pending) || Boolean(processError)
                        }
                        onClick={() =>
                          setConfirmation({
                            action: {
                              action: "terminate",
                              pid: process.pid,
                              started_at: process.started_at,
                            },
                            title: `Terminate ${process.name}?`,
                            detail: `Send SIGTERM to PID ${process.pid}, owned by ${process.owner}, on ${hostname}. Unsaved work may be lost.`,
                            label: `Terminate ${process.name}`,
                          })
                        }
                      >
                        Terminate
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              {processes && rows.length === 0 && (
                <p className="host-caption">
                  {processes.length
                    ? "No matching processes."
                    : "No processes reported by the host account."}
                </p>
              )}
              {rows.length > shown && (
                <button onClick={() => setShown(shown + 50)}>
                  Show more processes
                </button>
              )}
              <p className="host-caption">
                CPU is normalized to total host capacity. First readings may
                need one sampling interval.
              </p>
            </>
          )}
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
              disabled={!live || !policy?.power || Boolean(pending)}
              onClick={() =>
                setConfirmation({
                  action: { action },
                  title: `${action === "restart" ? "Restart" : "Shut down"} ${hostname}?`,
                  detail:
                    "All host services will be interrupted and the connection will close. A shutdown requires another way to turn the machine back on.",
                  label:
                    action === "restart" ? "Restart host" : "Shut down host",
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
        aria-describedby="host-confirmation-description"
      >
        <h2 id="host-confirmation-title">{confirmation?.title}</h2>
        <p id="host-confirmation-description">{confirmation?.detail}</p>
        <div className="host-actions">
          <button autoFocus onClick={() => setConfirmation(null)}>
            Cancel
          </button>
          <button
            disabled={!live || Boolean(pending)}
            onClick={() => {
              if (confirmation) void submit(confirmation.action);
            }}
          >
            {confirmation?.label ?? "Confirm operation"}
          </button>
        </div>
      </dialog>
    </section>
  );
}
