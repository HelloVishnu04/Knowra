"""CLI script to manage Knowra user authentication and database.

Usage:
    python manage_users.py list
    python manage_users.py create --email <email> --password <pwd> [--role owner]
    python manage_users.py reset-password --email <email> --password <pwd>
    python manage_users.py set-role --email <email> --role <owner|administrator|member|viewer>
    python manage_users.py unlock [--email <email>]
    python manage_users.py delete --email <email>
"""

import argparse
import hashlib
import sys
import uuid

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import (
    AuthenticationThrottle,
    Organization,
    RefreshCredential,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
)


def list_users():
    with SessionLocal() as session:
        memberships = session.execute(
            select(User, Workspace, WorkspaceMember)
            .outerjoin(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .outerjoin(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .order_by(User.created_at)
        ).all()
        if not memberships:
            print("No users found in database.")
            return
        print(f"{'User ID':<38} {'Email':<30} {'Workspace':<25} {'Role':<10}")
        print("-" * 105)
        for user, ws, wm in memberships:
            ws_name = ws.name if ws else "None"
            role = wm.role if wm else "None"
            print(f"{user.id:<38} {user.email:<30} {ws_name:<25} {role:<10}")


def create_user(email: str, password: str, role: str = "owner"):
    email = email.strip().lower()
    with SessionLocal() as session:
        existing = session.scalar(select(User).where(User.email == email))
        if existing:
            print(f"Error: User with email '{email}' already exists.")
            sys.exit(1)

        user = User(
            id=str(uuid.uuid4()),
            email=email,
            hashed_password=hash_password(password),
        )
        org = Organization(id=str(uuid.uuid4()), name=f"{email} workspace")
        ws = Workspace(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            name=f"{email.split('@', 1)[0]}'s workspace",
        )
        membership = WorkspaceMember(
            id=str(uuid.uuid4()),
            workspace_id=ws.id,
            user_id=user.id,
            role=role,
        )
        session.add(user)
        session.add(org)
        session.add(ws)
        session.add(membership)
        session.commit()
        print(f"Successfully created user '{email}' with role '{role}' in workspace '{ws.name}'.")


def reset_password(email: str, password: str):
    email = email.strip().lower()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))
        if not user:
            print(f"Error: User with email '{email}' not found.")
            sys.exit(1)
        user.hashed_password = hash_password(password)
        # Clear any throttles
        email_throttle = f"email:{hashlib.sha256(email.encode()).hexdigest()}"
        session.execute(
            delete(AuthenticationThrottle).where(AuthenticationThrottle.id == email_throttle)
        )
        session.commit()
        print(f"Successfully reset password for user '{email}'.")


def set_role(email: str, role: str):
    email = email.strip().lower()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))
        if not user:
            print(f"Error: User with email '{email}' not found.")
            sys.exit(1)
        membership = session.scalar(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
        )
        if not membership:
            print(f"Error: No workspace membership found for '{email}'.")
            sys.exit(1)
        membership.role = role
        session.commit()
        print(f"Successfully updated role for '{email}' to '{role}'.")


def unlock_accounts(email: str | None = None):
    with SessionLocal() as session:
        if email:
            digest = f"email:{hashlib.sha256(email.strip().lower().encode()).hexdigest()}"
            session.execute(
                delete(AuthenticationThrottle).where(AuthenticationThrottle.id == digest)
            )
            print(f"Cleared lockouts for email '{email}'.")
        else:
            session.execute(delete(AuthenticationThrottle))
            print("Cleared all rate limits and lockouts.")
        session.commit()


def delete_user(email: str):
    email = email.strip().lower()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))
        if not user:
            print(f"Error: User with email '{email}' not found.")
            sys.exit(1)
        # Delete sessions, refresh tokens, workspace members
        sessions = session.scalars(
            select(UserSession).where(UserSession.user_id == user.id)
        ).all()
        session_ids = [s.id for s in sessions]
        if session_ids:
            session.execute(
                delete(RefreshCredential).where(
                    RefreshCredential.session_id.in_(session_ids)
                )
            )
            session.execute(delete(UserSession).where(UserSession.user_id == user.id))
        session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
        session.execute(delete(User).where(User.id == user.id))
        session.commit()
        print(f"Successfully deleted user '{email}'.")


def main():
    parser = argparse.ArgumentParser(description="Manage Knowra users and authentication.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all users and their roles")

    create_parser = subparsers.add_parser("create", help="Create a new user")
    create_parser.add_argument("--email", required=True)
    create_parser.add_argument("--password", required=True)
    create_parser.add_argument("--role", default="owner", choices=["owner", "administrator", "member", "viewer"])

    pwd_parser = subparsers.add_parser("reset-password", help="Reset a user password")
    pwd_parser.add_argument("--email", required=True)
    pwd_parser.add_argument("--password", required=True)

    role_parser = subparsers.add_parser("set-role", help="Update workspace role")
    role_parser.add_argument("--email", required=True)
    role_parser.add_argument("--role", required=True, choices=["owner", "administrator", "member", "viewer"])

    unlock_parser = subparsers.add_parser("unlock", help="Clear failed login throttles/lockouts")
    unlock_parser.add_argument("--email", required=False)

    del_parser = subparsers.add_parser("delete", help="Delete user")
    del_parser.add_argument("--email", required=True)

    args = parser.parse_args()

    if args.command == "list":
        list_users()
    elif args.command == "create":
        create_user(args.email, args.password, args.role)
    elif args.command == "reset-password":
        reset_password(args.email, args.password)
    elif args.command == "set-role":
        set_role(args.email, args.role)
    elif args.command == "unlock":
        unlock_accounts(args.email)
    elif args.command == "delete":
        delete_user(args.email)


if __name__ == "__main__":
    main()
