"""
Authentication endpoints:
  POST /auth/login     — get access + refresh token
  POST /auth/refresh   — get new access token via refresh token
  POST /auth/logout    — revoke refresh token
  POST /auth/signup    — public self-registration
  POST /auth/register  — admin-only user creation
  GET  /auth/me        — current user info
  PUT  /auth/me/profile — update profile
  PUT  /auth/me/password — change password
  GET  /auth/users     — list users (admin)
  PUT  /auth/users/{id} — update user (admin)
  DELETE /auth/users/{id} — delete user (admin)
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app import models, schemas
from app.auth.utils import (
    hash_password, verify_password,
    create_access_token,
    create_refresh_token, verify_refresh_token, revoke_refresh_token, revoke_all_refresh_tokens,
    get_current_user, require_admin,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
limiter = Limiter(key_func=get_remote_address)


def _apply_safe_update(obj, payload, allowed_fields: set):
    """Apply only whitelisted fields from payload to ORM model."""
    for field, value in payload.model_dump(exclude_none=True).items():
        if field not in allowed_fields:
            raise HTTPException(status_code=400, detail=f"Field '{field}' cannot be updated")
        setattr(obj, field, value)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=schemas.TokenResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(
        models.User.username == form_data.username
    ).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không đúng",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Account is disabled")

    expire_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token({"sub": user.username}, expires_delta=expire_delta)
    refresh_token = create_refresh_token(user.id, db)

    return schemas.TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=schemas.UserOut.model_validate(user),
    )


# ---------------------------------------------------------------------------
# Refresh — đổi refresh token lấy access token mới (token rotation)
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=schemas.TokenResponse)
@limiter.limit("10/minute")
def refresh(
    request: Request,
    payload: schemas.RefreshRequest,
    db: Session = Depends(get_db),
):
    user = verify_refresh_token(payload.refresh_token, db)

    expire_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    new_access_token = create_access_token({"sub": user.username}, expires_delta=expire_delta)
    new_refresh_token = create_refresh_token(user.id, db)

    return schemas.TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=schemas.UserOut.model_validate(user),
    )


# ---------------------------------------------------------------------------
# Logout — revoke refresh token ngay lập tức
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=204)
def logout(
    payload: schemas.RefreshRequest,
    db: Session = Depends(get_db),
):
    revoke_refresh_token(payload.refresh_token, db)


# ---------------------------------------------------------------------------
# Signup — public registration for regular users
# ---------------------------------------------------------------------------

@router.post("/signup", response_model=schemas.UserOut, status_code=201)
@limiter.limit("5/minute")
def signup(
    request: Request,
    payload: schemas.UserSignup,
    db: Session = Depends(get_db),
):
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = models.User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=models.UserRole.user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Register — chỉ admin mới tạo được user mới
# ---------------------------------------------------------------------------

@router.post("/register", response_model=schemas.UserOut, status_code=201)
def register(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = models.User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.put("/me/profile", response_model=schemas.UserOut)
def update_my_profile(
    payload: schemas.ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _apply_safe_update(current_user, payload, {"full_name", "age", "sex", "weight_kg", "height_cm"})
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/me/password", status_code=204)
def change_password(
    payload: schemas.ChangePassword,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    current_user.hashed_password = hash_password(payload.new_password)
    # Revoke tất cả refresh token khi đổi mật khẩu
    revoke_all_refresh_tokens(current_user.id, db)
    db.commit()


# ---------------------------------------------------------------------------
# Admin: user management
# ---------------------------------------------------------------------------

@router.get("/users", response_model=schemas.PaginatedResponse)
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    total = db.query(models.User).count()
    users = db.query(models.User).offset((page - 1) * page_size).limit(page_size).all()
    return schemas.PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[schemas.UserOut.model_validate(u) for u in users],
    )


@router.put("/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _apply_safe_update(user, payload, {"full_name", "email", "is_active", "role"})
    # Nếu bị deactivate → revoke tất cả token
    if payload.is_active is False:
        revoke_all_refresh_tokens(user_id, db)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
