"""
Measurement / sensor readings endpoints
  GET  /sessions/{id}/readings           — paginated raw readings
  GET  /sessions/{id}/readings/latest    — latest N readings (for real-time polling)
  POST /sessions/{id}/readings           — manually push a reading (testing / simulation)
  DELETE /sessions/{id}/readings         — clear all readings for a session
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.auth.utils import get_current_user, require_user_or_admin

router = APIRouter(prefix="/sessions", tags=["Measurements"])


@router.get("/{session_id}/readings", response_model=schemas.PaginatedResponse)
def list_readings(
    session_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    s = db.query(models.MeasurementSession).filter(
        models.MeasurementSession.id == session_id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    q = (
        db.query(models.SensorReading)
        .filter(models.SensorReading.session_id == session_id)
        .order_by(models.SensorReading.timestamp_ms)
    )
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/{session_id}/readings/latest", response_model=list[schemas.SensorReadingOut])
def latest_readings(
    session_id: int,
    n: int = Query(50, ge=1, le=500, description="Number of latest readings"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Return the latest N readings sorted ascending by timestamp."""
    s = db.query(models.MeasurementSession).filter(
        models.MeasurementSession.id == session_id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    readings = (
        db.query(models.SensorReading)
        .filter(models.SensorReading.session_id == session_id)
        .order_by(models.SensorReading.timestamp_ms.desc())
        .limit(n)
        .all()
    )
    return list(reversed(readings))


@router.post("/{session_id}/readings", response_model=schemas.SensorReadingOut, status_code=201)
def push_reading(
    session_id: int,
    payload: schemas.SensorReadingIn,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_user_or_admin),
):
    """Manually push a reading — useful for testing or injecting simulated data."""
    s = db.query(models.MeasurementSession).filter(
        models.MeasurementSession.id == session_id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    reading = models.SensorReading(session_id=session_id, **payload.model_dump())
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading


@router.delete("/{session_id}/readings", status_code=204)
def clear_readings(
    session_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_user_or_admin),
):
    """Delete all readings for a session (irreversible)."""
    s = db.query(models.MeasurementSession).filter(
        models.MeasurementSession.id == session_id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if s.status == models.SessionStatus.recording:
        raise HTTPException(status_code=400, detail="Cannot clear readings while recording")

    db.query(models.SensorReading).filter(
        models.SensorReading.session_id == session_id
    ).delete()
    db.commit()
