"""Account grants are control-plane metadata, bounded by host-approved mounts."""

from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import LocalUser, StorageGrant, StorageLocation
from app.services.storage_control import control


def registration(root):
    if root.registration:
        return root.registration
    name = f"ark-storage:{root.id}:{root.kind}:{root.device}:{root.inode}:{root.owner or ''}"
    return str(uuid5(NAMESPACE_URL, name))


def ensure_location(db, root):
    """Import once. Later accounts never acquire implicit private-storage access."""
    identity = registration(root)
    location = db.get(StorageLocation, identity)
    if location is not None:
        if location.root_id != root.id or location.kind != root.kind:
            from app.services.local_storage import StorageError

            raise StorageError(
                "Storage registration changed identity or type. Register a separate location.", 503
            )
        return location
    control(db)  # Serialize first import against concurrent requests and grant edits.
    location = db.get(StorageLocation, identity, populate_existing=True)
    if location is not None:
        if location.root_id != root.id or location.kind != root.kind:
            from app.services.local_storage import StorageError

            raise StorageError(
                "Storage registration changed identity or type. Register a separate location.", 503
            )
        return location
    location = StorageLocation(
        id=identity, root_id=root.id, kind=root.kind, retired=False, revision=0
    )
    db.add(location)
    db.flush()
    users = db.scalars(select(LocalUser).where(LocalUser.active.is_(True))).all()
    for user in users:
        if root.kind == "managed" or (root.kind == "assigned" and root.owner == user.id):
            db.add(
                StorageGrant(
                    location_id=identity,
                    principal_id=user.id,
                    level="read" if root.read_only else "write",
                    version=str(uuid4()),
                )
            )
    db.flush()
    return location


def authorization(root, principal_id):
    with SessionLocal() as db:
        location = ensure_location(db, root)
        user = db.get(LocalUser, principal_id)
        grant = db.get(StorageGrant, (location.id, principal_id))
        if (
            location.retired
            or user is None
            or not user.active
            or grant is None
            or grant.level not in {"read", "write"}
        ):
            result = ("none", location.id, None)
        else:
            level = "read" if root.read_only else grant.level
            result = (level, location.id, grant.version)
        db.commit()
        return result


def retire_missing(db, manifest):
    present = {registration(root) for root in manifest.roots}
    for location in db.scalars(select(StorageLocation).where(StorageLocation.retired.is_(False))):
        if location.id not in present:
            location.retired = True
