"""Owner-only enrollment over Compose stdin; no browser bootstrap secret."""

import json
import sys

from app.auth.service import token_hash
from app.core.database import SessionLocal
from app.models import SystemControl
from app.schemas.system_host import Policy
from app.services.system_control import audit


def main():
    request = json.loads(sys.stdin.read(16384))
    policy = Policy.model_validate(request["policy"])
    with SessionLocal() as db:
        control = db.get(SystemControl, 1)
        if control is None:
            control = SystemControl(id=1)
            db.add(control)
        control.token_hash = token_hash(request["token"]) if request["token"] else None
        control.policy = policy.model_dump()
        audit(db, "host-owner", "agent_enroll" if request["token"] else "agent_revoke")
        db.commit()


if __name__ == "__main__":
    main()
