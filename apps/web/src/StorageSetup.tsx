import { useState } from "react";
import type { StorageAdministration } from "./storageAdminApi";

export default function StorageSetup({
  data,
  onConnect,
}: {
  data: StorageAdministration;
  onConnect: () => void;
}) {
  const [choice, setChoice] = useState<"new" | "existing">("new");
  const [copied, setCopied] = useState("");
  const managed = data.roots.find((root) => root.kind === "managed");
  const job = data.setup.job;
  const running =
    job && ["applying", "verifying", "queued"].includes(job.state);
  const ready = managed?.state === "healthy" && !running;
  const command = "./scripts/ark storage setup";
  const existingCommand =
    './scripts/ark storage manager enroll --approve "/absolute/path/to/existing/folder" --install';
  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied("Command copied. Run it in a terminal on the Ark server.");
    } catch {
      setCopied(
        "Select and copy the command below, then run it on the Ark server.",
      );
    }
  }
  function existingHelp() {
    return (
      <>
        <p>
          From the ArkCloud repository on the host, run this as the deployment
          owner. Replace the quoted path with your existing dedicated directory.
          This enables the helper; it does not grant file access yet.
        </p>
        <pre>
          <code>{existingCommand}</code>
        </pre>
        <button type="button" onClick={() => void copy(existingCommand)}>
          Copy existing-folder command
        </button>
        <p>
          When the helper connects, choose your folder here and assign an
          account. Use an absolute host path; do not use a whole home or system
          directory. Already-connected locations retain management access.
        </p>
      </>
    );
  }
  return (
    <section
      className="panel storage-section storage-setup"
      aria-labelledby="setup-heading"
    >
      <h3 id="setup-heading">
        {ready
          ? "Local Files is ready"
          : managed
            ? "Restore Local Files"
            : "Set up Local Files"}
      </h3>
      {ready ? (
        <>
          <p>
            Your private account folders live on the Ark server at{" "}
            <span className="storage-path">{managed.source}</span>.
          </p>
          <a className="storage-open-files" href={`#local-files/${managed.id}`}>
            Open my files
          </a>
          {!data.manager.online && (
            <details>
              <summary>Reconnect the host helper</summary>
              <p>
                Your files are connected. Run <code>{command}</code> from the
                ArkCloud repository on the host to restore UI storage
                management. It verifies your existing base without replacing it.
              </p>
            </details>
          )}
          <details>
            <summary>Connect another host folder</summary>
            {existingHelp()}
          </details>
        </>
      ) : (
        <>
          {!managed && !running && (
            <fieldset className="storage-setup-choice">
              <legend>How would you like to start?</legend>
              <label className="storage-checkbox">
                <input
                  type="radio"
                  name="storage-setup"
                  checked={choice === "new"}
                  onChange={() => setChoice("new")}
                />
                Create my cloud storage
              </label>
              <label className="storage-checkbox">
                <input
                  type="radio"
                  name="storage-setup"
                  checked={choice === "existing"}
                  onChange={() => setChoice("existing")}
                />
                Connect an existing folder
              </label>
            </fieldset>
          )}
          {choice === "new" || managed || running ? (
            <>
              <p>
                {managed ? (
                  "Ark will verify and reconnect your existing private-folder base."
                ) : (
                  <>
                    Ark creates <strong>{data.setup.default_path}</strong> on
                    the host, connects it, and gives each account a separate
                    private folder. You do not need to create the directory
                    yourself.
                  </>
                )}
              </p>
              <ol className="storage-setup-steps">
                <li>
                  <strong>Open a terminal on the Ark server</strong>
                  <p>
                    Use the host account that runs Ark and open the ArkCloud
                    repository
                    {data.setup.repository_path && (
                      <>
                        {" "}
                        at <code>{data.setup.repository_path}</code>
                      </>
                    )}
                    . Run this on the server, not inside a container or on a
                    separate browser computer.
                  </p>
                </li>
                <li>
                  <strong>Run the setup command</strong>
                  <pre>
                    <code>{command}</code>
                  </pre>
                  <button type="button" onClick={() => void copy(command)}>
                    Copy setup command
                  </button>
                  <p>
                    Ark configures access, enables the host helper, and verifies
                    storage. Mount changes briefly restart the API. Existing
                    directories are never overwritten.
                  </p>
                </li>
                <li>
                  <strong>
                    {data.setup.interrupted
                      ? "Resume the host setup command"
                      : running
                        ? "Setting up Local Files"
                        : "Return here to open your files"}
                  </strong>
                  <p role="status">
                    {data.setup.interrupted
                      ? "Setup has not reported progress recently. If the host command stopped, rerun the same command to resume. An unfinished operation is kept until it can be verified."
                      : running
                        ? job.message
                        : "This page checks setup progress automatically. No second configuration step is needed."}
                  </p>
                </li>
              </ol>
              {job?.state === "failed" && (
                <div className="storage-setup-failure">
                  <p className="local-error" role="alert">
                    {job.message}
                  </p>
                  <p>
                    Correct the reported problem and rerun the same setup
                    command. Ark resumes saved setup without creating duplicate
                    locations.
                  </p>
                </div>
              )}
              {managed && <p className="local-error">{managed.message}</p>}
              <details>
                <summary>
                  Choose a different directory or resolve an existing-folder
                  conflict
                </summary>
                <p>
                  If the default directory already exists and is not
                  Ark-managed, connect it using the existing-folder option, or
                  choose a new directory with{" "}
                  <code>
                    ./scripts/ark storage setup --path
                    "/absolute/path/to/new-folder"
                  </code>
                  . Changing an established base uses Change base directory
                  below.
                </p>
                <p>
                  For a missing or replaced disk, verify the disk and use
                  Reconnect or Disconnect below. Setup never silently accepts a
                  different directory identity. New storage receives Ark-only
                  container labels. Without systemd user services, use{" "}
                  <code>--no-install</code> and supervise the host helper.
                </p>
              </details>
            </>
          ) : (
            <>
              <p>
                Connect a directory already on the server to one Ark account.
                Its existing files stay in place.
              </p>
              {data.manager.online ? (
                <>
                  <p>
                    Choose a folder inside an approved host area, then select
                    the account and access mode.
                  </p>
                  <button
                    type="button"
                    className="refresh-button"
                    onClick={onConnect}
                    disabled={Boolean(data.configuration_error)}
                  >
                    Choose existing folder
                  </button>
                  <details>
                    <summary>
                      Authorize a folder outside the approved areas
                    </summary>
                    {existingHelp()}
                  </details>
                </>
              ) : (
                existingHelp()
              )}
            </>
          )}
        </>
      )}
      {copied && <p role="status">{copied}</p>}
    </section>
  );
}
