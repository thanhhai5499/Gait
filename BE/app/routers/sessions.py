"""
Measurement Session endpoints
"""
import asyncio
import csv
import io
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app import models, schemas
from app.auth.utils import get_current_user, require_user_or_admin
from app.utils import now_vn
from app.services.serial_reader import serial_registry, ws_manager, auto_detect_ch340
from app.services.simulator import sim_registry
from app.services.gait_analyzer import analyze_session
from app.services.reference_norms import evaluate_session as evaluate_reference

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _require_profile_complete(user: models.User) -> None:
    """Chặn kết nối đo nếu người dùng chưa cập nhật đủ thông tin cá nhân."""
    if any(v is None for v in (user.age, user.sex, user.weight_kg, user.height_cm)):
        raise HTTPException(
            status_code=422,
            detail="Vui lòng cập nhật đầy đủ thông tin cá nhân (tuổi, giới tính, cân nặng, chiều cao) trước khi đo.",
        )


def _check_owner(s: models.MeasurementSession, current_user: models.User):
    """403 nếu user thường cố truy cập session của người khác."""
    if current_user.role != models.UserRole.admin and s.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")


def _get_session_or_404(session_id: int, db: Session) -> models.MeasurementSession:
    s = db.query(models.MeasurementSession).filter(
        models.MeasurementSession.id == session_id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


def _session_out(s: models.MeasurementSession, db: Session) -> schemas.SessionOut:
    count = db.query(models.SensorReading).filter(
        models.SensorReading.session_id == s.id
    ).count()
    out = schemas.SessionOut.model_validate(s)
    out.reading_count = count
    return out


# ---------------------------------------------------------------------------
# List / detail
# ---------------------------------------------------------------------------

@router.get("/", response_model=schemas.PaginatedResponse)
def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: Optional[models.SessionStatus] = Query(None),
    user_id: Optional[int] = Query(None, description="Admin only: lọc theo user"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = db.query(
        models.MeasurementSession,
        func.count(models.SensorReading.id).label("reading_count"),
    ).outerjoin(
        models.SensorReading,
        models.SensorReading.session_id == models.MeasurementSession.id,
    ).group_by(models.MeasurementSession.id)

    if current_user.role != models.UserRole.admin:
        q = q.filter(models.MeasurementSession.user_id == current_user.id)
    elif user_id:
        q = q.filter(models.MeasurementSession.user_id == user_id)
    if status:
        q = q.filter(models.MeasurementSession.status == status)
    q = q.order_by(models.MeasurementSession.created_at.desc())

    # Count without the join/group overhead
    count_q = db.query(models.MeasurementSession)
    if current_user.role != models.UserRole.admin:
        count_q = count_q.filter(models.MeasurementSession.user_id == current_user.id)
    elif user_id:
        count_q = count_q.filter(models.MeasurementSession.user_id == user_id)
    if status:
        count_q = count_q.filter(models.MeasurementSession.status == status)
    total = count_q.count()

    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for session, reading_count in rows:
        out = schemas.SessionOut.model_validate(session)
        out.reading_count = reading_count
        items.append(out)

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/my-active", response_model=Optional[schemas.SessionOut])
def get_my_active_session(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    """Trả về session đang recording/paused của chính user. null nếu không có."""
    s = (
        db.query(models.MeasurementSession)
        .filter(
            models.MeasurementSession.user_id == current_user.id,
            models.MeasurementSession.status.in_([
                models.SessionStatus.recording,
                models.SessionStatus.paused,
            ]),
        )
        .order_by(models.MeasurementSession.created_at.desc())
        .first()
    )
    if not s:
        return None
    return _session_out(s, db)


@router.post("/prepare", response_model=schemas.SessionOut, status_code=201)
async def prepare_session(
    payload: schemas.PrepareRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    """Mở serial reader để xem trước tín hiệu. Session ở idle — gọi /start để ghi chính thức."""
    _require_profile_complete(current_user)

    # Auto-detect CH340 nếu com_port = "AUTO"
    com_port = payload.com_port
    if com_port.upper() == "AUTO":
        device = auto_detect_ch340()
        if not device:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy thiết bị. Vui lòng kết nối thiết bị và thử lại."
            )
        com_port = device["port"]

    session = models.MeasurementSession(
        session_code=secrets.token_hex(8).upper(),
        user_id=current_user.id,
        com_port=com_port,
        baud_rate=payload.baud_rate,
        notes=payload.notes,
        status=models.SessionStatus.idle,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    loop = asyncio.get_running_loop()
    try:
        serial_registry.start(
            session_id=session.id,
            com_port=session.com_port,
            baud_rate=session.baud_rate,
            db_factory=SessionLocal,
            loop=loop,
        )
    except RuntimeError as exc:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc))

    return _session_out(session, db)


@router.post("/prepare-sim", response_model=schemas.SessionOut, status_code=201)
async def prepare_session_sim(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    """Xem trước tín hiệu với dữ liệu giả lập."""
    _require_profile_complete(current_user)
    session = models.MeasurementSession(
        session_code=secrets.token_hex(8).upper(),
        user_id=current_user.id,
        com_port="SIMULATOR",
        baud_rate=0,
        notes="[Preview] Giả lập",
        status=models.SessionStatus.idle,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    loop = asyncio.get_running_loop()
    try:
        sim_registry.start(session_id=session.id, loop=loop)
    except RuntimeError as exc:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc))

    return _session_out(session, db)


@router.post("/quick-start", response_model=schemas.SessionOut, status_code=201)
async def quick_start_session(
    payload: schemas.QuickStartRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    # Auto-detect CH340 nếu com_port = "AUTO"
    com_port = payload.com_port
    if com_port.upper() == "AUTO":
        device = auto_detect_ch340()
        if not device:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy thiết bị. Vui lòng kết nối thiết bị và thử lại."
            )
        com_port = device["port"]

    session = models.MeasurementSession(
        session_code=secrets.token_hex(8).upper(),
        user_id=current_user.id,
        com_port=com_port,
        baud_rate=payload.baud_rate,
        notes=payload.notes,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    loop = asyncio.get_running_loop()
    try:
        serial_registry.start(
            session_id=session.id,
            com_port=session.com_port,
            baud_rate=session.baud_rate,
            db_factory=SessionLocal,
            loop=loop,
        )
    except RuntimeError as exc:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc))

    session.status = models.SessionStatus.recording
    session.start_time = now_vn()
    db.commit()
    db.refresh(session)
    return _session_out(session, db)


@router.post("/quick-start-sim", response_model=schemas.SessionOut, status_code=201)
async def quick_start_sim(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    session = models.MeasurementSession(
        session_code=secrets.token_hex(8).upper(),
        user_id=current_user.id,
        com_port="SIMULATOR",
        baud_rate=0,
        notes="[Giả lập] Dữ liệu sinh tự động",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    loop = asyncio.get_running_loop()
    try:
        sim_registry.start(session_id=session.id, loop=loop)
    except RuntimeError as exc:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc))

    session.status = models.SessionStatus.recording
    session.start_time = now_vn()
    db.commit()
    db.refresh(session)
    return _session_out(session, db)


@router.get("/{session_id}", response_model=schemas.SessionDetail)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    s = _get_session_or_404(session_id, db)
    # User thường chỉ được xem session của chính mình
    if current_user.role != models.UserRole.admin and s.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    count = db.query(models.SensorReading).filter(
        models.SensorReading.session_id == s.id
    ).count()
    out = schemas.SessionDetail.model_validate(s)
    out.reading_count = count
    return out


@router.put("/{session_id}", response_model=schemas.SessionOut)
def update_session(
    session_id: int,
    payload: schemas.SessionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    s = _get_session_or_404(session_id, db)
    _check_owner(s, current_user)
    if s.status == models.SessionStatus.recording:
        raise HTTPException(status_code=400, detail="Cannot update a recording session")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(s, field, value)
    db.commit()
    db.refresh(s)
    return _session_out(s, db)


@router.delete("/{session_id}", status_code=204)
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    s = _get_session_or_404(session_id, db)
    _check_owner(s, current_user)
    serial_registry.stop(session_id)
    sim_registry.stop(session_id)
    db.delete(s)
    db.commit()


# ---------------------------------------------------------------------------
# Recording control
# ---------------------------------------------------------------------------

@router.post("/{session_id}/start", response_model=schemas.SessionOut)
async def start_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    s = _get_session_or_404(session_id, db)
    _check_owner(s, current_user)
    if s.status == models.SessionStatus.recording:
        raise HTTPException(status_code=400, detail="Session is already recording")
    if not s.com_port:
        raise HTTPException(status_code=400, detail="No COM port configured")

    loop = asyncio.get_running_loop()
    already_running = serial_registry.is_running(session_id) or sim_registry.is_running(session_id)
    if not already_running:
        try:
            if s.com_port == "SIMULATOR":
                sim_registry.start(session_id=session_id, loop=loop, record=True)
            else:
                serial_registry.start(
                    session_id=session_id,
                    com_port=s.com_port,
                    baud_rate=s.baud_rate,
                    db_factory=SessionLocal,
                    loop=loop,
                    record=True,
                )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    else:
        # Reader đang chạy ở chế độ preview → bật ghi DB
        sim_registry.set_recording(session_id, True)
        serial_registry.set_recording(session_id, True)

    s.status = models.SessionStatus.recording
    s.start_time = now_vn()
    db.commit()
    db.refresh(s)
    return _session_out(s, db)


@router.post("/{session_id}/stop", response_model=schemas.SessionOut)
def stop_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    s = _get_session_or_404(session_id, db)
    _check_owner(s, current_user)
    serial_registry.stop(session_id)
    sim_registry.stop(session_id)
    s.status = models.SessionStatus.completed
    s.end_time = now_vn()
    db.commit()
    db.refresh(s)
    return _session_out(s, db)


@router.post("/{session_id}/pause", response_model=schemas.SessionOut)
def pause_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    s = _get_session_or_404(session_id, db)
    _check_owner(s, current_user)
    if s.status != models.SessionStatus.recording:
        raise HTTPException(status_code=400, detail="Session is not recording")
    # Tạm dừng ghi DB nhưng vẫn giữ kết nối (tắt record flag)
    sim_registry.set_recording(session_id, False)
    serial_registry.set_recording(session_id, False)
    serial_registry.stop(session_id)
    sim_registry.stop(session_id)
    s.status = models.SessionStatus.paused
    db.commit()
    db.refresh(s)
    return _session_out(s, db)


@router.post("/{session_id}/resume", response_model=schemas.SessionOut)
async def resume_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    s = _get_session_or_404(session_id, db)
    _check_owner(s, current_user)
    if s.status != models.SessionStatus.paused:
        raise HTTPException(status_code=400, detail="Session is not paused")

    loop = asyncio.get_running_loop()
    if s.com_port == "SIMULATOR":
        sim_registry.start(session_id=session_id, loop=loop)
    else:
        serial_registry.start(
            session_id=session_id,
            com_port=s.com_port,
            baud_rate=s.baud_rate,
            db_factory=SessionLocal,
            loop=loop,
        )
    s.status = models.SessionStatus.recording
    db.commit()
    db.refresh(s)
    return _session_out(s, db)


@router.get("/{session_id}/status", response_model=schemas.SerialStatusResponse)
def get_session_status(
    session_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    _get_session_or_404(session_id, db)
    info = serial_registry.get_status(session_id)
    return schemas.SerialStatusResponse(session_id=session_id, **info)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@router.post("/{session_id}/analyze", response_model=schemas.GaitAnalysisOut)
def trigger_analysis(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_user_or_admin),
):
    s = _get_session_or_404(session_id, db)
    _check_owner(s, current_user)
    if s.status == models.SessionStatus.recording:
        raise HTTPException(status_code=400, detail="Stop recording before analyzing")

    readings = (
        db.query(models.SensorReading)
        .filter(models.SensorReading.session_id == session_id)
        .order_by(models.SensorReading.timestamp_ms)
        .all()
    )
    if not readings:
        raise HTTPException(status_code=422, detail="No readings found for this session")

    if s.analysis:
        db.delete(s.analysis)
        db.flush()

    analysis = analyze_session(session_id, readings)

    # Z-score so với 3 dataset chuẩn — dùng profile của session owner
    # (admin analyze hộ user khác vẫn lấy đúng age/sex)
    profile_user = s.user if s.user else current_user
    if profile_user.age and profile_user.sex:
        try:
            sex_mapped = "men" if profile_user.sex.value == "male" else "women"
            ref = evaluate_reference(
                analysis=analysis,
                walk_distance_m=s.walk_distance_m,
                age=profile_user.age,
                sex=sex_mapped,
            )

            # ── Symmetry Index với ngưỡng lâm sàng (Section 5.2: AI > 10%)
            def _si_band(si):
                if si is None:
                    return "unavailable"
                if si < 10:
                    return "normal"
                if si < 25:
                    return "borderline"
                return "abnormal"

            def _si_remark(si, joint_name):
                if si is None:
                    return None
                if si >= 25:
                    return f"Mất đối xứng {joint_name} nghiêm trọng (AI={si:.1f}%) — cần đánh giá chuyên khoa."
                if si >= 10:
                    return f"Mất đối xứng {joint_name} nhẹ (AI={si:.1f}%) — theo dõi và tăng bài tập đối xứng."
                return f"Đối xứng {joint_name} tốt (AI={si:.1f}%)."

            si_hip  = analysis.symmetry_index_hip
            si_knee = analysis.symmetry_index_knee
            symmetry_evals = [
                {
                    "parameter": "hip_symmetry_index",
                    "label":     "Đối xứng hông (SI)",
                    "measured":  round(si_hip, 2)  if si_hip  is not None else None,
                    "unit":      "%",
                    "threshold": "Bình thường < 10% · Cận ngưỡng 10–25% · Bất thường > 25%",
                    "band":      _si_band(si_hip),
                    "note":      _si_remark(si_hip,  "hông"),
                },
                {
                    "parameter": "knee_symmetry_index",
                    "label":     "Đối xứng gối (SI)",
                    "measured":  round(si_knee, 2) if si_knee is not None else None,
                    "unit":      "%",
                    "threshold": "Bình thường < 10% · Cận ngưỡng 10–25% · Bất thường > 25%",
                    "band":      _si_band(si_knee),
                    "note":      _si_remark(si_knee, "gối"),
                },
            ]

            # ── Nhận xét lâm sàng tự động theo tham số bất thường
            all_evals = ref["kinematic"] + ref["spatiotemporal"]
            abnormal_params = [e for e in all_evals if e.band == "abnormal"]
            borderline_params = [e for e in all_evals if e.band == "borderline"]

            def _clinical_note(ev):
                p = ev.parameter
                z = ev.z
                if p == "cadence" and z is not None and z < -2:
                    return "Nhịp bước thấp bất thường — có thể do sợ ngã, yếu cơ hoặc đau khớp."
                if p == "gait_speed" and z is not None and z < -2:
                    return "Tốc độ đi dưới 1,0 m/s — nguy cơ ngã cao ở người cao tuổi (theo Yishun Study)."
                if p == "stance_pct" and z is not None and z > 2:
                    return "Tỉ lệ chống chân cao — bù trừ để tăng ổn định, thường gặp sau đột quỵ."
                if p == "knee_peak_flexion_deg" and z is not None and z < -2:
                    return "Gối không đạt góc gập tối đa khi swing — nguy cơ vấp ngã hoặc cứng khớp."
                if p == "hip_peak_ext_deg" and z is not None and z > 2:
                    return "Duỗi hông quá mức — kiểm tra ổn định dây chằng khớp háng."
                if p == "step_length" and z is not None and z < -2:
                    return "Độ dài bước ngắn — giảm khả năng duỗi hông và lực đẩy cuối pha chống."
                return None

            clinical_notes = []
            for ev in abnormal_params:
                note = _clinical_note(ev)
                if note:
                    clinical_notes.append({"parameter": ev.parameter, "note": note, "severity": "abnormal"})
            for ev in borderline_params:
                note = _clinical_note(ev)
                if note:
                    clinical_notes.append({"parameter": ev.parameter, "note": note, "severity": "borderline"})
            # Thêm ghi chú symmetry bất thường
            for si_ev in symmetry_evals:
                if si_ev["band"] in ("abnormal", "borderline") and si_ev["note"]:
                    clinical_notes.append({
                        "parameter": si_ev["parameter"],
                        "note":      si_ev["note"],
                        "severity":  si_ev["band"],
                    })

            # ── Đếm summary (bao gồm cả symmetry)
            summary = {"normal": 0, "borderline": 0, "abnormal": 0, "unavailable": 0}
            for ev in all_evals:
                summary[ev.band] = summary.get(ev.band, 0) + 1
            for si_ev in symmetry_evals:
                b = si_ev["band"]
                summary[b] = summary.get(b, 0) + 1

            analysis.reference_evaluations = {
                "kinematic":      [e.to_dict() for e in ref["kinematic"]],
                "spatiotemporal": [e.to_dict() for e in ref["spatiotemporal"]],
                "symmetry":       symmetry_evals,
                "clinical_notes": clinical_notes,
                "summary":        summary,
                "patient":        {"age": profile_user.age, "sex": sex_mapped},
            }
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Reference evaluation failed — skipping")

    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@router.get("/{session_id}/export/csv")
def export_csv(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    s = _get_session_or_404(session_id, db)
    _check_owner(s, current_user)
    readings = (
        db.query(models.SensorReading)
        .filter(models.SensorReading.session_id == session_id)
        .order_by(models.SensorReading.timestamp_ms)
        .all()
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "timestamp_ms", "recorded_at",
        "left_hip", "left_knee", "right_hip", "right_knee",
        "left_force_1", "left_force_2", "right_force_1", "right_force_2",
        "accel_x", "accel_y", "accel_z",
        "gyro_x", "gyro_y", "gyro_z",
        "magn_x", "magn_y", "magn_z",
        "phase_left", "phase_right", "signal_quality",
    ])
    for r in readings:
        writer.writerow([
            r.timestamp_ms, r.recorded_at,
            r.left_hip, r.left_knee, r.right_hip, r.right_knee,
            r.left_force_1, r.left_force_2, r.right_force_1, r.right_force_2,
            r.accel_x, r.accel_y, r.accel_z,
            r.gyro_x, r.gyro_y, r.gyro_z,
            r.magn_x, r.magn_y, r.magn_z,
            r.phase_left.value if r.phase_left else "",
            r.phase_right.value if r.phase_right else "",
            r.signal_quality,
        ])

    buf.seek(0)
    filename = f"session_{s.session_code}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
