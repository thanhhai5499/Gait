"""
Camera sessions endpoints — lưu và truy xuất kết quả phân tích từ camera.

POST   /camera-sessions           — lưu kết quả phân tích
GET    /camera-sessions           — danh sách (phân trang)
GET    /camera-sessions/{id}      — chi tiết một session
DELETE /camera-sessions/{id}      — xóa (chủ sở hữu hoặc admin)
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.utils import now_vn
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.auth.utils import get_current_user

router = APIRouter(prefix="/camera-sessions", tags=["Camera Sessions"])


def _get_or_404(cs_id: int, db: Session) -> models.CameraSession:
    cs = db.query(models.CameraSession).filter(models.CameraSession.id == cs_id).first()
    if not cs:
        raise HTTPException(status_code=404, detail="Camera session không tồn tại")
    return cs


def _check_owner(cs: models.CameraSession, current_user: models.User) -> None:
    if current_user.role != models.UserRole.admin and cs.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Không có quyền truy cập")


# ── POST /camera-sessions ─────────────────────────────────────────────────────

@router.post("", response_model=schemas.CameraSessionOut, status_code=201)
def save_camera_session(
    payload: schemas.CameraSessionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    cs = models.CameraSession(
        user_id=current_user.id,
        recorded_at=payload.recorded_at,
        duration_s=payload.duration_s,
        frames=payload.frames,
        cameras_used=payload.cameras_used,
        analysis=payload.analysis,
        notes=payload.notes,
        created_at=now_vn(),
    )
    db.add(cs)
    db.commit()
    db.refresh(cs)
    return cs


# ── GET /camera-sessions ──────────────────────────────────────────────────────

@router.get("", response_model=schemas.PaginatedResponse)
def list_camera_sessions(
    page:      int = Query(1,   ge=1),
    page_size: int = Query(20,  ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = db.query(models.CameraSession)

    # Non-admin users see only their own records
    if current_user.role != models.UserRole.admin:
        q = q.filter(models.CameraSession.user_id == current_user.id)

    q = q.order_by(models.CameraSession.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    return {"total": total, "page": page, "page_size": page_size, "items": [
        schemas.CameraSessionOut.model_validate(cs) for cs in items
    ]}


# ── GET /camera-sessions/{id} ─────────────────────────────────────────────────

@router.get("/{cs_id}", response_model=schemas.CameraSessionOut)
def get_camera_session(
    cs_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    cs = _get_or_404(cs_id, db)
    _check_owner(cs, current_user)
    return cs


# ── DELETE /camera-sessions/{id} ─────────────────────────────────────────────

@router.delete("/{cs_id}", status_code=204)
def delete_camera_session(
    cs_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    cs = _get_or_404(cs_id, db)
    _check_owner(cs, current_user)
    db.delete(cs)
    db.commit()
