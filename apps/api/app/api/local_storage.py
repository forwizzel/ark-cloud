import asyncio
import os
import secrets
import threading
from contextlib import contextmanager, suppress
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.auth.service import SESSION_COOKIE, Principal, get_session
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.dependencies import require_csrf, require_principal
from app.models import LocalUser
from app.services.local_storage import (
    MUTATIONS,
    LocalStorage,
    StorageError,
    filesystem_error,
    load_manifest,
    rename_exclusive,
)
from app.services.storage_control import upload_limit


class StorageRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def normalized(request):
            try:
                return await handler(request)
            except (OSError, StorageError) as error:
                failure = error if isinstance(error, StorageError) else filesystem_error(error)
                raise HTTPException(failure.status, str(failure)) from error

        return normalized


router = APIRouter(prefix="/storage", tags=["local-storage"], route_class=StorageRoute)
# The supported deployment is one API worker. Bound uploads independently of listing/downloads.
transfers = threading.BoundedSemaphore(4)
downloads = threading.BoundedSemaphore(8)


def get_storage(settings: Annotated[Settings, Depends(get_settings)]) -> LocalStorage:
    return LocalStorage(load_manifest(settings.storage_manifest))


Storage = Annotated[LocalStorage, Depends(get_storage)]
Reader = Annotated[Principal, Depends(require_principal)]
Writer = Annotated[Principal, Depends(require_csrf)]
PathQuery = Annotated[str, Query(max_length=2048)]
RevisionQuery = Annotated[str, Query(pattern=r"^[a-f0-9]{32}$")]


class CreateFolder(BaseModel):
    path: str = Field(min_length=1, max_length=2048)


class MoveItem(CreateFolder):
    destination: str = Field(min_length=1, max_length=2048)
    revision: str = Field(pattern=r"^[a-f0-9]{32}$")


@router.get("/roots")
def roots(principal: Reader, storage: Storage):
    return storage.locations(principal.id)


@router.get("/{root_id}/items")
def items(
    root_id: str,
    principal: Reader,
    storage: Storage,
    path: PathQuery = "",
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    revision: RevisionQuery | None = None,
):
    if offset and not revision:
        raise StorageError("A folder revision is required for pagination.", 422)
    return storage.listing(root_id, principal.id, path, offset, revision)


@router.post("/{root_id}/folders", status_code=201)
def create_folder(root_id: str, body: CreateFolder, principal: Writer, storage: Storage):
    storage.mkdir(root_id, principal.id, body.path)
    return {"message": "Folder created."}


@router.post("/{root_id}/move", status_code=204)
def move(root_id: str, body: MoveItem, principal: Writer, storage: Storage):
    storage.move(root_id, principal.id, body.path, body.destination, body.revision)
    return Response(status_code=204)


@router.delete("/{root_id}/items", status_code=204)
def delete(
    root_id: str,
    principal: Writer,
    storage: Storage,
    path: PathQuery,
    revision: RevisionQuery,
    confirm: Annotated[bool, Query()] = False,
):
    if not confirm:
        raise StorageError("Confirm permanent deletion first.", 422)
    storage.delete(root_id, principal.id, path, revision)
    return Response(status_code=204)


@router.get("/{root_id}/download")
def download(
    root_id: str, principal: Reader, storage: Storage, path: PathQuery, revision: RevisionQuery
):
    if not downloads.acquire(blocking=False):
        raise StorageError("All download slots are busy. Retry shortly.", 429)
    try:
        fd, size = storage.download(root_id, principal.id, path, revision)
    except BaseException:
        downloads.release()
        raise
    source = os.fdopen(fd, "rb")

    def close():
        if not source.closed:
            source.close()
            downloads.release()

    def chunks():
        try:
            remaining = size
            while remaining:
                chunk = source.read(min(262_144, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            close()

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(path.split("/")[-1], safe=""),
            "Content-Length": str(size),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, no-store",
        },
        background=BackgroundTask(close),
    )


def still_authorized(request: Request, settings: Settings, owner: str):
    # A long upload must not publish after logout, account deletion, or session revocation.
    with SessionLocal() as db:
        session = get_session(db, settings, request.cookies.get(SESSION_COOKIE))
        user = db.get(LocalUser, owner)
        if session is None or session.principal_id != owner or user is None or not user.active:
            raise StorageError("Session expired. Sign in before retrying the upload.", 401)


@contextmanager
def transfer_slot():
    if not transfers.acquire(blocking=False):
        raise StorageError("All four upload slots are busy. Retry shortly.", 429)
    try:
        yield
    finally:
        transfers.release()


@router.post("/{root_id}/upload", status_code=201)
async def upload(
    root_id: str,
    request: Request,
    principal: Writer,
    storage: Storage,
    settings: Annotated[Settings, Depends(get_settings)],
    path: PathQuery,
):
    if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
        raise StorageError("Upload a raw file with application/octet-stream content type.", 415)
    maximum = upload_limit(settings)
    length = request.headers.get("content-length")
    if length and (not length.isdecimal() or int(length) > maximum):
        raise StorageError(f"Upload exceeds the {maximum}-byte limit.", 413)
    with (
        transfer_slot(),
        storage.root(root_id, principal.id, write=True) as root,
        storage.parent(root, path) as (parent, name),
    ):
        temp = f".ark-upload-{secrets.token_hex(16)}"
        fd = os.open(
            temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=parent
        )
        try:
            with os.fdopen(fd, "wb", buffering=0) as target:
                stream = request.stream().__aiter__()
                total = 0
                while True:
                    try:
                        chunk = await asyncio.wait_for(anext(stream), timeout=60)
                    except StopAsyncIteration:
                        break
                    except TimeoutError as error:
                        raise StorageError("Upload timed out. Retry the file.", 408) from error
                    total += len(chunk)
                    if total > maximum:
                        raise StorageError(f"Upload exceeds the {maximum}-byte limit.", 413)
                    await run_in_threadpool(write_all, target, chunk)
                await run_in_threadpool(os.fsync, target.fileno())
            await run_in_threadpool(
                publish, storage, root_id, principal.id, path, parent, temp, name, request, settings
            )
            storage.audit("upload", root_id, principal.id)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temp, dir_fd=parent)
    return {"message": "Upload complete.", "size_bytes": total}


def write_all(target, chunk: bytes):
    view = memoryview(chunk)
    while view:
        written = target.write(view)
        if not written:
            raise OSError("Incomplete write")
        view = view[written:]


def publish(storage, root_id, owner, path, parent, temp, name, request, settings):
    with MUTATIONS:
        still_authorized(request, settings, owner)
        current = LocalStorage(load_manifest(settings.storage_manifest))
        if current.config(root_id, owner) != storage.config(root_id, owner):
            raise StorageError("Storage configuration changed during upload. Refresh and retry.")
        with (
            current.root(root_id, owner, write=True) as root,
            current.parent(root, path) as (fd, _),
        ):
            old, new = os.fstat(parent), os.fstat(fd)
            if (old.st_dev, old.st_ino) != (new.st_dev, new.st_ino):
                raise StorageError("Destination folder moved during upload. Refresh and retry.")
            rename_exclusive(parent, temp, parent, name)
            os.fsync(parent)
