import { FormEvent, useEffect, useRef, useState } from "react";
import useUnsavedChanges from "./useUnsavedChanges";
import "./account.css";

import {
  changePassword,
  changeUsername,
  deleteUser,
  inviteUser,
  listUsers,
  reissueInvite,
  updateUser,
  type AuthSession,
  type LocalUser,
} from "./api";

type AccountAction = {
  kind: "role" | "disable" | "reissue" | "delete";
  user: LocalUser;
};

export default function AccountPage({
  session,
  onUpdate,
  onPasswordChanged,
  usersOnly = false,
}: {
  session: AuthSession;
  onUpdate: (session: AuthSession) => void;
  onPasswordChanged: () => void;
  usersOnly?: boolean;
}) {
  const [username, setUsername] = useState(session.username ?? "");
  const [currentForName, setCurrentForName] = useState("");
  const [currentForPassword, setCurrentForPassword] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState<"member" | "admin">("member");
  const [inviteCode, setInviteCode] = useState<string | null>(null);
  const [inviteAcknowledged, setInviteAcknowledged] = useState(false);
  const [copyNotice, setCopyNotice] = useState("");
  const [copyFailed, setCopyFailed] = useState(false);
  const [copying, setCopying] = useState(false);
  const [accountAction, setAccountAction] = useState<AccountAction | null>(
    null,
  );
  const [deleteName, setDeleteName] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [users, setUsers] = useState<LocalUser[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(usersOnly);
  const [ledgerError, setLedgerError] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const csrf = session.csrf_token ?? "";
  const confirmationInput = useRef<HTMLInputElement>(null);
  const errorNotice = useRef<HTMLParagraphElement>(null);
  const actionHeading = useRef<HTMLHeadingElement>(null);
  const deleteInput = useRef<HTMLInputElement>(null);
  const usersHeading = useRef<HTMLHeadingElement>(null);
  const inviteHeading = useRef<HTMLHeadingElement>(null);
  const inviteButton = useRef<HTMLButtonElement>(null);
  const actionTrigger = useRef<HTMLButtonElement | null>(null);
  const restoreActionFocus = useRef(false);
  const restoreInviteFocus = useRef(false);
  const unacknowledgedInvite = Boolean(inviteCode && !inviteAcknowledged);
  useUnsavedChanges(
    username !== (session.username ?? "") ||
      unacknowledgedInvite ||
      Boolean(
        currentForName ||
        currentForPassword ||
        password ||
        confirmation ||
        inviteName ||
        deleteName ||
        deletePassword,
      ),
    unacknowledgedInvite
      ? "This invitation code will not be shown again. Copy and save it before leaving. Leave without acknowledging it?"
      : undefined,
  );
  useEffect(() => {
    if (error && error !== "New passwords do not match.")
      errorNotice.current?.focus();
  }, [error]);

  useEffect(() => {
    if (!accountAction) return;
    if (accountAction.kind === "delete") deleteInput.current?.focus();
    else actionHeading.current?.focus();
  }, [accountAction]);

  useEffect(() => {
    if (accountAction || busy || loadingUsers || !restoreActionFocus.current)
      return;
    restoreActionFocus.current = false;
    const trigger = actionTrigger.current;
    if (trigger?.isConnected && !trigger.disabled) trigger.focus();
    else usersHeading.current?.focus();
  }, [accountAction, busy, loadingUsers]);

  useEffect(() => {
    if (inviteCode) inviteHeading.current?.focus();
    else if (restoreInviteFocus.current) {
      restoreInviteFocus.current = false;
      if (inviteButton.current && !inviteButton.current.disabled)
        inviteButton.current.focus();
      else usersHeading.current?.focus();
    }
  }, [inviteCode]);

  const fetchUsers = () =>
    listUsers()
      .then((loaded) => {
        setUsers(loaded);
        setLedgerError("");
        return true;
      })
      .catch((reason: unknown) => {
        setLedgerError(
          reason instanceof Error ? reason.message : "Unable to load accounts.",
        );
        return false;
      })
      .finally(() => setLoadingUsers(false));
  const refreshUsers = () => {
    setLoadingUsers(true);
    return fetchUsers();
  };
  const retryUsers = async () => {
    if (await refreshUsers()) usersHeading.current?.focus();
  };

  useEffect(() => {
    if (session.role === "admin" && usersOnly) void fetchUsers();
  }, [session.role, usersOnly]);

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setNotice("");
    setError("");
    try {
      await action();
    } catch (reason: unknown) {
      setError(
        reason instanceof Error ? reason.message : "Account update failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  function saveName(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      const updated = await changeUsername(username, currentForName, csrf);
      onUpdate(updated);
      setCurrentForName("");
      setNotice("Username updated. Use it the next time you sign in.");
      if (session.role === "admin") await refreshUsers();
    });
  }

  function savePassword(event: FormEvent) {
    event.preventDefault();
    if (password !== confirmation) {
      setError("New passwords do not match.");
      confirmationInput.current?.focus();
      return;
    }
    void run(async () => {
      await changePassword(currentForPassword, password, csrf);
      setCurrentForPassword("");
      setPassword("");
      setConfirmation("");
      onPasswordChanged();
    });
  }

  function sendInvite(event: FormEvent) {
    event.preventDefault();
    if (inviteCode) return;
    void run(async () => {
      const result = await inviteUser(inviteName, inviteRole, csrf);
      revealInvite(result.token);
      setInviteName("");
      setNotice(
        "Invitation created. Copy the code now; it will not be shown again.",
      );
      await refreshUsers();
    });
  }

  function revealInvite(token: string) {
    setInviteCode(token);
    setInviteAcknowledged(false);
    setCopyNotice("");
    setCopyFailed(false);
  }

  async function copyInvite() {
    if (!inviteCode || copying) return;
    setCopying(true);
    setCopyNotice("");
    try {
      await navigator.clipboard.writeText(inviteCode);
      setCopyFailed(false);
      setCopyNotice("Invitation code copied. Save and share it privately.");
    } catch {
      setCopyFailed(true);
      setCopyNotice(
        "Unable to copy the code. Select and copy it manually, then save it privately.",
      );
    } finally {
      setCopying(false);
    }
  }

  function openAction(
    kind: AccountAction["kind"],
    user: LocalUser,
    trigger: HTMLButtonElement,
  ) {
    actionTrigger.current = trigger;
    restoreActionFocus.current = false;
    setError("");
    setDeleteName("");
    setDeletePassword("");
    setAccountAction({ kind, user });
  }

  function closeAction() {
    restoreActionFocus.current = true;
    setAccountAction(null);
    setDeleteName("");
    setDeletePassword("");
    setError("");
  }

  async function enableAccount(user: LocalUser) {
    const updated = await updateUser(user.id, { active: true }, csrf);
    setUsers((current) =>
      current.map((item) => (item.id === user.id ? updated : item)),
    );
    setNotice(`${user.username} enabled.`);
    await refreshUsers();
  }

  function confirmAction(event: FormEvent) {
    event.preventDefault();
    if (!accountAction) return;
    const { kind, user } = accountAction;
    if (kind === "delete" && (deleteName !== user.username || !deletePassword))
      return;
    void run(async () => {
      if (kind === "delete") {
        await deleteUser(user.id, deleteName, deletePassword, csrf);
        setUsers((current) => current.filter((item) => item.id !== user.id));
        setNotice(`${user.username} deleted. Local files remain on the host.`);
      } else if (kind === "reissue") {
        if (inviteCode) return;
        const result = await reissueInvite(user.id, csrf);
        revealInvite(result.token);
        setNotice(
          `New invitation code issued for ${user.username}; the old code no longer works.`,
        );
      } else {
        const role = user.role === "admin" ? "member" : "admin";
        const updated = await updateUser(
          user.id,
          kind === "role" ? { role } : { active: false },
          csrf,
        );
        setUsers((current) =>
          current.map((item) => (item.id === user.id ? updated : item)),
        );
        setNotice(
          kind === "role"
            ? `${user.username} is now ${role === "admin" ? "an administrator" : "a member"}.`
            : `${user.username} disabled.`,
        );
      }
      closeAction();
      if (kind === "reissue") restoreActionFocus.current = false;
      await refreshUsers();
    });
  }

  function actionPanel(user: LocalUser) {
    if (!accountAction || accountAction.user.id !== user.id) return null;
    const { kind } = accountAction;
    const roleLabel = user.role === "admin" ? "member" : "administrator";
    const title =
      kind === "delete"
        ? `Delete ${user.username}?`
        : kind === "disable"
          ? `Disable ${user.username}?`
          : kind === "reissue"
            ? `Issue a new invitation code for ${user.username}?`
            : `Make ${user.username} ${roleLabel === "administrator" ? "an" : "a"} ${roleLabel}?`;
    const confirmLabel =
      kind === "delete"
        ? `Delete account ${user.username}`
        : kind === "disable"
          ? `Confirm disable ${user.username}`
          : kind === "reissue"
            ? `Issue new code for ${user.username}`
            : `Confirm make ${user.username} ${roleLabel}`;
    return (
      <section
        className="account-confirmation"
        role="region"
        aria-labelledby="account-action-title"
        aria-describedby="account-action-description"
      >
        <form
          className={kind === "delete" ? "account-delete" : undefined}
          onSubmit={confirmAction}
          aria-busy={busy}
        >
          <h3 id="account-action-title" ref={actionHeading} tabIndex={-1}>
            {title}
          </h3>
          <p id="account-action-description">
            {kind === "delete"
              ? "This permanently removes the account and its access permissions. Local files remain on the host. This account’s storage assignments lose access; they are not inherited by a new account with the same username."
              : kind === "disable"
                ? "This account will no longer be able to sign in or use Ark Cloud. You can enable it again later."
                : kind === "reissue"
                  ? "The old invitation code will stop working. Copy and save the new one-time code before leaving this page."
                  : user.role === "admin"
                    ? "This account will lose administrator access to accounts and instance configuration."
                    : "This account will gain administrator access to manage accounts and instance configuration."}
          </p>
          {error && (
            <p
              className="auth-error"
              role="alert"
              id="account-error"
              ref={errorNotice}
              tabIndex={-1}
            >
              {error}
            </p>
          )}
          {kind === "delete" && (
            <>
              <label>
                Type {user.username} to confirm
                <input
                  ref={deleteInput}
                  name="delete-confirmation"
                  autoComplete="off"
                  spellCheck={false}
                  autoCapitalize="none"
                  required
                  disabled={busy}
                  value={deleteName}
                  onChange={(event) => setDeleteName(event.target.value)}
                />
              </label>
              <label>
                Your current password
                <input
                  name="current-password"
                  required
                  type="password"
                  autoComplete="current-password"
                  disabled={busy}
                  value={deletePassword}
                  onChange={(event) => setDeletePassword(event.target.value)}
                />
              </label>
            </>
          )}
          <div className="account-confirmation-actions">
            <button
              type="submit"
              disabled={
                busy ||
                (kind === "delete" &&
                  (deleteName !== user.username || !deletePassword))
              }
            >
              {confirmLabel}
            </button>
            <button type="button" disabled={busy} onClick={closeAction}>
              Cancel
            </button>
          </div>
        </form>
      </section>
    );
  }

  const ledgerUnavailable = busy || loadingUsers || Boolean(ledgerError);

  return (
    <div className="account-page">
      {error && !accountAction && (
        <p
          className="auth-error"
          role="alert"
          id="account-error"
          ref={errorNotice}
          tabIndex={-1}
        >
          {error}
        </p>
      )}
      {notice && (
        <p className="connection-notice" role="status">
          {notice}
        </p>
      )}
      {!usersOnly && (
        <div className="account-grid">
          <section
            className="account-card"
            aria-labelledby="account-name-title"
          >
            <p className="eyebrow">Identity</p>
            <h2 id="account-name-title">Username</h2>
            <form onSubmit={saveName}>
              <label>
                New username
                <input
                  name="username"
                  spellCheck={false}
                  autoCapitalize="none"
                  required
                  minLength={3}
                  maxLength={64}
                  autoComplete="username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                />
              </label>
              <label>
                Current password
                <input
                  name="current-password"
                  required
                  type="password"
                  autoComplete="current-password"
                  value={currentForName}
                  onChange={(event) => setCurrentForName(event.target.value)}
                />
              </label>
              <button
                className="refresh-button"
                type="submit"
                disabled={busy}
                aria-busy={busy}
              >
                Save username
              </button>
            </form>
          </section>
          <section
            className="account-card"
            aria-labelledby="account-password-title"
          >
            <p className="eyebrow">Security</p>
            <h2 id="account-password-title">Password</h2>
            <form onSubmit={savePassword}>
              <label>
                Current password
                <input
                  name="current-password"
                  required
                  type="password"
                  autoComplete="current-password"
                  value={currentForPassword}
                  onChange={(event) =>
                    setCurrentForPassword(event.target.value)
                  }
                />
              </label>
              <label>
                New password
                <input
                  name="new-password"
                  required
                  type="password"
                  minLength={12}
                  maxLength={1024}
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>
              <label>
                Confirm new password
                <input
                  name="password-confirmation"
                  ref={confirmationInput}
                  aria-invalid={error === "New passwords do not match."}
                  aria-describedby={
                    error === "New passwords do not match."
                      ? "account-error"
                      : undefined
                  }
                  required
                  type="password"
                  autoComplete="new-password"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                />
              </label>
              <button
                className="refresh-button"
                type="submit"
                disabled={busy}
                aria-busy={busy}
              >
                Change password
              </button>
            </form>
          </section>
        </div>
      )}
      {!usersOnly && session.role === "admin" && (
        <a href="#administration-users">Manage accounts and invitations</a>
      )}
      {session.role === "admin" && usersOnly && (
        <section
          className="account-card account-card--wide"
          aria-labelledby="account-users-title"
        >
          <h2 id="account-users-title" ref={usersHeading} tabIndex={-1}>
            Local accounts
          </h2>
          <p>
            Only administrators can invite people. Invitations expire after 24
            hours.
          </p>
          <form className="invite-form" onSubmit={sendInvite}>
            <label>
              Username
              <input
                name="invited-username"
                autoComplete="off"
                spellCheck={false}
                autoCapitalize="none"
                required
                minLength={3}
                maxLength={64}
                disabled={
                  ledgerUnavailable ||
                  Boolean(inviteCode) ||
                  Boolean(accountAction)
                }
                value={inviteName}
                onChange={(event) => setInviteName(event.target.value)}
              />
            </label>
            <label>
              Role
              <select
                name="invited-role"
                autoComplete="off"
                disabled={
                  ledgerUnavailable ||
                  Boolean(inviteCode) ||
                  Boolean(accountAction)
                }
                value={inviteRole}
                onChange={(event) =>
                  setInviteRole(event.target.value as "member" | "admin")
                }
              >
                <option value="member">Member</option>
                <option value="admin">Administrator</option>
              </select>
            </label>
            <button
              ref={inviteButton}
              className="refresh-button"
              disabled={
                ledgerUnavailable ||
                Boolean(inviteCode) ||
                Boolean(accountAction)
              }
              aria-busy={busy}
            >
              Create invitation
            </button>
          </form>
          {inviteCode && (
            <section
              className="invite-code"
              aria-labelledby="account-invite-title"
            >
              <h3 id="account-invite-title" ref={inviteHeading} tabIndex={-1}>
                One-time invitation code
              </h3>
              <code translate="no">{inviteCode}</code>
              <p>
                Share privately. The recipient opens Ark Cloud, chooses “Redeem
                invitation”, and enters this code. It will not appear again.
              </p>
              <button
                type="button"
                disabled={copying}
                onClick={() => void copyInvite()}
              >
                Copy invitation code
              </button>
              {copyNotice && (
                <p role={copyFailed ? "alert" : "status"}>{copyNotice}</p>
              )}
              <label className="account-invite-acknowledgment">
                <input
                  type="checkbox"
                  checked={inviteAcknowledged}
                  onChange={(event) =>
                    setInviteAcknowledged(event.target.checked)
                  }
                />
                I have saved this code and understand it will not be shown
                again.
              </label>
              <button
                type="button"
                disabled={!inviteAcknowledged || copying || busy}
                onClick={() => {
                  restoreInviteFocus.current = true;
                  setInviteCode(null);
                  setCopyNotice("");
                }}
              >
                Dismiss code
              </button>
            </section>
          )}
          {ledgerError && (
            <div className="account-ledger-warning">
              <p role="alert">
                Account list may be out of date. {ledgerError} Retry loading the
                list before making another account change.
              </p>
              <button
                type="button"
                disabled={busy || loadingUsers}
                onClick={() => void retryUsers()}
              >
                Retry loading accounts
              </button>
            </div>
          )}
          <ul className="account-users">
            {users.map((user) => (
              <li key={user.id}>
                <div>
                  <strong>{user.username}</strong>
                  <small>
                    {user.pending
                      ? "Invitation pending"
                      : user.active
                        ? "Active"
                        : "Disabled"}{" "}
                    · {user.role}
                  </small>
                </div>
                <div className="account-user-actions">
                  {user.pending && user.active && (
                    <button
                      type="button"
                      aria-label={`New code for ${user.username}`}
                      disabled={
                        ledgerUnavailable ||
                        Boolean(inviteCode) ||
                        Boolean(accountAction)
                      }
                      onClick={(event) =>
                        openAction("reissue", user, event.currentTarget)
                      }
                    >
                      New code
                    </button>
                  )}
                  <button
                    type="button"
                    aria-label={`Make ${user.role === "admin" ? "member" : "admin"} for ${user.username}`}
                    disabled={
                      ledgerUnavailable ||
                      Boolean(accountAction) ||
                      user.id === undefined ||
                      (user.username === session.username &&
                        user.role === "admin")
                    }
                    onClick={(event) =>
                      openAction("role", user, event.currentTarget)
                    }
                  >
                    {user.role === "admin" ? "Make member" : "Make admin"}
                  </button>
                  <button
                    type="button"
                    aria-label={`${user.active ? "Disable" : "Enable"} ${user.username}`}
                    disabled={
                      ledgerUnavailable ||
                      Boolean(accountAction) ||
                      user.username === session.username
                    }
                    onClick={(event) =>
                      user.active
                        ? openAction("disable", user, event.currentTarget)
                        : void run(() => enableAccount(user))
                    }
                  >
                    {user.active ? "Disable" : "Enable"}
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${user.username}`}
                    disabled={
                      ledgerUnavailable ||
                      Boolean(accountAction) ||
                      user.username === session.username
                    }
                    onClick={(event) =>
                      openAction("delete", user, event.currentTarget)
                    }
                  >
                    Delete
                  </button>
                </div>
                {actionPanel(user)}
              </li>
            ))}
          </ul>
          {loadingUsers && <p role="status">Loading accounts…</p>}
          {!loadingUsers && !ledgerError && users.length === 0 && (
            <p>No local accounts are available.</p>
          )}
        </section>
      )}
      {!usersOnly && (
        <p className="scope-note account-note">
          Changing your password signs out every device, including this one.
          Your account is stored on this Ark Cloud instance. Your files stay in
          their server storage locations when you update your login.
        </p>
      )}
    </div>
  );
}
