import { useEffect, useRef, useState, type ReactNode } from "react";
import { fetchSystemInformation, type SystemInformation } from "./api";
import SystemControls from "./SystemControls";
import SystemTerminal from "./SystemTerminal";
import {
  bytes,
  number,
  timestamp,
  systemRequest,
  type HostInformation,
  type HostSnapshot,
  type HostStatus,
} from "./systemApi";
import "./system-page.css";

function Detail({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value ?? "—"}</dd>
    </div>
  );
}
function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel host-panel" aria-label={title}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
function Meter({ value, label }: { value: number | null; label: string }) {
  return (
    <div className="host-meter">
      <div>
        <span>{label}</span>
        <strong>{number(value, "%")}</strong>
      </div>
      {value !== null && (
        <progress max={100} value={value} aria-label={label} />
      )}
    </div>
  );
}
function uptime(seconds: number) {
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function Overview({ snapshot }: { snapshot: HostSnapshot }) {
  const { identity, compute } = snapshot;
  return (
    <div className="host-pair host-overview">
      <Panel title="Identity">
        <div className="host-identity">
          <strong>{identity.hostname}</strong>
          <p>{identity.os}</p>
        </div>
        <dl className="host-details">
          <Detail label="Uptime" value={uptime(identity.uptime_seconds)} />
        </dl>
        <details className="host-identity-secondary">
          <summary>Kernel, architecture and boot details</summary>
          <dl className="host-details">
            <Detail label="Kernel" value={identity.kernel} />
            <Detail label="Architecture" value={identity.architecture} />
            <Detail label="Booted" value={timestamp(identity.boot_time)} />
          </dl>
        </details>
      </Panel>
      <Panel title="Compute">
        <p className="host-cpu-model">
          {compute.model ?? "CPU model unavailable"}
        </p>
        <Meter label="CPU utilization" value={compute.percent} />
        <dl className="host-details">
          <Detail
            label="Physical / logical cores"
            value={`${number(compute.physical_cores)} / ${number(compute.logical_cores)}`}
          />
          <Detail label="Sockets" value={number(compute.sockets)} />
          <Detail
            label="Frequency"
            value={number(compute.frequency_mhz, " MHz")}
          />
          <Detail
            label="Load · 1 / 5 / 15 min"
            value={compute.load_average?.map((v) => number(v)).join(" / ")}
          />
          <Detail
            label="Detected GPUs"
            value={
              compute.gpus.length ? compute.gpus.join(", ") : "No GPU detected"
            }
          />
        </dl>
        <details>
          <summary>Per-core utilization</summary>
          <div className="host-core-grid">
            {compute.per_core.map((value, index) => (
              <span key={index}>
                Core {index + 1} <strong>{number(value, "%")}</strong>
              </span>
            ))}
          </div>
          {compute.per_core.length === 0 && (
            <p>Waiting for an interval sample.</p>
          )}
        </details>
        <p className="host-caption">
          GPU detection does not imply utilization measurements or device
          access.
        </p>
      </Panel>
    </div>
  );
}

function Vitals({
  snapshot,
  history,
}: {
  snapshot: HostSnapshot;
  history: HostInformation["history"];
}) {
  const { memory } = snapshot;
  return (
    <div className="host-vitals">
      <div className="host-pair">
        <Panel title="Temperatures">
          <div className="host-temperature-groups">
            {["cpu", "gpu", "memory", "motherboard", "storage", "other"].map(
              (group) => {
                const readings = snapshot.temperatures.filter(
                  (reading) => reading.group === group,
                );
                return readings.length ? (
                  <section key={group}>
                    <h3>
                      {group === "cpu" || group === "gpu"
                        ? group.toUpperCase()
                        : group[0].toUpperCase() + group.slice(1)}
                    </h3>
                    <dl>
                      {readings.map((reading) => (
                        <div className="host-temperature" key={reading.id}>
                          <dt>
                            {reading.label}
                            <small>{reading.source_name}</small>
                          </dt>
                          <dd
                            className={
                              reading.critical !== null &&
                              reading.celsius >= reading.critical
                                ? "host-danger"
                                : reading.high !== null &&
                                    reading.celsius >= reading.high
                                  ? "host-warning"
                                  : ""
                            }
                          >
                            {number(reading.celsius, " °C")}
                            {reading.high !== null && (
                              <small>High {number(reading.high, " °C")}</small>
                            )}
                            {reading.critical !== null && (
                              <small>
                                Critical {number(reading.critical, " °C")}
                              </small>
                            )}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                ) : null;
              },
            )}
          </div>
          {snapshot.temperatures.length === 0 && (
            <p className="host-caption">
              No readable temperature sensors. Other host readings remain
              available.
            </p>
          )}
        </Panel>
        <Panel title="Memory">
          <Meter
            label="RAM utilization"
            value={memory.usage?.percent ?? null}
          />
          <dl className="host-details">
            <Detail
              label="Used / total"
              value={
                memory.usage
                  ? `${bytes(memory.usage.used_bytes)} / ${bytes(memory.usage.total_bytes)}`
                  : null
              }
            />
            <Detail
              label="Available"
              value={bytes(memory.usage?.available_bytes)}
            />
            <Detail
              label="Cache / buffers"
              value={`${bytes(memory.cached_bytes)} / ${bytes(memory.buffers_bytes)}`}
            />
            <Detail
              label="Swap used / total"
              value={
                memory.swap
                  ? `${bytes(memory.swap.used_bytes)} / ${bytes(memory.swap.total_bytes)}`
                  : null
              }
            />
            <Detail
              label="Swap in / out since boot"
              value={`${bytes(memory.swap_in_bytes)} / ${bytes(memory.swap_out_bytes)}`}
            />
          </dl>
          <details>
            <summary>Recent CPU and memory samples</summary>
            <p className="host-caption">
              Up to ten minutes collected by this API session. Gaps indicate
              interrupted collection.
            </p>
            <div className="host-history">
              <table>
                <thead>
                  <tr>
                    <th>Collected</th>
                    <th>CPU</th>
                    <th>RAM</th>
                  </tr>
                </thead>
                <tbody>
                  {history
                    .slice(-30)
                    .reverse()
                    .map((sample, index) => (
                      <tr key={`${sample.collected_at}:${index}`}>
                        <td>{timestamp(sample.collected_at)}</td>
                        <td>{number(sample.cpu, "%")}</td>
                        <td>{number(sample.memory, "%")}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </details>
        </Panel>
      </div>
      <Panel title="Storage">
        <p className="host-caption">
          Host filesystems. Pseudo-filesystems and duplicate bind mounts are
          omitted from the capacity ledger.
        </p>
        <div className="host-mounts">
          {snapshot.mounts.map((mount) => (
            <article key={mount.id} className="host-mount">
              <div className="host-panel-heading">
                <h3>{mount.path}</h3>
                <span>
                  {mount.filesystem} · {mount.device}
                </span>
              </div>
              <Meter
                label={`Utilization of ${mount.path}`}
                value={mount.usage?.percent ?? null}
              />
              <dl className="host-details">
                <Detail
                  label="Used / total"
                  value={
                    mount.usage
                      ? `${bytes(mount.usage.used_bytes)} / ${bytes(mount.usage.total_bytes)}`
                      : null
                  }
                />
                <Detail
                  label="Available"
                  value={bytes(mount.usage?.available_bytes)}
                />
                <Detail label="Mount options" value={mount.options} />
              </dl>
            </article>
          ))}
        </div>
        {snapshot.mounts.length === 0 && (
          <p>No host filesystem readings available.</p>
        )}
        <details>
          <summary>Device I/O and omitted mounts</summary>
          <p className="host-caption">
            Rates are measured between samples, at device level; they are not
            per-filesystem rates. Missing rates need another sample.
          </p>
          <dl className="host-details">
            {snapshot.disk_io.map((disk) => (
              <Detail
                key={disk.device}
                label={disk.device}
                value={`Read ${bytes(disk.read_bytes_per_second)}/s · write ${bytes(disk.write_bytes_per_second)}/s`}
              />
            ))}
          </dl>
          <p className="host-caption">
            Omitted: {snapshot.omitted_mounts.join(", ") || "None"}
          </p>
        </details>
      </Panel>
    </div>
  );
}

function Runtime({
  information,
  vitals,
}: {
  information: SystemInformation;
  vitals: boolean;
}) {
  return (
    <details className="panel host-panel host-runtime">
      <summary>API runtime readings</summary>
      <p className="host-caption">
        Readings come from the API container, not the enrolled host agent. CPU
        and memory may reflect kernel-wide values; storage measures{" "}
        {information.storage.path}.
      </p>
      {vitals ? (
        <div className="host-pair">
          <Panel title="Temperatures">
            <dl className="host-details">
              {information.sensors.temperatures.map((reading, index) => (
                <Detail
                  key={index}
                  label={reading.label}
                  value={number(reading.celsius, " °C")}
                />
              ))}
            </dl>
            <p>{information.sensors.warning}</p>
          </Panel>
          <Panel title="Memory">
            <dl className="host-details">
              <Detail
                label="Used / total"
                value={
                  information.memory.usage
                    ? `${bytes(information.memory.usage.used_bytes)} / ${bytes(information.memory.usage.total_bytes)}`
                    : null
                }
              />
              <Detail
                label="Storage used / total"
                value={
                  information.storage.usage
                    ? `${bytes(information.storage.usage.used_bytes)} / ${bytes(information.storage.usage.total_bytes)}`
                    : null
                }
              />
            </dl>
          </Panel>
        </div>
      ) : (
        <dl className="host-details">
          <Detail
            label="Configured hostname"
            value={information.identity.hostname}
          />
          <Detail label="Configured OS" value={information.identity.os} />
          <Detail label="CPU model" value={information.compute.model} />
          <Detail
            label="CPU utilization"
            value={number(information.compute.percent, "%")}
          />
          <Detail
            label="Detected GPUs"
            value={information.compute.gpus.join(", ") || "No GPU detected"}
          />
          <Detail
            label="API / Python"
            value={`${information.identity.api_version} / ${information.identity.python_version}`}
          />
        </dl>
      )}
    </details>
  );
}

export default function SystemInformationPage({
  route = "#system",
  csrfToken = "",
  isAdmin = false,
}: {
  route?: string;
  csrfToken?: string;
  isAdmin?: boolean;
}) {
  const vitals = route === "#system/vitals";
  const [information, setInformation] = useState<HostInformation | null>(null);
  const [admin, setAdmin] = useState<HostStatus | null>(null);
  const [runtime, setRuntime] = useState<SystemInformation | null>(null);
  const [error, setError] = useState("");
  const [policyError, setPolicyError] = useState("");
  const [runtimeError, setRuntimeError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [request, setRequest] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    let active = false;
    async function refresh() {
      if (active || document.hidden) return;
      active = true;
      setRefreshing(true);
      const telemetry = async () => {
        let needsRuntime = true;
        try {
          const value = await systemRequest<HostInformation>(
            `/system/${vitals ? "vitals" : "overview"}`,
            "",
            undefined,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          setInformation(value);
          setError("");
          needsRuntime = !value.snapshot;
        } catch (cause) {
          if (!controller.signal.aborted)
            setError(
              cause instanceof Error
                ? cause.message
                : "System information unavailable.",
            );
        }
        if (needsRuntime && !controller.signal.aborted) {
          try {
            const value = await fetchSystemInformation(controller.signal);
            if (!controller.signal.aborted) {
              setRuntime(value);
              setRuntimeError("");
            }
          } catch (cause) {
            if (!controller.signal.aborted)
              setRuntimeError(
                cause instanceof Error
                  ? cause.message
                  : "API runtime readings unavailable.",
              );
          }
        }
      };
      const permissions = async () => {
        if (!isAdmin) return;
        try {
          const value = await systemRequest<HostStatus>(
            "/admin/system/status",
            csrfToken,
            undefined,
            controller.signal,
          );
          if (!controller.signal.aborted) {
            setAdmin(value);
            setPolicyError("");
          }
        } catch (cause) {
          if (!controller.signal.aborted)
            setPolicyError(
              cause instanceof Error
                ? cause.message
                : "Host permissions unavailable.",
            );
        }
      };
      await Promise.all([telemetry(), permissions()]);
      active = false;
      if (!controller.signal.aborted) setRefreshing(false);
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [csrfToken, isAdmin, request, vitals]);

  const snapshot = information?.snapshot;
  const live = information?.state === "connected" && !error;
  const stateLabels = {
    connected: "Host connected",
    offline: "Host offline · readings may be stale",
    not_enrolled: "Host agent not enrolled",
    revoked: "System disconnected",
  };

  return (
    <div className="host-workspace" id="system">
      <div className="host-workspace-bar">
        <div className="host-tabs" role="tablist" aria-label="System sections">
          {["Overview", "Vitals"].map((label, index) => (
            <button
              key={label}
              ref={(element) => {
                tabs.current[index] = element;
              }}
              id={`system-tab-${index}`}
              role="tab"
              aria-selected={vitals === (index === 1)}
              aria-controls={`system-panel-${index}`}
              tabIndex={vitals === (index === 1) ? 0 : -1}
              onClick={() => {
                window.location.hash = index ? "system/vitals" : "system";
              }}
              onKeyDown={(event) => {
                if (
                  ["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)
                ) {
                  event.preventDefault();
                  const next =
                    event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? 1
                        : 1 - index;
                  tabs.current[next]?.focus();
                  window.location.hash = next ? "system/vitals" : "system";
                }
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="host-connection" role="status">
          <strong>
            {error
              ? information
                ? "Host status unavailable · readings are stale"
                : "Host status unavailable"
              : information
                ? stateLabels[information.state]
                : "Connecting to System…"}
          </strong>
          <span>
            {information?.collected_at
              ? `Collected ${timestamp(information.collected_at)}`
              : error
                ? "No host readings available"
                : "Waiting for host readings"}
          </span>
        </div>
        <div className="host-actions">
          <button disabled={refreshing} onClick={() => setRequest(request + 1)}>
            {refreshing ? "Updating…" : "Refresh"}
          </button>
        </div>
      </div>
      {error && (
        <p className="system-warning" role="alert">
          {error}
          {snapshot &&
            ` Showing values collected ${timestamp(snapshot.collected_at)}.`}
        </p>
      )}
      {isAdmin && policyError && (
        <p className="system-warning" role="alert">
          Host permissions: {policyError} Controls are paused until permissions
          refresh.
        </p>
      )}
      {!snapshot && runtimeError && (
        <p className="system-warning" role="alert">
          API runtime: {runtimeError}
          {runtime && " Showing the last available runtime readings."}
        </p>
      )}
      {snapshot && snapshot.warnings.length > 0 && (
        <details className="host-reading-warnings">
          <summary>Some host readings are unavailable</summary>
          <ul>
            {snapshot.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
      {information && !snapshot && (
        <p className="host-caption">
          Host readings aren't available yet.{" "}
          {isAdmin ? (
            <a href="#administration/system">
              Configure System in Administration
            </a>
          ) : (
            "Ask an administrator to connect System."
          )}
        </p>
      )}
      <div
        id="system-panel-0"
        role="tabpanel"
        aria-labelledby="system-tab-0"
        tabIndex={0}
        hidden={vitals}
      >
        {snapshot && <Overview snapshot={snapshot} />}
        {!snapshot && runtime && (
          <Runtime information={runtime} vitals={false} />
        )}
        {isAdmin && (
          <SystemControls
            csrf={csrfToken}
            policy={policyError ? null : (admin?.policy ?? null)}
            live={live && !policyError && !vitals}
            hostname={snapshot?.identity.hostname ?? "this host"}
          />
        )}
        {isAdmin && (
          <SystemTerminal
            csrf={csrfToken}
            policy={policyError ? null : (admin?.policy ?? null)}
            live={live && !policyError}
            hidden={vitals}
          />
        )}
      </div>
      <div
        id="system-panel-1"
        role="tabpanel"
        aria-labelledby="system-tab-1"
        tabIndex={0}
        hidden={!vitals}
      >
        {snapshot && (
          <Vitals snapshot={snapshot} history={information?.history ?? []} />
        )}
        {!snapshot && runtime && <Runtime information={runtime} vitals />}
        {isAdmin && snapshot && (
          <p className="host-caption">
            <a href="#administration/storage">
              Manage ArkCloud storage locations
            </a>
          </p>
        )}
      </div>
      <footer className="host-caption">
        Host readings are collected by the enrolled account. Permissions and
        hardware determine which measurements and operations are available.
      </footer>
    </div>
  );
}
