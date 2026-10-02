# Local storage (v0.9)

Local Files makes your host's files available through your Ark account. Google Drive remains an
optional metadata workspace. Files never pass through Google or live in PostgreSQL.

## Configure storage in Ark Cloud

Administrators use **Administration → Storage**. Account invitations and management live
under **Administration → Users**. Regular users choose their default location/folder inside
**Local Files**; that preference persists with their account across devices.

### Add and connect a location

Administration is a landing page with separate Storage and Users pages. Storage shows a locations
ledger; Add location, per-location access/configuration/activity, Settings, and Diagnostics are
distinct routed views. Refresh and browser Back/Forward preserve the selected view.

Choose **Add location**, enter its name, select a new or existing server folder, choose private
account folders or shared files, assign accounts, and press **Connect** once. Ark prepares narrow
filesystem access automatically, applies the mount, and verifies the running API before enabling
accounts. No command-copy panel, permission checkbox or separate review step is involved.

Normal `./scripts/ark up` provisions the deployment owner's storage helper and a dedicated
`~/Ark-Locations` area for new UI-created folders. Existing paths and credentials are preserved.
`ARK_STORAGE_MANAGED_AREA` can select a different **new** dedicated area at deployment time;
its identity is pinned in `.ark-storage/managed-area.json`. An unrelated existing directory is
never silently adopted. Linux, the acl package and a systemd user service are deployment prerequisites.
Owner-supervised installations retain the CLI below. User-service lifetime follows the deployment
owner's systemd login/linger configuration. Lifecycle helpers pause the manager during stack changes.

An existing directory must be inside an owner-authorized area. Ark inspects identity, ownership,
supported entry types and filesystem access, then applies narrow API ACLs to eligible owner-owned
directories/files and default ACLs for future content. ACL mask expansion preserves other users'
effective rights. File bodies and existing SELinux labels are preserved; new directories receive
the configured Ark-only labels. Symlinks, nested mounts, hard links, special files and foreign-owned
content cannot be silently traversed or re-permissioned. Host policy blockers appear in Diagnostics.

A failed runtime verification leaves one registered **Needs repair** location with account access
paused. Open its Connection page and press **Repair connection**. Repair reuses its registration,
prepares access automatically and restores failed initial account intent only after verification.
Selecting the same failed path in Add location also resolves to repair instead of an overlap error;
selecting an already-connected path opens the existing location. Genuine overlapping roots remain
unsupported. Retry re-evaluates automatic access rather than replaying an obsolete checkbox value.
The durable manager and ACL journals preserve recovery state; dismissing history does not release
access blocks. Missing or replaced disk identities require explicit owner review.

### Control account access

Every location has **Manage access**. Choose **No access**, **Read-only**, or **Read & write** for
each account by username. The editor shows effective permissions, disabled/invited account state,
and whether a private folder is ready. Saving private access explicitly creates that account's
folder when needed; status reads never do. Revoking access preserves files. Permission edits work
without a host-helper connection or container restart when the location is already applied.

`Ark-Files` is a **private-account base**: enabled accounts see only their own immutable-ID folder.
It is not a shared directory, and granting another account access never reveals your private files.
Existing active accounts retain access during the permissions migration; later accounts require
an explicit grant. Legacy assigned directories preserve their assigned account's initial access.

For a separate shared location, use **Add location → Shared files**, selecting account permissions
before connecting. Existing private bases are preserved. Authorized
users of a shared location see the same files; its permissions do not apply to private account folders.

The API enforces grants on every file operation. Read-only accounts cannot upload, create, rename,
move or delete. Host read-only mounts remain an upper limit. Upload publication rechecks the grant
version, including revoke/regrant changes made while a transfer is running. Grants use immutable
account IDs and location registrations, not usernames or labels. Removed registrations are retired;
recreating a location does not inherit its old shared permissions. Registration IDs are pinned across
explicitly reviewed identity refreshes and base relocation. Stale access editors cannot save into a
different registration or overwrite a newer permission revision. Account grants and their audit
history live in PostgreSQL, never file bodies; include them in your normal database backups.

The UI provides:

- **Connect folder:** browse approved server folders, pick accounts by username, choose access,
  review the path, and connect. Paths refer to the server, not the browser computer.
- **Create private account folders:** explicitly choose a new base directory. Ark applies a narrow
  mapped-UID ACL and private container labeling to this new tree, then creates private folders for
  selected accounts. Later accounts need an administrator's access grant.
- **Manage access:** directly grant or revoke per-account permissions; private folders remain isolated.
- **Configure:** change a label or host mount access mode. Advanced options expose explicit
  SELinux relabeling and a narrow ACL grant for a host-owned folder plus future content. Existing
  child permissions are not recursively changed.
