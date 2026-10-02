import { useEffect, useState, type ReactNode } from "react";
import { formatNumber } from "./formatNumber";

import {
  fetchSystemInformation,
  type SystemInformation,
  type SystemSection,
} from "./api";

type LoadState<T> =
  | { phase: "loading" }
  | {
      phase: "ready";
      value: T;
      refreshing: boolean;
      refreshError: string | null;
    }
  | { phase: "error"; message: string };

type TemperatureReading = SystemInformation["sensors"]["temperatures"][number];

function groupTemperatures(temperatures: TemperatureReading[]) {
  const groups = {
    cpu: [] as TemperatureReading[],
    memory: [] as TemperatureReading[],
    motherboard: [] as TemperatureReading[],
    other: [] as TemperatureReading[],
  };
  for (const reading of temperatures) {
    if (reading.label.startsWith("CPU ")) groups.cpu.push(reading);
    else if (reading.label.startsWith("Memory module"))
      groups.memory.push(reading);
    else if (
      reading.label.startsWith("Motherboard") ||
      reading.label.includes("VRM") ||
      reading.label.startsWith("External sensor")
    )
      groups.motherboard.push(reading);
    else groups.other.push(reading);
  }
  return groups;
}

function TemperatureGroup({
  title,
  readings,
}: {
  title: string;
  readings: TemperatureReading[];
}) {
  if (readings.length === 0) return null;
  return (
    <div className="system-temperature-group">
      <h3>{title}</h3>
      <dl>
        {readings.map((reading, index) => (
          <div
            className="system-temperature-reading"
            key={`${reading.source_name}-${index}`}
          >
            <dt>{reading.label}</dt>
            <dd>
              {formatNumber(reading.celsius, 1)}
              {"\u00a0"}°C
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${formatNumber(bytes)}\u00a0B`;
  const units = ["KiB", "MiB", "GiB", "TiB", "PiB"];
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length,
  );
  return `${formatNumber(bytes / 1024 ** exponent, 1)}\u00a0${units[exponent - 1]}`;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function valueOrDash(value: string | number | null): string {
  return value === null || value === ""
    ? "—"
    : typeof value === "number"
      ? formatNumber(value)
      : value;
}

function Detail({
  label,
  value,
}: {
  label: string;
  value: string | number | null;
}) {
  return (
    <div className="system-detail">
      <dt>{label}</dt>
      <dd>{valueOrDash(value)}</dd>
    </div>
  );
}

function Section({
  title,
  section,
  children,
}: {
  title: string;
  section: SystemSection;
  children: ReactNode;
}) {
  return (
    <section className="system-section panel" aria-label={title}>
      <header className="system-section-head">
        <h2>{title}</h2>
        {section.availability !== "available" && (
          <span
            className={`system-availability system-availability--${section.availability}`}
          >
            {section.availability}
          </span>
        )}
      </header>
      {section.availability !== "available" && section.warning && (
        <p className="system-warning">{section.warning}</p>
      )}
      {children}
    </section>
  );
}

export default function SystemInformationPage() {
  const [information, setInformation] = useState<LoadState<SystemInformation>>({
    phase: "loading",
  });
  const [infoRequest, setInfoRequest] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchSystemInformation(controller.signal)
      .then((value) =>
        setInformation({
          phase: "ready",
          value,
          refreshing: false,
          refreshError: null,
        }),
      )
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          error instanceof Error
            ? error.message
            : "System information is unavailable.";
        setInformation((current) =>
          current.phase === "ready"
            ? { ...current, refreshing: false, refreshError: message }
            : { phase: "error", message },
        );
      });
    return () => controller.abort();
  }, [infoRequest]);

  const retryInformation = () => {
    setInformation((current) =>
      current.phase === "ready"
        ? { ...current, refreshing: true, refreshError: null }
        : { phase: "loading" },
    );
    setInfoRequest((value) => value + 1);
  };
  const temperatureGroups = groupTemperatures(
    information.phase === "ready" ? information.value.sensors.temperatures : [],
  );
  return (
    <div className="system-page" id="system-information">
      <section
        className="system-temperatures panel"
        aria-labelledby="temperatures-heading"
      >
        <header className="system-temperatures-head">
          <h2 id="temperatures-heading">Temperatures</h2>
          <div className="system-temperatures-actions">
            {information.phase === "ready" && (
              <span>Updated {formatTime(information.value.collected_at)}</span>
            )}
            <button
              className="refresh-button"
              type="button"
              onClick={retryInformation}
              disabled={
                information.phase === "loading" ||
                (information.phase === "ready" && information.refreshing)
              }
            >
              {information.phase === "ready" && information.refreshing
                ? "Updating…"
                : "Refresh readings"}
            </button>
          </div>
        </header>
        {information.phase === "loading" && (
          <p className="system-message" role="status">
            Reading temperatures…
          </p>
        )}
        {information.phase === "error" && (
          <p className="system-message" role="alert">
            {information.message} Try refreshing the readings.
          </p>
        )}
        {information.phase === "ready" && (
          <>
            {information.refreshError && (
              <p className="system-warning" role="alert">
                Could not refresh readings. Showing values from{" "}
                {formatTime(information.value.collected_at)}.
              </p>
            )}
            {information.value.sensors.temperatures.length > 0 ? (
              <>
                <div className="system-temperature-columns">
                  <div>
                    <TemperatureGroup
                      title="CPU"
                      readings={temperatureGroups.cpu}
                    />
                    <TemperatureGroup
                      title="Memory"
                      readings={temperatureGroups.memory}
                    />
                  </div>
                  <div>
                    <TemperatureGroup
                      title="Motherboard"
                      readings={temperatureGroups.motherboard}
                    />
                    <TemperatureGroup
                      title="Other sensors"
                      readings={temperatureGroups.other}
                    />
                  </div>
                </div>
                <details className="system-sensor-details">
                  <summary>Sensor IDs</summary>
                  <dl>
                    {information.value.sensors.temperatures.map(
                      (reading, index) => (
                        <div key={`${reading.source_name}-${index}`}>
                          <dt>{reading.label}</dt>
                          <dd>{reading.source_name}</dd>
                        </div>
                      ),
                    )}
                  </dl>
                </details>
              </>
            ) : (
              <p className="system-empty">
                {information.value.sensors.warning ??
                  "No readable temperature sensors."}
              </p>
            )}
          </>
        )}
      </section>

      {information.phase === "ready" && (
        <div className="system-section-grid">
          <Section title="Compute" section={information.value.compute}>
            <dl className="system-details">
              <Detail
                label="CPU model"
                value={information.value.compute.model}
              />
              <Detail
                label="Detected GPU"
                value={information.value.compute.gpus.join(", ") || null}
              />
              <Detail
                label="Logical cores"
                value={information.value.compute.logical_cores}
              />
              <Detail
                label="CPU use"
                value={
                  information.value.compute.percent === null
                    ? null
                    : `${formatNumber(information.value.compute.percent, 1)}%`
                }
              />
              <Detail
                label="Frequency"
                value={
                  information.value.compute.frequency_mhz === null
                    ? null
                    : `${formatNumber(information.value.compute.frequency_mhz)}\u00a0MHz`
                }
              />
            </dl>
          </Section>
          <Section title="Memory" section={information.value.memory}>
            <dl className="system-details">
              <Detail
                label="Used / total"
                value={
                  information.value.memory.usage
                    ? `${formatBytes(information.value.memory.usage.used_bytes)} / ${formatBytes(information.value.memory.usage.total_bytes)}`
                    : null
                }
              />
              <Detail
                label="Available"
                value={
                  information.value.memory.usage
                    ? formatBytes(
                        information.value.memory.usage.available_bytes,
                      )
                    : null
                }
              />
              <Detail
                label="Used"
                value={
                  information.value.memory.usage
                    ? `${formatNumber(information.value.memory.usage.percent, 1)}%`
                    : null
                }
              />
              <Detail
                label="Swap used / total"
                value={
                  information.value.memory.swap
                    ? `${formatBytes(information.value.memory.swap.used_bytes)} / ${formatBytes(information.value.memory.swap.total_bytes)}`
                    : null
                }
              />
            </dl>
          </Section>
          <Section title="Storage" section={information.value.storage}>
            <dl className="system-details">
              <Detail
                label="Measured path"
                value={information.value.storage.path}
              />
              <Detail
                label="Filesystem"
                value={information.value.storage.filesystem_type}
              />
              <Detail
                label="Used / total"
                value={
                  information.value.storage.usage
                    ? `${formatBytes(information.value.storage.usage.used_bytes)} / ${formatBytes(information.value.storage.usage.total_bytes)}`
                    : null
                }
              />
              <Detail
                label="Available"
                value={
                  information.value.storage.usage
                    ? formatBytes(
                        information.value.storage.usage.available_bytes,
                      )
                    : null
                }
              />
            </dl>
          </Section>
          <Section title="Identity" section={information.value.identity}>
            <dl className="system-details">
              <Detail
                label="Configured hostname"
                value={information.value.identity.hostname}
              />
              <Detail
                label="Configured OS"
                value={information.value.identity.os}
              />
              <Detail
                label="Kernel"
                value={information.value.identity.kernel}
              />
              <Detail
                label="Architecture"
                value={information.value.identity.architecture}
              />
              <Detail
                label="Host boot uptime"
                value={
                  information.value.identity.host_uptime_seconds === null
                    ? null
                    : `${Math.floor(information.value.identity.host_uptime_seconds / 3600)} hours`
                }
              />
              <Detail
                label="Python"
                value={information.value.identity.python_version}
              />
            </dl>
          </Section>
        </div>
      )}
      <footer className="system-scope-note">
        Readings come from the API container. CPU and memory can reflect
        host-wide kernel values; storage covers the configured filesystem path.
        Sensor placement may vary. GPU detection does not imply device access.
      </footer>
    </div>
  );
}
