import { useState } from "react";
import { storageRequest, type StorageJob } from "./storageAdminApi";

export default function StorageActivity({
  jobs,
  csrfToken,
  busy,
  titles,
  onNotice,
  onRefresh,
  onRetry,
}: {
  jobs: StorageJob[];
  csrfToken: string;
  busy: boolean;
  titles: Record<string, string>;
  onNotice: (value: string) => void;
  onRefresh: () => Promise<void>;
  onRetry: (job: StorageJob) => void;
}) {
  const [working, setWorking] = useState(false);
  const [showDismissed, setShowDismissed] = useState(false);
  const visible = jobs.filter(
    (job) => !["browse", "preflight"].includes(job.action),
  );
  const current = visible.filter((job) =>
    ["current", "attention"].includes(
      job.disposition ??
        (["queued", "applying", "verifying"].includes(job.state)
          ? "current"
          : job.state === "failed"
            ? "attention"
            : "history"),
    ),
  );
  const history = visible.filter(
    (job) =>
      !current.includes(job) &&
      (showDismissed || job.disposition !== "dismissed"),
  );
  async function act(path: string) {
    setWorking(true);
    try {
      const result = await storageRequest<{ message: string }>(
        path,
        csrfToken,
        "POST",
      );
      onNotice(result.message);
      await onRefresh();
    } catch (error) {
      onNotice(
        error instanceof Error ? error.message : "Activity request failed.",
      );
    } finally {
      setWorking(false);
    }
  }
  function entry(job: StorageJob) {
    const labels: Record<string, string> = {
      dismissed: "Dismissed",
      canceled: "Canceled",
      superseded: "Superseded",
      resolved: "Resolved",
      obsolete: "No longer applicable",
    };
    const label =
      labels[job.disposition ?? ""] ??
      {
        queued: "Waiting for host",
        applying: "Applying",
        verifying: "Verifying",
        completed: "Completed",
        failed: "Failed",
      }[job.state];
    return (
      <li key={job.id}>
        <div>
          <strong>{titles[job.action] ?? job.action}</strong>
          <span>{label}</span>
        </div>
        <p>{job.message}</p>
        {job.disposition === "attention" && job.retry_reason && (
          <p className="storage-help">{job.retry_reason}</p>
        )}
        <div className="local-actions">
          {job.state === "queued" && (
            <button
              disabled={working}
              onClick={() =>
                void act(
                  `admin/storage/jobs/${encodeURIComponent(job.id)}/cancel`,
                )
              }
            >
              Cancel pending request
            </button>
          )}
          {job.can_retry && (
            <button disabled={busy || working} onClick={() => onRetry(job)}>
              Retry {titles[job.action]?.toLowerCase() ?? "operation"}
            </button>
          )}
          {job.can_dismiss && (
            <button
              disabled={working}
              onClick={() =>
                void act(
                  `admin/storage/jobs/${encodeURIComponent(job.id)}/dismiss`,
                )
              }
            >
              Dismiss {titles[job.action]?.toLowerCase() ?? "notification"}
            </button>
          )}
        </div>
        <time dateTime={job.created_at}>
          {new Date(job.created_at).toLocaleString()}
        </time>
      </li>
    );
  }
  return (
    <>
      <h4>Current issues &amp; progress</h4>
      {current.length ? (
        <ol className="storage-activity">{current.map(entry)}</ol>
      ) : (
        <p>No pending operations or current failure notifications.</p>
      )}
      <details className="storage-history">
        <summary>History</summary>
        <p>
          Finished and obsolete requests are kept here for reference. Dismissing
          a notification does not change storage access.
        </p>
        <div className="local-actions">
          <button
            disabled={working || !history.some((job) => job.can_dismiss)}
            onClick={() => void act("admin/storage/jobs/dismiss-history")}
          >
            Dismiss historical notifications
          </button>
          <button onClick={() => setShowDismissed((value) => !value)}>
            {showDismissed ? "Hide dismissed" : "Show dismissed"}
          </button>
        </div>
        {history.length ? (
          <ol className="storage-activity">{history.map(entry)}</ol>
        ) : (
          <p>No visible history.</p>
        )}
      </details>
    </>
  );
}
