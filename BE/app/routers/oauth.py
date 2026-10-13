"""
Google OAuth2 endpoints
  GET  /auth/google           — redirect đến trang đăng nhập Google
  GET  /auth/google/callback  — Google callback, trả về JWT token
"""
import re
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app import models, schemas
from app.auth.utils import create_access_token

router = APIRouter(prefix="/auth", tags=["Google OAuth2"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
SCOPES = "openid email profile"


# ---------------------------------------------------------------------------
# Bước 1 — Redirect đến Google
# ---------------------------------------------------------------------------

@router.get("/google")
def google_login():
    """Redirect người dùng đến trang đăng nhập Google."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth chưa được cấu hình")

    params = (
        f"?client_id={settings.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={settings.GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPES.replace(' ', '%20')}"
        f"&access_type=offline"
        f"&prompt=select_account"
    )
    return RedirectResponse(url=GOOGLE_AUTH_URL + params)


# ---------------------------------------------------------------------------
# Bước 2 — Google callback
# ---------------------------------------------------------------------------

@router.get("/google/callback", response_model=schemas.TokenResponse)
async def google_callback(
    code: str,
    db: Session = Depends(get_db),
):
    """
    Google redirect về đây kèm authorization code.
    Đổi code → access_token → lấy thông tin user → tạo/login user → trả JWT.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth chưa được cấu hình")

    # 1. Đổi code lấy token từ Google
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })

    if token_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Không thể lấy token từ Google")

    google_token = token_resp.json().get("access_token")

    # 2. Lấy thông tin user từ Google
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_token}"},
        )

    if user_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Không thể lấy thông tin user từ Google")

    google_data = user_resp.json()
    google_id = google_data.get("sub")
    email = google_data.get("email")
    full_name = google_data.get("name", email)
    avatar_url = google_data.get("picture")

    if not email:
        raise HTTPException(status_code=400, detail="Không lấy được email từ Google")

    # 3. Tìm hoặc tạo user
    user = db.query(models.User).filter(models.User.google_id == google_id).first()

    if not user:
        # Kiểm tra email đã tồn tại chưa (user có thể đã đăng ký local)
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            # Liên kết tài khoản local với Google
            user.google_id = google_id
            user.auth_provider = models.AuthProvider.google
            user.avatar_url = avatar_url
        else:
            # Tạo user mới từ Google
            username = _generate_username(email, db)
            user = models.User(
                username=username,
                email=email,
                full_name=full_name,
                hashed_password=None,
                role=models.UserRole.user,
                auth_provider=models.AuthProvider.google,
                google_id=google_id,
                avatar_url=avatar_url,
            )
            db.add(user)

    db.commit()
    db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Tài khoản đã bị vô hiệu hóa")

    # 4. Tạo JWT và trả về
    token = create_access_token(
        {"sub": user.username},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return schemas.TokenResponse(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=schemas.UserOut.model_validate(user),
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _generate_username(email: str, db: Session) -> str:
    """Tạo username từ email, đảm bảo không trùng."""
    base = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())
    if not base:
        base = "user"
    username = base
    counter = 1
    while db.query(models.User).filter(models.User.username == username).first():
        username = f"{base}{counter}"
        counter += 1
    return username
