import { useEffect, useRef, useState } from "react";
import {
  storageRequest,
  type AccessLevel,
  type LocationAccess,
  type ManagedLocation,
} from "./storageAdminApi";

const levels: Record<AccessLevel, string> = {
  none: "No access",
  read: "Read-only",
  write: "Read & write",
};

export default function StorageAccess({
  root,
  csrfToken,
  onClose,
  onChanged,
}: {
  root: ManagedLocation;
  csrfToken: string;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [view, setView] = useState<LocationAccess | null>(null);
  const [draft, setDraft] = useState<Record<string, AccessLevel>>({});
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const route = `admin/storage/roots/${encodeURIComponent(root.id)}/access`;
  useEffect(() => {
    const controller = new AbortController();
    storageRequest<LocationAccess>(
      route,
      csrfToken,
      "GET",
      undefined,
      controller.signal,
    )
      .then((next) => {
        if (controller.signal.aborted) return;
        setView(next);
        setDraft(
          Object.fromEntries(
            next.accounts.map((account) => [account.id, account.level]),
          ),
        );
        heading.current?.focus();
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "Access could not be loaded.",
          );
      });
    return () => controller.abort();
  }, [route, csrfToken]);
  async function save(userId: string, username: string) {
    if (!view) return;
    setBusy(userId);
    setError("");
    setNotice("");
    try {
      const next = await storageRequest<LocationAccess>(
        route,
        csrfToken,
        "PUT",
        {
          user_id: userId,
          level: draft[userId],
          revision: view.revision,
          registration: view.registration,
        },
      );
      setView(next);
      setNotice(`Access saved for ${username}. No restart needed.`);
      await onChanged();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Access could not be saved.",
      );
    } finally {
      setBusy("");
    }
  }
  return (
    <section
      className="panel storage-section"
      aria-labelledby="storage-access-heading"
    >
      <div className="storage-section-heading">
        <h3 id="storage-access-heading" ref={heading} tabIndex={-1}>
          Manage access — {root.label}
        </h3>
        <button type="button" onClick={onClose} disabled={Boolean(busy)}>
          Close access editor
        </button>
      </div>
      <p className="storage-path">{root.source}</p>
      <p>
        {root.kind === "managed"
          ? "Each enabled account sees only its own private folder. Granting access creates that account’s folder when needed. Administrators do not gain access to another account’s files."
          : "These accounts share the same files in this directory. Choose the access each person needs."}
      </p>
      <p>
        New accounts have no access until you grant it. Revoking access
        preserves files.
      </p>
      {view?.host_read_only && (
        <p>
          This host mount is read-only. Write access requires changing the host
          mount configuration first.
        </p>
      )}
      {error && (
        <p className="local-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="storage-notice" role="status">
          {notice}
        </p>
      )}
      {!view && !error && <p role="status">Loading account permissions…</p>}
      {view && (
        <ul className="storage-access-list">
          {view.accounts.map((account) => (
            <li key={account.id}>
              <div>
                <h4>{account.username}</h4>
                <p>
                  {account.active
                    ? account.pending
                      ? "Invitation pending · "
                      : ""
                    : "Account disabled · "}
                  {account.message}
                </p>
                <p className="storage-help">
                  Effective access: {levels[account.effective_level]}
                </p>
              </div>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void save(account.id, account.username);
                }}
              >
                <label>
                  Access for {account.username}
                  <select
                    value={draft[account.id] ?? account.level}
                    disabled={Boolean(busy)}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        [account.id]: event.target.value as AccessLevel,
                      }))
                    }
                  >
                    <option value="none">No access</option>
                    <option value="read" disabled={!account.active}>
                      Read-only
                    </option>
                    <option
                      value="write"
                      disabled={!account.active || view.host_read_only}
                    >
                      Read &amp; write
                    </option>
                  </select>
                </label>
                <button
                  type="submit"
                  disabled={
                    Boolean(busy) ||
                    (draft[account.id] === account.level &&
                      (account.ready || account.level === "none"))
                  }
                >
                  {busy === account.id
                    ? "Saving…"
                    : `Save access for ${account.username}`}
                </button>
              </form>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
