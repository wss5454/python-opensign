from __future__ import annotations

from typing import Optional
from urllib.parse import quote

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, User, get_db


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        return False


def ensure_admin_user() -> None:
    """Create/update the default admin from env credentials."""
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == settings.admin_email).first()
        password_hash = hash_password(settings.admin_password)
        if admin is None:
            admin = User(
                name=settings.admin_name,
                email=settings.admin_email,
                password_hash=password_hash,
                is_admin=True,
            )
            db.add(admin)
        else:
            admin.name = settings.admin_name
            admin.password_hash = password_hash
            admin.is_admin = True
        db.commit()
    finally:
        db.close()


def authenticate_admin(db: Session, email: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.email == email, User.is_admin.is_(True)).first()
    if not user or not verify_password(password, user.password_hash or ""):
        return None
    return user


def get_session_admin(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    admin_id = request.session.get("admin_id")
    if not admin_id:
        return None
    user = db.query(User).filter(User.id == admin_id, User.is_admin.is_(True)).first()
    if not user:
        request.session.clear()
        return None
    return user


def require_admin_web(
    request: Request,
    admin: Optional[User] = Depends(get_session_admin),
) -> User:
    if admin:
        return admin
    next_url = request.url.path
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail="Login required",
        headers={"Location": f"/login?next={quote(next_url, safe='/?&=')}"},
    )


def require_admin_api(
    admin: Optional[User] = Depends(get_session_admin),
) -> User:
    if admin:
        return admin
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin login required",
    )


def login_admin(request: Request, admin: User) -> None:
    request.session["admin_id"] = admin.id
    request.session["admin_email"] = admin.email
    request.session["admin_name"] = admin.name


def logout_admin(request: Request) -> None:
    request.session.clear()