- **Change base directory:** pause API writes, copy private account folders to a new directory,
  verify file hashes, modes and extended attributes/ACLs, then switch mounts. The original tree
  remains on disk. Pause external writers as well. There is no merge or overwrite of existing targets.
- **Disconnect:** revoke application access immediately and remove the mount configuration without
  deleting content or reversing ACLs/labels.
- **Check access:** verify as the API user; writable roots receive a temporary create/rename/remove
  probe. Basic status reads do not create account directories or test files.
- **Reconnect:** explicitly accept a reviewed root identity after checking that the correct disk
  and contents are present. Approved-area identities are pinned separately; if an approved area
  itself is replaced/remounted, its host owner must review and re-enroll it.
- **Maximum file size:** save a runtime per-file upload limit (1 byte–10 GiB). The environment value
  is the initial fallback; **Restore environment default** removes the UI override. New uploads
  use the effective policy, and the browser checks size before starting a transfer.
- **Activity & diagnostics:** current issues/progress are separate from finished history. Retry
  appears only when it applies to the current location, account and helper state; otherwise Ark
  explains the next step. Removed-location failures, canceled requests and superseded/resolved
  operations belong in **History**. Dismiss a terminal notification or dismiss historical
  notifications together; **Show dismissed** retains access to the records. Dismissal never
  releases an access block or cancels unfinished work. Queued UI requests expire after one hour;
  host setup is explicitly resumed by rerunning the command.

Mount changes briefly recreate the API, preserving PostgreSQL, the web service and content.
The browser reconnects automatically. A durable host journal reconciles interrupted operations,
including relocation while the API is stopped. Only one storage operation/manager process runs
at a time; the retained CLI shares the configuration lock. Queued requests can be canceled before
deployment begins. Completed operations require verification against the running API manifest and
mounts, not merely a successful host write.

An idle, authenticated helper reconciles stale blocks for removed roots only after the host
configuration matches the running manifest and the old mount is absent. It cannot release blocks
for existing locations this way; those require successful access verification.

The manager credential lives only in mode-0600 `.ark-storage/manager.json`; the API stores its hash.
The manager polls the loopback web proxy using typed requests. The API receives no Docker socket,
privileged namespaces, host-root mount or ability to run arbitrary host commands. Enrollment
delegates storage provisioning inside approved areas to Ark administrators; it does not give them
browser access to another account's content. Existing host configuration is imported when the
manager first reports its inventory. No existing directory or user preference is silently replaced.

## Owner CLI reference

The commands below are the fallback for host recovery or a deployment without the enrolled manager.

## Enable private account folders

Requirements: Linux x86_64/aarch64 with `openat2` (kernel 5.6+), Docker Compose v2 supporting
long-form bind options, Python 3.10+ on the host, and Fedora's `acl` package (`setfacl`). The API
continues running as `arkcloud`, not root. Build/start Ark and bootstrap your first account using
the README, then run:

```bash
./scripts/ark storage init
./scripts/ark up
./scripts/ark storage check
```

The default is a **new** `~/.local/share/ark-cloud/files` directory. Use
`./scripts/ark storage init --path /your/disk/ark-files` for another new directory. The owner tool
refuses an existing target rather than changing its permissions or labels silently. It probes the
API image's UID/GID mapping and grants its mapped host UID a narrow access/default ACL on this
new tree. Default ACLs retain host-owner access to newly created content. Verify host-side and
container-side access; permission modes shown by `ls` alone do not describe all ACL entries.

Configuration is kept in ignored `.ark-storage/host.json`, `.ark-storage/manifest.json`, and
`compose.storage.yaml`. The host file is authoritative, the API manifest contains only stable root
IDs, registration IDs, container paths, expected device/inode identity, mode, and legacy ownership.
The API cannot edit it; per-account grants are separately managed in PostgreSQL.
Use lifecycle commands under `./scripts/ark`: they include the storage override. Plain
`docker compose` intentionally uses the base stack without real content mounts for unit checks.
Do not run a base-only `docker compose up` against your integrated instance.

Each account gets `<data directory>/<immutable user UUID>`. Username changes preserve the UUID.
Administrators grant invited accounts private storage access and explicitly provision their folders.
Application admin status
does not grant browser access to another account's files. All files are accessible to the host
owner through their ACL; this is application account isolation, not encryption from the host owner.

## Register existing directories

List immutable account IDs on the host:

