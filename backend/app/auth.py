import hashlib
import hmac
import secrets
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from .config import settings, configured
from .db import get_db, now, utc
from .models import User, LoginSession

hasher = PasswordHasher()


def token_hash(token):
    secret = settings().app_secret_key
    if not configured(secret) or len(secret) < 32:
        raise HTTPException(503, "APP_SECRET_KEY를 32자 이상으로 설정하세요")
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def user_required(request: Request, db=Depends(get_db)):
    token = request.cookies.get("session")
    session = db.get(LoginSession, token_hash(token)) if token else None
    if not session or utc(session.expires_at) <= now():
        raise HTTPException(401, "로그인이 필요합니다")
    return db.get(User, session.user_id)


def admin_required(user=Depends(user_required)):
    if not user.is_admin:
        raise HTTPException(403, "관리자 권한이 필요합니다")
    return user


def login(db, email, password):
    user = db.scalar(select(User).where(User.email == email.lower()))
    try:
        hasher.verify(user.password_hash if user else DUMMY_HASH, password)
    except VerificationError:
        raise HTTPException(401, "이메일 또는 비밀번호가 일치하지 않습니다") from None
    if not user:
        raise HTTPException(401, "이메일 또는 비밀번호가 일치하지 않습니다")
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(token_hash=token_hash(token), user_id=user.id, expires_at=now() + timedelta(hours=settings().session_hours)))
    db.commit()
    return user, token


DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
