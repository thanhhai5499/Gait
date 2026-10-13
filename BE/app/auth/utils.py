"""
Password hashing and JWT utilities.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app import models, schemas

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Access token (JWT, short-lived)
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> schemas.TokenData:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise JWTError("No sub claim")
        return schemas.TokenData(username=username)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Refresh token (opaque random string, stored server-side as hash)
# ---------------------------------------------------------------------------

def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_refresh_token(user_id: int, db: Session) -> str:
    raw = secrets.token_urlsafe(64)
    token_hash = _hash_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    # Xóa các refresh token cũ đã hết hạn của user này để tránh bảng phình
    db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == user_id,
        models.RefreshToken.expires_at < datetime.now(timezone.utc),
    ).delete()

    db_token = models.RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(db_token)
    db.commit()
    return raw


def verify_refresh_token(raw_token: str, db: Session) -> models.User:
    token_hash = _hash_token(raw_token)
    db_token = db.query(models.RefreshToken).filter(
        models.RefreshToken.token_hash == token_hash,
    ).first()

    if not db_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if db_token.revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked")
    if db_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has expired")

    user = db.query(models.User).filter(
        models.User.id == db_token.user_id,
        models.User.is_active.is_(True),
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Token rotation: revoke used token và cấp token mới (caller sẽ gọi create_refresh_token)
    db_token.revoked = True
    db.commit()
    return user


def revoke_refresh_token(raw_token: str, db: Session) -> None:
    token_hash = _hash_token(raw_token)
    db.query(models.RefreshToken).filter(
        models.RefreshToken.token_hash == token_hash,
    ).update({"revoked": True})
    db.commit()


def revoke_all_refresh_tokens(user_id: int, db: Session) -> None:
    db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == user_id,
        models.RefreshToken.revoked.is_(False),
    ).update({"revoked": True})
    db.commit()


# ---------------------------------------------------------------------------
# Current-user dependency
# ---------------------------------------------------------------------------

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    token_data = decode_token(token)
    user = db.query(models.User).filter(
        models.User.username == token_data.username
    ).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def require_role(*roles: models.UserRole):
    """Factory: dependency that restricts access to specific roles."""
    def _check(current_user: models.User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to roles: {[r.value for r in roles]}",
            )
        return current_user
    return _check


require_admin = require_role(models.UserRole.admin)
require_user_or_admin = require_role(models.UserRole.user, models.UserRole.admin)
