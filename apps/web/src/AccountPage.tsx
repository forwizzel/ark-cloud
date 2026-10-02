import { FormEvent, useEffect, useRef, useState } from "react";
import useUnsavedChanges from "./useUnsavedChanges";

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
  const [deleting, setDeleting] = useState<LocalUser | null>(null);
  const [deleteName, setDeleteName] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [users, setUsers] = useState<LocalUser[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(usersOnly);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const csrf = session.csrf_token ?? "";
  const confirmationInput = useRef<HTMLInputElement>(null);
  const errorNotice = useRef<HTMLParagraphElement>(null);
  const discardChanges = useUnsavedChanges(
    username !== (session.username ?? "") ||
      Boolean(
        currentForName ||
        currentForPassword ||
        password ||
        confirmation ||
        inviteName ||
        deleteName ||
        deletePassword,
      ),
  );
  useEffect(() => {
    if (error && error !== "New passwords do not match.")
      errorNotice.current?.focus();
  }, [error]);

  const fetchUsers = () =>
    listUsers()
      .then(setUsers)
      .catch((reason: unknown) => {
        setError(
          reason instanceof Error ? reason.message : "Unable to load accounts.",
        );
      })
      .finally(() => setLoadingUsers(false));
  const refreshUsers = () => {
    setLoadingUsers(true);
    return fetchUsers();
  };

  useEffect(() => {
    if (session.role === "admin" && usersOnly) void fetchUsers();
  }, [session.role, usersOnly]);

  async function run(action: () => Promise<void>) {
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
    void run(async () => {
      const result = await inviteUser(inviteName, inviteRole, csrf);
      setInviteCode(result.token);
      setInviteName("");
      await refreshUsers();
      setNotice(
        "Invitation created. Copy the code now; it will not be shown again.",
      );
    });
  }

  function confirmDelete(event: FormEvent) {
    event.preventDefault();
    if (!deleting) return;
    void run(async () => {
      await deleteUser(deleting.id, deleteName, deletePassword, csrf);
      setDeleting(null);
      setDeleteName("");
      setDeletePassword("");
      setNotice("Account deleted. Local files remain on the host.");
      await refreshUsers();
    });
  }

  return (
    <div className="account-page">
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
          <h2 id="account-users-title">Local accounts</h2>
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
                value={inviteName}
                onChange={(event) => setInviteName(event.target.value)}
              />
            </label>
            <label>
              Role
              <select
                name="invited-role"
                autoComplete="off"
                value={inviteRole}
                onChange={(event) =>
                  setInviteRole(event.target.value as "member" | "admin")
                }
              >
                <option value="member">Member</option>
                <option value="admin">Administrator</option>
              </select>
            </label>
            <button className="refresh-button" disabled={busy} aria-busy={busy}>
              Create invitation
            </button>
          </form>
          {inviteCode && (
            <div className="invite-code" role="status">
              <strong>One-time invitation code</strong>
              <code translate="no">{inviteCode}</code>
              <p>
                Share privately. The recipient opens Ark Cloud, chooses “Redeem
                invitation”, and enters this code. It will not appear again.
              </p>
              <p>
                Local files remain on the host. This account’s storage
                assignments lose access; they are not inherited by a new account
                with the same username.
              </p>
              <button type="button" onClick={() => setInviteCode(null)}>
                Dismiss code
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
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          const result = await reissueInvite(user.id, csrf);
                          setInviteCode(result.token);
                          setNotice(
                            "New invitation code issued; the old code no longer works.",
                          );
                        })
                      }
                    >
                      New code
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={
                      busy ||
                      user.id === undefined ||
                      (user.username === session.username &&
                        user.role === "admin")
                    }
                    onClick={() =>
                      void run(async () => {
                        await updateUser(
                          user.id,
                          { role: user.role === "admin" ? "member" : "admin" },
                          csrf,
                        );
                        await refreshUsers();
                      })
                    }
                  >
                    {user.role === "admin" ? "Make member" : "Make admin"}
                  </button>
                  <button
                    type="button"
                    disabled={busy || user.username === session.username}
                    onClick={() =>
                      void run(async () => {
                        await updateUser(
                          user.id,
                          { active: !user.active },
                          csrf,
                        );
                        await refreshUsers();
                      })
                    }
                  >
                    {user.active ? "Disable" : "Enable"}
                  </button>
                  <button
                    type="button"
                    disabled={busy || user.username === session.username}
                    onClick={() => {
                      if (!discardChanges()) return;
                      setDeleting(user);
                      setDeleteName("");
                      setDeletePassword("");
                    }}
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
          {loadingUsers && <p role="status">Loading accounts…</p>}
          {!loadingUsers && !error && users.length === 0 && (
            <p>No local accounts are available.</p>
          )}
          {deleting && (
            <form className="account-delete" onSubmit={confirmDelete}>
              <h3>Delete {deleting.username}?</h3>
              <p>
                This permanently removes the account and its access permissions.
                Local files remain on the host.
              </p>
              <label>
                Type {deleting.username} to confirm
                <input
                  name="delete-confirmation"
                  autoComplete="off"
                  spellCheck={false}
                  autoCapitalize="none"
                  required
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
                  value={deletePassword}
                  onChange={(event) => setDeletePassword(event.target.value)}
                />
              </label>
              <button
                type="submit"
                disabled={busy || deleteName !== deleting.username}
              >
                Delete account
              </button>
              <button
                type="button"
                onClick={() => {
                  if (discardChanges()) {
                    setDeleting(null);
                    setDeleteName("");
                    setDeletePassword("");
                  }
                }}
              >
                Cancel
              </button>
            </form>
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