```bash
./scripts/ark storage users
./scripts/ark storage add --id photos --path /your/disk/photos --owner ACCOUNT_UUID --label Photos --selinux preserve
./scripts/ark up
./scripts/ark storage check
```

Use `--read-only` to enforce a read-only bind **and** API write restriction. `add` does not change
existing Unix permissions. Grant the mapped API UID the minimum permissions you intend, including
traverse/read on directories and write on parents for create/rename/delete. Review inheritance for
new files added by other host applications. Configure ACLs as the owner of that directory; do not
recursively chown an existing Documents or Photos tree to a container UID. `storage init` prints
the mapped UID for a new tree; Docker's UID mapping can be inspected with:

```bash
./scripts/ark exec api python -c 'import os; print(os.getuid(), os.getgid()); print(open("/proc/self/uid_map").read()); print(open("/proc/self/gid_map").read())'
```

Account assignments are host-owned; the enrolled manager applies approved administrator UI requests.
Without it, use the owner CLI. One assigned root
starts with one UUID owner's grant in the legacy CLI; use **Manage access** for additional accounts.
Sources cannot overlap the managed tree, another registered root, repository,
system/credential directories, or a whole home/root directory. Source and target symlinks are
rejected. Alias/bind mount arrangements that conceal overlap are unsupported; inspect them on the
host before registering. Nested filesystem mounts are not traversed by the API.

## Fedora, rootless Docker, and SELinux

Three independent checks matter: the bind mount exists, the mapped Unix UID/ACL permits access,
and SELinux permits access. Container UID 100 does **not** generally mean host UID 100 under
rootless Docker. Container root mapping to your login UID also does not make the API user your
login user. The provisioner probes mappings; it does not hard-code subordinate UID ranges.

Check both `getenforce` and `docker info --format '{{json .SecurityOptions}}'`. Fedora can be
enforcing while this Docker daemon does not use SELinux container confinement. Do not infer a
confined-container verification from `getenforce` alone.

- New Ark-owned data uses private `Z` relabeling. Docker may recursively change the host labels.
  The generated manifest also uses a private label and a read-only bind. It contains no passwords.
- Existing directories default to **no relabeling only when you explicitly choose `--selinux
  preserve`**. The existing label must already permit the intended access. Read-only mounts still
  need permission and an allowed label.
- `--selinux private` authorizes `Z`; `--selinux shared` authorizes `z`. `z` permits sharing between
  containers using the shared label; it is not read-only. A second container using `Z` can relabel
  data away from the first container's MCS category. Do not mount the same private tree in parallel
  test/init containers. Run `storage check` with `exec` in the existing API container.
- Review `ls -Zd` and `getfacl` on the selected tree and parent directories. An `EACCES` response
  cannot tell whether DAC or SELinux denied access. A host administrator can inspect AVC records
  with `ausearch -m AVC -ts recent`. If durable custom file-context rules are needed, review them
  with the host's policy administrator; never blindly generate allow rules or relabel an entire
  home/system directory. Preserve the previous context policy for rollback.
- Keep SELinux enforcing. Do not enable `--privileged`, disable labeling, or use blanket `777`
  modes to hide a denial. If a directory cannot retain its existing host/application use under
  an appropriate policy, copy selected content into the dedicated Ark tree instead.

Only the API receives content mounts. The web container, database, and telemetry configuration
do not. The daemon must be local to the filesystem the owner tool sees; remote Docker contexts
are unsupported by the provisioner.

## File behavior and limits

- Browse, upload/download, create folders, rename, move **within** a location, and permanently
  delete files/empty folders. Deletion requires explicit confirmation. There is no recursive
  deletion, trash, overwrite, cross-location move, public link, executable preview, or Drive sync.
- UTF-8 names, including ordinary dotfiles, are shown. Control characters, backslashes, traversal,
  symlinks, multi-linked regular files, special files, and `.ark-` reserved names are excluded.
  Choose a tree whose entire ordinary contents may be exposed to its owner; dotfiles are not a
  secret filter. Paths have at most 32 components/2,048 UTF-8 bytes; components at most 255 bytes.
- Listings stop at 10,000 entries and return 100 at a time. Changing directory membership
  invalidates pagination. Item revisions prevent ordinary stale moves/deletes/downloads. Host
  editors may change files outside Ark; downloads are live reads, not snapshots or version history.
- Default upload limit is 1 GiB. The administrator UI can override `ARK_STORAGE_UPLOAD_MAX_BYTES`
  at runtime (maximum 10 GiB), or restore that environment fallback.
  Four simultaneous uploads and eight downloads are supported in the single API worker. An upload
  idle for 60 seconds fails; browser cancellation and normal errors remove temporary content.
  Transfers stream in bounded chunks; the browser does not buffer a whole download into a Blob.
