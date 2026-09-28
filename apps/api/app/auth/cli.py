"""Local instance-owner account recovery; run only from the API container."""

import argparse
import getpass
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from sqlalchemy import delete, func, select

from app.auth.service import (
    normalize_username,
    now,
    session_secret,
    token_hash,
    validate_new_password,
)
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import AuthSession, BootstrapCode, GoogleDriveConnection, LocalUser, LoginAttempt


def main() -> None:
    parser = argparse.ArgumentParser(description="Ark Cloud local account owner commands")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bootstrap", help="Issue a 15-minute first-admin setup code")
    reset = commands.add_parser("reset-password", help="Reset an account from the local console")
    reset.add_argument("username")
    recover = commands.add_parser(
        "recover-admin", help="Restore admin access from the local console"
    )
    recover.add_argument("username")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.command == "bootstrap":
            if db.scalar(select(func.count()).select_from(LocalUser)) or db.scalar(
                select(func.count()).select_from(GoogleDriveConnection)
            ):
                parser.error("Accounts or legacy Drive data exist; setup cannot be reopened.")
            session_secret(db, get_settings())
            code = secrets.token_urlsafe(32)
            db.merge(
                BootstrapCode(
                    id=1, token_hash=token_hash(code), expires_at=now() + timedelta(minutes=15)
                )
            )
            db.execute(delete(LoginAttempt))
            db.commit()
            print(f"One-time setup code (expires in 15 minutes): {code}")
            return

        try:
            username = normalize_username(args.username)
        except ValueError as error:
            parser.error(str(error))
        user = db.scalar(select(LocalUser).where(LocalUser.username == username).with_for_update())
        if not user:
            parser.error("Account not found.")
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Confirm new password: "):
            parser.error("Passwords do not match.")
        try:
            validate_new_password(password)
        except ValueError as error:
            parser.error(str(error))
        user.password_hash = PasswordHasher().hash(password)
        user.active = True
        if args.command == "recover-admin":
            user.role = "admin"
        user.invite_hash = None
        user.invite_expires_at = None
        user.updated_at = now()
        db.execute(delete(AuthSession).where(AuthSession.principal_id == user.id))
        db.execute(delete(LoginAttempt))
        db.commit()
        print(f"Account {username} updated; existing sessions revoked.")


if __name__ == "__main__":
    main()
