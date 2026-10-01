"""Host-only enrollment, accepting secrets through stdin rather than arguments/logs."""

import argparse
import json
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.api.storage_admin import begin_setup
from app.auth.service import token_hash
from app.core.database import SessionLocal
from app.models import StorageJob
from app.services.storage_control import control


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--begin", action="store_true")
    actions.add_argument("--progress", action="store_true")
    actions.add_argument("--job-id")
    args = parser.parse_args()
    if args.begin or args.progress or args.job_id:
        with SessionLocal() as db:
            if args.job_id:
                job = db.get(StorageJob, args.job_id)
                print(json.dumps({"state": job.state if job else None}))
                return
            body = json.load(sys.stdin)
            if args.begin:
                from app.api.storage_admin import Preference

                root = Preference(root_id=body["root_id"])
                path = body["path"]
                if not isinstance(path, str) or not path.startswith("/") or len(path) > 4096:
                    sys.exit("Choose an absolute host path.")
                try:
                    result = begin_setup(db, path, root.root_id)
                    print(json.dumps({"id": result["id"]}))
                except ValueError as error:
                    print(json.dumps({"error": str(error)}))
            else:
                job = db.get(StorageJob, body["id"])
                if not job or job.action != "setup" or job.state not in {"applying", "verifying"}:
                    sys.exit("No active host setup matches this request.")
                if body["state"] not in {"applying", "failed"}:
                    sys.exit("Host progress cannot bypass API verification.")
                job.state = body["state"]
                job.message = str(body["message"])[:2000]
                job.updated_at = datetime.now(UTC)
                db.commit()
                print(json.dumps({"recorded": True}))
        return
    token = sys.stdin.readline().strip()
    if len(token) < 40:
        sys.exit("A randomly generated enrollment token is required.")
    with SessionLocal() as db:
        value = control(db)
        active = db.scalars(
            select(StorageJob).where(StorageJob.state.in_(("queued", "applying", "verifying")))
        ).all()
        if active and (not args.setup or any(job.action != "setup" for job in active)):
            sys.exit("Finish the active storage operation before re-enrolling.")
        value.token_hash = token_hash(token)
        value.last_seen_at = None
        db.commit()
    print(json.dumps({"enrolled": True}))


if __name__ == "__main__":
    main()
