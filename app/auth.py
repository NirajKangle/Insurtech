import base64
import hashlib
import hmac
import time
from datetime import datetime, timedelta

import bcrypt
from fastapi import HTTPException, Request, Response
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User

SESSION_COOKIE = "insurtech_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session_token(user_id: str) -> str:
    settings = get_settings()
    expire = datetime.utcnow() + timedelta(seconds=SESSION_MAX_AGE)
    return jwt.encode(
        {"user_id": user_id, "exp": expire},
        settings.jwt_secret,
        algorithm="HS256",
    )


def set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(user_id),
        httponly=True,
        max_age=SESSION_MAX_AGE,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def get_user_id_from_request(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload.get("user_id")
    except JWTError:
        return None


def require_user(request: Request, db: Session) -> User:
    user_id = get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def generate_oauth_state(user_id: str) -> str:
    settings = get_settings()
    ts = str(int(time.time()))
    payload = f"{user_id}:{ts}"
    sig = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def verify_oauth_state(state: str) -> str | None:
    settings = get_settings()
    try:
        padded = state + "=" * (-len(state) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode()).decode()
        user_id, ts, sig = decoded.split(":")
        payload = f"{user_id}:{ts}"
        expected = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(time.time()) - int(ts) > 600:
            return None
        return user_id
    except (ValueError, TypeError):
        return None