- Uploads stage in the destination directory as `.ark-upload-*`, fsync, recheck authorization and
  destination identity, and publish without replacing existing entries. A disconnect after publish
  or an fsync error can make the result uncertain: refresh before retrying. A process/host crash
  may leave reserved temporary files. With Ark stopped, the host owner can inspect and remove
  only confirmed orphan `.ark-upload-*` regular files. Never clean arbitrary hidden files.
- Missing mounts/identity mismatches fail closed. A separately mounted disk must be mounted before
  starting Ark; otherwise its empty mountpoint could be a different directory. Bind sources use
  `create_host_path: false`. If a filesystem is disconnected, stop/recreate Ark after reconnecting
  and run `storage check`; bind mounts need not track later host mount replacements. Device IDs
  can change across remounts/reboots. Verify the source disk, content, and owners, then explicitly
  run `./scripts/ark storage refresh-identity ROOT_ID --confirm` and recreate the stack. This
  deliberately accepts the currently mounted source's identity; never run it against an absent
  disk's empty mountpoint. Available bytes describe the shared filesystem, not a user quota.

Filesystem operations use descriptor-relative `openat2` resolution with no symlinks/mount crossings
and no-clobber `renameat2`. Only regular-file descriptors are reopened for downloads. Short writes
are handled, final mutations are serialized within the single API process, and uploads recheck
the session before publication. These protections isolate untrusted browser accounts; **host
processes able to rename directories or alter files are trusted**. No file manager can make a tree
controlled by a malicious host administrator a private sandbox. Pause external reorganizations
while making destructive changes through Ark. Do not run multiple API workers against the same
mounts without adding cross-process mutation coordination.

Uvicorn raw access logging is disabled because file URLs contain names. Structured successful
mutation events include only action/root ID/principal ID; configure Docker log rotation to bound
retention. Configure any outer proxy to avoid retaining sensitive file paths. Remote access remains
loopback plus Tailscale Serve HTTPS; use `ARK_COOKIE_SECURE=true` when accessing over HTTPS.

## Persistence, removal, and recovery

If Administration reports an invalid storage configuration, its Local Storage page still shows
host inventory and activity. On the host, inspect `.ark-storage/manifest.json`: the API needs to
read it, while `.ark-storage/manager.json` must remain private. If the manifest is valid but has
mode `600`, the deployment owner can run `chmod 644 .ark-storage/manifest.json` from the Ark
repository, then reload Administration. If the manifest is malformed or missing, review the
host-owned `.ark-storage/host.json` and generated `compose.storage.yaml` before regenerating or
restarting; do not replace the manifest with an empty one for a configured deployment.

Deleting an approved host area does not unregister a connected location. Disconnect the location
in Administration (or use the owner CLI below) without recreating the deleted directory. To use a
new area, first verify the intended disk and re-enroll the manager with an existing dedicated
directory; never accept an empty mountpoint as a replacement for a missing disk.

`up`, `restart`, and `down` preserve host content. Disabling or deleting a local account removes
access, **not** files. New accounts get new UUIDs even if a username is reused. To stop exposing an
assigned root, run `./scripts/ark storage remove ROOT_ID --confirm`, then `./scripts/ark up`.
This removes configuration only; it does not delete content, undo ACLs, or restore SELinux labels.

Back up these together: PostgreSQL (accounts and stable UUIDs), `.ark-storage/` and
`compose.storage.yaml` (assignments and sources), and the host file trees (including ACLs/xattrs).
Protect these backups: `.ark-storage/manager.json` now contains a host-manager credential; the
manifest itself still contains no secrets. Re-enroll after restoring if that credential is unavailable.
Stop file writes during a coordinated backup. A database backup alone contains no file bodies.
Test restoration to a separate location/instance, verify owner UUIDs, labels, ACLs, mount identity,
and file hashes, then verify another account cannot access them. Never use live paths for a restore
rehearsal. This phase does not implement an automatic backup service.

`reset-data --confirm` destroys database accounts/UUIDs and named volumes; bind-mounted files and
the host manifest survive. Restore the original database/configuration for original ownership.
For a deliberate transfer to a new account after losing the database, the owner must verify the
recipient UUID, stop Ark, and move the old managed UUID directory to the new UUID **only if the
new target is absent**, preserving metadata. For an assigned root, explicitly remove/re-add its
registration with the reviewed new UUID. Never infer ownership from a matching username. Resume
Ark and run `storage check`. Google credentials/tokens retain their existing recovery rules.
