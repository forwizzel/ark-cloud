# Local storage (v0.9)

Local Files makes your host's files available through your Ark account. Google Drive remains an
optional metadata workspace. Files never pass through Google or live in PostgreSQL.

## Enable private account folders

Requirements: Linux x86_64/aarch64 with `openat2` (kernel 5.6+), Docker Compose v2 supporting
long-form bind options, Python 3 on the host, and Fedora's `acl` package (`setfacl`). The API
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
IDs, container paths, expected device/inode identity, mode, and ownership. The API cannot edit it.
Use lifecycle commands under `./scripts/ark`: they include the storage override. Plain
`docker compose` intentionally uses the base stack without real content mounts for unit checks.
Do not run a base-only `docker compose up` against your integrated instance.

Each account gets `<data directory>/<immutable user UUID>`. Username changes preserve the UUID.
Invited users get their own folder when they first access Local Files. Application admin status
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

Account assignments are owner-operated; there is no browser root-assignment API. One assigned root
has one UUID owner. Sources cannot overlap the managed tree, another registered root, repository,
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
- Default upload limit is 1 GiB, configurable with `ARK_STORAGE_UPLOAD_MAX_BYTES` (maximum 10 GiB).
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

`up`, `restart`, and `down` preserve host content. Disabling or deleting a local account removes
access, **not** files. New accounts get new UUIDs even if a username is reused. To stop exposing an
assigned root, run `./scripts/ark storage remove ROOT_ID --confirm`, then `./scripts/ark up`.
This removes configuration only; it does not delete content, undo ACLs, or restore SELinux labels.

Back up these together: PostgreSQL (accounts and stable UUIDs), `.ark-storage/` and
`compose.storage.yaml` (assignments and sources), and the host file trees (including ACLs/xattrs).
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
