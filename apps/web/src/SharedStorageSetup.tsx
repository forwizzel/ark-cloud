import { useState } from "react";

export default function SharedStorageSetup({
  canCreate,
  onCreate,
}: {
  canCreate: boolean;
  onCreate: () => void;
}) {
  const [notice, setNotice] = useState("");
  const command = "./scripts/ark storage setup --shared";
  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setNotice(
        "Command copied. Run it from the ArkCloud repository on the host.",
      );
    } catch {
      setNotice("Select and copy the command below to run it on the host.");
    }
  }
  return (
    <section
      className="panel storage-section"
      aria-labelledby="shared-setup-heading"
    >
      <h3 id="shared-setup-heading">Create a shared folder</h3>
      <p>
        A shared location lets selected accounts see the same files. Keep it
        separate from Ark-Files, which contains isolated private folders.
      </p>
      <p>
        Run this from the ArkCloud repository on the server, as the host
        deployment owner. Ark creates a new <strong>~/Ark-Shared</strong>,
        connects it, and verifies access.
      </p>
      <pre>
        <code>{command}</code>
      </pre>
      <button type="button" onClick={() => void copy()}>
        Copy shared setup command
      </button>
      {notice && <p role="status">{notice}</p>}
      <p>
        When the location appears below, choose <strong>Manage access</strong>{" "}
        to grant accounts read-only or read/write access. Shared locations start
        with no account access. Existing unregistered directories are never
        overwritten.
      </p>
      <details>
        <summary>Create inside an already-approved host area</summary>
        <p>
          Choose a new directory inside an approved area that does not overlap
          any connected location. You can select account permissions before
          connecting it.
        </p>
        <button type="button" disabled={!canCreate} onClick={onCreate}>
          Choose new shared directory
        </button>
      </details>
    </section>
  );
}
