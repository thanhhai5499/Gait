"""
Serial port utility endpoints
  GET  /serial/ports           — list available COM ports
  GET  /serial/status/{id}     — status of reader for a session
  POST /serial/simulate/{id}   — inject simulated data (dev/testing only)
"""
import math
import random
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.auth.utils import get_current_user, require_user_or_admin
from app.services.serial_reader import list_serial_ports, serial_registry, auto_detect_ch340

router = APIRouter(prefix="/serial", tags=["Serial / COM port"])


@router.get("/ports", response_model=list[schemas.SerialPortInfo])
def get_serial_ports(_: models.User = Depends(get_current_user)):
    """List all available serial/COM ports detected by the OS."""
    return list_serial_ports()


@router.get("/auto-detect", response_model=schemas.CH340DetectResponse)
def detect_ch340(_: models.User = Depends(get_current_user)):
    """
    Tự động phát hiện thiết bị CH340 (USB-SERIAL CH340).
    Trả về thông tin port nếu tìm thấy, hoặc 404 nếu không có.
    """
    device = auto_detect_ch340()
    if not device:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy thiết bị. Vui lòng kết nối thiết bị và thử lại."
        )
    return device


@router.get("/status/{session_id}", response_model=schemas.SerialStatusResponse)
def serial_status(
    session_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    s = db.query(models.MeasurementSession).filter(
        models.MeasurementSession.id == session_id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    info = serial_registry.get_status(session_id)
    return schemas.SerialStatusResponse(session_id=session_id, **info)


@router.post("/simulate/{session_id}")
def simulate_data(
    session_id: int,
    n_samples: int = Query(100, ge=1, le=5000, description="Number of samples to inject"),
    freq_hz: float = Query(50.0, ge=1.0, le=200.0, description="Simulated sample rate"),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_user_or_admin),
):
    """
    Inject simulated gait data into a session for development/demo purposes.
    Generates sinusoidal joint angles mimicking a normal walking pattern.
    """
    s = db.query(models.MeasurementSession).filter(
        models.MeasurementSession.id == session_id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if s.status == models.SessionStatus.recording:
        raise HTTPException(status_code=400, detail="Cannot inject while session is recording")

    dt_ms = 1000.0 / freq_hz
    # Find max existing timestamp
    last = (
        db.query(models.SensorReading)
        .filter(models.SensorReading.session_id == session_id)
        .order_by(models.SensorReading.timestamp_ms.desc())
        .first()
    )
    base_ts = (last.timestamp_ms + dt_ms) if last else 0.0

    # Gait cycle ≈ 1.1 s at comfortable walking speed
    gait_period_s = 1.1
    gait_period_ms = gait_period_s * 1000.0

    readings = []
    for i in range(n_samples):
        t_ms = base_ts + i * dt_ms
        t_s = t_ms / 1000.0
        phi = (t_s % gait_period_s) / gait_period_s  # 0..1 within cycle

        # Simplified sinusoidal models (degrees)
        lh  = 20 + 20 * math.sin(2 * math.pi * phi) + random.gauss(0, 1)
        lk  = 30 + 30 * math.sin(2 * math.pi * phi - 0.5) + random.gauss(0, 1)
        # Right leg leads left by half a cycle
        phi_r = (phi + 0.5) % 1.0
        rh  = 20 + 20 * math.sin(2 * math.pi * phi_r) + random.gauss(0, 1)
        rk  = 30 + 30 * math.sin(2 * math.pi * phi_r - 0.5) + random.gauss(0, 1)

        # FSR 2 cảm biến/chân (ADC 0-1023)
        f_scale = 600 + 300 * math.sin(2 * math.pi * phi)
        fL1 = max(0.0, f_scale + random.gauss(0, 10)) if phi < 0.6 else random.gauss(30, 5)
        fL2 = max(0.0, f_scale * 0.95 + random.gauss(0, 10)) if phi < 0.6 else random.gauss(28, 5)
        f_scale_r = 600 + 300 * math.sin(2 * math.pi * phi_r)
        fR1 = max(0.0, f_scale_r + random.gauss(0, 10)) if phi_r < 0.6 else random.gauss(30, 5)
        fR2 = max(0.0, f_scale_r * 0.95 + random.gauss(0, 10)) if phi_r < 0.6 else random.gauss(28, 5)

        # IMU accelerometer (m/s²)
        ax = 0.5 * math.sin(2 * math.pi * phi) + random.gauss(0, 0.1)
        ay = 0.3 * math.cos(2 * math.pi * phi) + random.gauss(0, 0.1)
        az = 9.81 + 0.8 * math.sin(4 * math.pi * phi) + random.gauss(0, 0.15)

        # IMU gyroscope (deg/s)
        gx = 5 * math.cos(2 * math.pi * phi) + random.gauss(0, 1)
        gy = 3 * math.sin(2 * math.pi * phi) + random.gauss(0, 1)
        gz = 2 * math.sin(4 * math.pi * phi) + random.gauss(0, 1)

        # IMU magnetometer (μT — giả lập hướng Bắc + nhiễu nhỏ)
        mx = 230 + random.gauss(0, 5)
        my = 120 + random.gauss(0, 5)
        mz = 45 + random.gauss(0, 3)

        # Gait phase: stance when phi < 60% of cycle
        phase_l = models.GaitPhase.stance if phi < 0.6 else models.GaitPhase.swing
        phase_r = models.GaitPhase.stance if phi_r < 0.6 else models.GaitPhase.swing

        readings.append(models.SensorReading(
            session_id=session_id,
            timestamp_ms=t_ms,
            left_hip=round(lh, 2),
            left_knee=round(lk, 2),
            right_hip=round(rh, 2),
            right_knee=round(rk, 2),
            left_force_1=round(fL1, 1),
            left_force_2=round(fL2, 1),
            right_force_1=round(fR1, 1),
            right_force_2=round(fR2, 1),
            accel_x=round(ax, 3),
            accel_y=round(ay, 3),
            accel_z=round(az, 3),
            gyro_x=round(gx, 3),
            gyro_y=round(gy, 3),
            gyro_z=round(gz, 3),
            magn_x=round(mx, 2),
            magn_y=round(my, 2),
            magn_z=round(mz, 2),
            phase_left=phase_l,
            phase_right=phase_r,
            signal_quality=99,
        ))

    db.bulk_save_objects(readings)
    db.commit()
    return {"injected": n_samples, "session_id": session_id}
