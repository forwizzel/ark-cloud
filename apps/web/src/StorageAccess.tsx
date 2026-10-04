import { useEffect, useRef, useState } from "react";
import useUnsavedChanges from "./useUnsavedChanges";
import {
  storageRequest,
  StorageRequestError,
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
  onChanged,
}: {
  root: ManagedLocation;
  csrfToken: string;
  onChanged: () => Promise<unknown>;
}) {
  const [view, setView] = useState<LocationAccess | null>(null);
  const [draft, setDraft] = useState<Record<string, AccessLevel>>({});
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [conflict, setConflict] = useState(false);
  const preservedDraft = useRef<Record<string, AccessLevel>>({});
  const heading = useRef<HTMLHeadingElement>(null);
  const errorNotice = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (error && !busy) errorNotice.current?.focus();
  }, [error, busy]);
  const route = `admin/storage/roots/${encodeURIComponent(root.id)}/access`;
  useUnsavedChanges(
    Boolean(
      view?.accounts.some(
        (account) =>
          draft[account.id] !== undefined &&
          draft[account.id] !== account.level,
      ),
    ),
  );
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
            next.accounts.map((account) => [
              account.id,
              preservedDraft.current[account.id] ?? account.level,
            ]),
          ),
        );
        setLoading(false);
        setConflict(false);
        if (refresh > 0)
          setNotice(
            "Access reloaded. Your unsaved choices have been preserved; review them before saving.",
          );
        heading.current?.focus();
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setLoading(false);
          setError(
            failure instanceof Error
              ? failure.message
              : "Access could not be loaded.",
          );
        }
      });
    return () => controller.abort();
  }, [route, csrfToken, refresh]);
  function reload() {
    preservedDraft.current = Object.fromEntries(
      (view?.accounts ?? [])
        .filter(
          (account) =>
            draft[account.id] !== undefined &&
            draft[account.id] !== account.level,
        )
        .map((account) => [account.id, draft[account.id]]),
    );
    setLoading(true);
    setError("");
    setNotice("");
    setRefresh((current) => current + 1);
  }
  async function save(userId: string, username: string) {
    if (!view || loading || conflict) return;
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
      setDraft((current) =>
        Object.fromEntries(
          next.accounts.map((account) => [
            account.id,
            account.id === userId
              ? account.level
              : (current[account.id] ?? account.level),
          ]),
        ),
      );
      setNotice(`Access saved for ${username}. No restart needed.`);
      await onChanged();
    } catch (failure) {
      if (failure instanceof StorageRequestError && failure.status === 409)
        setConflict(true);
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
        <div>
          <p
            className="local-error"
            role="alert"
            ref={errorNotice}
            tabIndex={-1}
            id="storage-access-error"
          >
            {error}
          </p>
          {(!view || conflict) && (
            <button
              type="button"
              disabled={loading || Boolean(busy)}
              onClick={reload}
            >
              {view ? "Reload access, keep my changes" : "Retry loading access"}
            </button>
          )}
        </div>
      )}
      {notice && (
        <p className="storage-notice" role="status">
          {notice}
        </p>
      )}
      {loading && <p role="status">Loading account permissions…</p>}
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
                    name={`access-${account.id}`}
                    autoComplete="off"
                    aria-describedby={
                      error ? "storage-access-error" : undefined
                    }
                    value={draft[account.id] ?? account.level}
                    disabled={Boolean(busy) || loading}
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
                  aria-busy={busy === account.id}
                  disabled={
                    Boolean(busy) ||
                    loading ||
                    conflict ||
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
