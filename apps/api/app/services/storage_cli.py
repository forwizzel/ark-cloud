"""Diagnostics run as the API user in the live container, not as container root."""

import os
import secrets
import sys
from contextlib import suppress

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import LocalUser
from app.services.local_storage import LocalStorage, StorageError, load_manifest, rename_exclusive


def main():
    with SessionLocal() as db:
        users = db.scalars(select(LocalUser).order_by(LocalUser.username)).all()
        if sys.argv[1:] == ["users"]:
            for user in users:
                print(f"{user.id}  {user.username}  {'active' if user.active else 'disabled'}")
            return
        storage = LocalStorage(load_manifest(get_settings().storage_manifest), verification=True)
        if not storage.manifest.roots:
            sys.exit("No local roots configured. Run ./scripts/ark storage init on the host.")
        failed = False
        for config in storage.manifest.roots:
            owner = "host-check"
            try:
                with storage.root(config.id, owner, write=not config.read_only, base=True) as root:
                    if not config.read_only:
                        name = f".ark-probe-{secrets.token_hex(8)}"
                        moved = name + "-moved"
                        try:
                            fd = os.open(
                                name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=root
                            )
                            os.close(fd)
                            rename_exclusive(root, name, root, moved)
                        finally:
                            for candidate in [name, moved]:
                                with suppress(FileNotFoundError):
                                    os.unlink(candidate, dir_fd=root)
                    print(
                        f"{config.id}: ready "
                        f"({'read-only' if config.read_only else 'read/write'}), "
                        f"API UID {os.getuid()}"
                    )
            except (OSError, StorageError) as error:
                print(f"{config.id}: unavailable: {error}")
                failed = True
        if failed:
            sys.exit(1)


if __name__ == "__main__":
    main()
