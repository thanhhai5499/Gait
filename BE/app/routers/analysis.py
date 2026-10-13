"""
Analysis & chart data endpoints
  GET  /sessions/{id}/analysis                 — full analysis result
  GET  /sessions/{id}/chart/timeseries         — time-series data for all joints
  GET  /sessions/{id}/chart/timeseries/{joint} — single joint time-series
  GET  /sessions/{id}/chart/rom                — ROM bar chart data
  GET  /sessions/{id}/chart/symmetry           — symmetry index chart
  GET  /sessions/{id}/chart/gait-cycle         — gait cycle summary
  GET  /sessions/{id}/chart/phase-distribution — stance/swing % per leg
  GET  /analysis/compare                       — compare two sessions
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.auth.utils import get_current_user
from app.services import reference_norms

router = APIRouter(tags=["Analysis & Charts"])

VALID_JOINTS = {"left_hip", "left_knee", "right_hip", "right_knee"}


def _get_analysis_or_404(session_id: int, db: Session) -> models.GaitAnalysis:
    analysis = (
        db.query(models.GaitAnalysis)
        .filter(models.GaitAnalysis.session_id == session_id)
        .first()
    )
    if not analysis:
        raise HTTPException(
            status_code=404,
            detail="No analysis found. Run POST /sessions/{id}/analyze first.",
        )
    return analysis


# ---------------------------------------------------------------------------
# Full analysis
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/analysis", response_model=schemas.GaitAnalysisOut)
def get_analysis(
    session_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return _get_analysis_or_404(session_id, db)


# ---------------------------------------------------------------------------
# Time-series charts
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/chart/timeseries", response_model=schemas.TimeSeriesChart)
def chart_timeseries_all(
    session_id: int,
    downsample: int = Query(1, ge=1, le=100, description="Take every Nth sample"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Return time-series for all 6 joint angles."""
    readings = (
        db.query(models.SensorReading)
        .filter(models.SensorReading.session_id == session_id)
        .order_by(models.SensorReading.timestamp_ms)
        .all()
    )
    if not readings:
        raise HTTPException(status_code=404, detail="No readings for this session")

    readings = readings[::downsample]
    ts = [r.timestamp_ms for r in readings]

    series = [
        schemas.ChartSeries(name="Left Hip",    data=[r.left_hip   or 0 for r in readings]),
        schemas.ChartSeries(name="Left Knee",   data=[r.left_knee  or 0 for r in readings]),
        schemas.ChartSeries(name="Right Hip",   data=[r.right_hip  or 0 for r in readings]),
        schemas.ChartSeries(name="Right Knee",  data=[r.right_knee or 0 for r in readings]),
    ]
    return schemas.TimeSeriesChart(session_id=session_id, timestamps_ms=ts, series=series)


@router.get("/sessions/{session_id}/chart/timeseries/{joint}", response_model=schemas.TimeSeriesChart)
def chart_timeseries_joint(
    session_id: int,
    joint: str,
    downsample: int = Query(1, ge=1, le=100),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Return time-series for a single joint, e.g. left_knee."""
    if joint not in VALID_JOINTS:
        raise HTTPException(status_code=400, detail=f"Invalid joint. Choose from: {sorted(VALID_JOINTS)}")

    readings = (
        db.query(models.SensorReading)
        .filter(models.SensorReading.session_id == session_id)
        .order_by(models.SensorReading.timestamp_ms)
        .all()
    )[::downsample]

    if not readings:
        raise HTTPException(status_code=404, detail="No readings for this session")

    ts = [r.timestamp_ms for r in readings]
    values = [getattr(r, joint) or 0.0 for r in readings]
    label = joint.replace("_", " ").title()

    return schemas.TimeSeriesChart(
        session_id=session_id,
        timestamps_ms=ts,
        series=[schemas.ChartSeries(name=label, data=values)],
    )


# ---------------------------------------------------------------------------
# ROM bar chart
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/chart/rom", response_model=schemas.SummaryChart)
def chart_rom(
    session_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    analysis = _get_analysis_or_404(session_id, db)

    def rom_item(label, stats):
        if stats is None:
            return schemas.BarChartItem(label=label, value=0.0, unit="deg")
        return schemas.BarChartItem(label=label, value=round(stats["rom"], 1), unit="deg")

    items = [
        rom_item("Left Hip",   analysis.left_hip_stats),
        rom_item("Left Knee",  analysis.left_knee_stats),
        rom_item("Right Hip",  analysis.right_hip_stats),
        rom_item("Right Knee", analysis.right_knee_stats),
    ]
    return schemas.SummaryChart(session_id=session_id, items=items)


# ---------------------------------------------------------------------------
# Symmetry chart
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/chart/symmetry")
def chart_symmetry(
    session_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    analysis = _get_analysis_or_404(session_id, db)
    return {
        "session_id": session_id,
        "items": [
            {"joint": "Hip",  "symmetry_index": analysis.symmetry_index_hip,  "unit": "%"},
            {"joint": "Knee", "symmetry_index": analysis.symmetry_index_knee, "unit": "%"},
        ],
        "note": "0 = perfect symmetry, higher = more asymmetry",
    }


# ---------------------------------------------------------------------------
# Gait cycle summary
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/chart/gait-cycle")
def chart_gait_cycle(
    session_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    analysis = _get_analysis_or_404(session_id, db)
    return {
        "session_id": session_id,
        "left": analysis.left_gait_cycle,
        "right": analysis.right_gait_cycle,
        "gait_score": analysis.gait_score,
    }


# ---------------------------------------------------------------------------
# Phase distribution (stance vs swing %)
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/chart/phase-distribution")
def chart_phase_distribution(
    session_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    readings = (
        db.query(models.SensorReading)
        .filter(models.SensorReading.session_id == session_id)
        .all()
    )
    if not readings:
        raise HTTPException(status_code=404, detail="No readings for this session")

    def phase_counts(phase_attr):
        stance = sum(1 for r in readings if getattr(r, phase_attr) == models.GaitPhase.stance)
        swing = sum(1 for r in readings if getattr(r, phase_attr) == models.GaitPhase.swing)
        total = len(readings)
        return {
            "stance_pct": round(stance / total * 100, 1) if total else 0,
            "swing_pct": round(swing / total * 100, 1) if total else 0,
            "unknown_pct": round((total - stance - swing) / total * 100, 1) if total else 0,
        }

    return {
        "session_id": session_id,
        "left": phase_counts("phase_left"),
        "right": phase_counts("phase_right"),
        "total_samples": len(readings),
    }


# ---------------------------------------------------------------------------
# Pelvic sway (spine accelerometer) — đo độ lệch hông lên xuống
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/chart/pelvis-sway")
def chart_pelvis_sway(
    session_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Trả về thống kê pelvic sway (3 trục) cho session đã phân tích.

    Trục z (vertical) là chỉ số chính: RMS cao = đi không ổn định / hông
    lắc lên xuống nhiều. Trục x (mediolateral) phản ánh độ lắc trái-phải.
    """
    analysis = _get_analysis_or_404(session_id, db)
    sway = analysis.pelvis_sway_stats
    if not sway:
        raise HTTPException(
            status_code=404,
            detail="No pelvic accelerometer data for this session.",
        )

    return {
        "session_id": session_id,
        "primary_axis": sway.get("primary_axis"),
        "axes": {
            "x_mediolateral":    sway.get("x_mediolateral"),
            "y_anteroposterior": sway.get("y_anteroposterior"),
            "z_vertical":        sway.get("z_vertical"),
        },
        "note": sway.get("note"),
    }


@router.get("/sessions/{session_id}/chart/pelvis-sway/timeseries", response_model=schemas.TimeSeriesChart)
def chart_pelvis_sway_timeseries(
    session_id: int,
    downsample: int = Query(1, ge=1, le=100),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Trả về time-series 3 trục accel cột sống để vẽ biểu đồ pelvic sway."""
    readings = (
        db.query(models.SensorReading)
        .filter(models.SensorReading.session_id == session_id)
        .order_by(models.SensorReading.timestamp_ms)
        .all()
    )
    if not readings:
        raise HTTPException(status_code=404, detail="No readings for this session")

    readings = readings[::downsample]
    ts = [r.timestamp_ms for r in readings]

    series = [
        schemas.ChartSeries(name="Accel X",    data=[r.accel_x or 0 for r in readings]),
        schemas.ChartSeries(name="Accel Y",    data=[r.accel_y or 0 for r in readings]),
        schemas.ChartSeries(name="Accel Z",    data=[r.accel_z or 0 for r in readings]),
    ]
    return schemas.TimeSeriesChart(session_id=session_id, timestamps_ms=ts, series=series)


# ---------------------------------------------------------------------------
# Reference-norms comparison (vs NTU / Yishun / Chinese datasets)
# ---------------------------------------------------------------------------

@router.get(
    "/sessions/{session_id}/reference-comparison",
    response_model=schemas.ReferenceComparison,
)
def reference_comparison(
    session_id: int,
    age: int = Query(..., ge=10, le=110, description="Patient age in years"),
    sex: str = Query(..., pattern="^(men|women)$",
                     description="Patient sex: 'men' or 'women'"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Compare the session's analyzed metrics against three normative datasets.

    Dataset routing:
      - Joint-angle kinematics (peak flexion, ROM, …) → NTU 2026 (50-80 yr)
      - Spatiotemporal (cadence, stance%, gait speed) for age 21-90 → Yishun 2020
      - Spatiotemporal for age 18-20                  → Chinese Students 2023

    Bands are |Z|<1 normal · 1≤|Z|<2 borderline · |Z|≥2 abnormal.

    `gait_speed` requires `walk_distance_m` to be set on the session
    (POST /sessions or PUT /sessions/{id}); otherwise it is reported as
    `unavailable`.
    """
    analysis = _get_analysis_or_404(session_id, db)
    session  = (
        db.query(models.MeasurementSession)
        .filter(models.MeasurementSession.id == session_id)
        .first()
    )

    result = reference_norms.evaluate_session(
        analysis=analysis,
        walk_distance_m=session.walk_distance_m if session else None,
        age=age,
        sex=sex,
    )

    # Tally bands across both categories for the UI summary card.
    summary = {"normal": 0, "borderline": 0, "abnormal": 0, "unavailable": 0}
    for ev in (*result["kinematic"], *result["spatiotemporal"]):
        summary[ev.band] = summary.get(ev.band, 0) + 1

    return schemas.ReferenceComparison(
        session_id=session_id,
        age=age,
        sex=sex,
        walk_distance_m=session.walk_distance_m if session else None,
        kinematic=[schemas.ReferenceEvaluation(**ev.to_dict())
                   for ev in result["kinematic"]],
        spatiotemporal=[schemas.ReferenceEvaluation(**ev.to_dict())
                        for ev in result["spatiotemporal"]],
        summary=summary,
    )


@router.get("/reference-datasets")
def list_reference_datasets(_: models.User = Depends(get_current_user)):
    """Return metadata for the three bundled normative datasets."""
    return reference_norms.dataset_summary()


# ---------------------------------------------------------------------------
# Compare two sessions
# ---------------------------------------------------------------------------

@router.get("/analysis/compare")
def compare_sessions(
    session_a: int = Query(..., description="First session ID"),
    session_b: int = Query(..., description="Second session ID"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Compare ROM and symmetry metrics between two sessions."""
    a = _get_analysis_or_404(session_a, db)
    b = _get_analysis_or_404(session_b, db)

    def delta(val_a, val_b):
        if val_a is None or val_b is None:
            return None
        return round(val_b - val_a, 2)

    def rom_compare(label, stats_a, stats_b):
        rom_a = stats_a["rom"] if stats_a else None
        rom_b = stats_b["rom"] if stats_b else None
        return {
            "joint": label,
            "session_a_rom": rom_a,
            "session_b_rom": rom_b,
            "delta": delta(rom_a, rom_b),
        }

    return {
        "session_a": session_a,
        "session_b": session_b,
        "score_a": a.gait_score,
        "score_b": b.gait_score,
        "score_delta": delta(a.gait_score, b.gait_score),
        "rom_comparison": [
            rom_compare("Left Hip",   a.left_hip_stats,   b.left_hip_stats),
            rom_compare("Left Knee",  a.left_knee_stats,  b.left_knee_stats),
            rom_compare("Right Hip",  a.right_hip_stats,  b.right_hip_stats),
            rom_compare("Right Knee", a.right_knee_stats, b.right_knee_stats),
        ],
        "symmetry_comparison": {
            "hip":  {"a": a.symmetry_index_hip,  "b": b.symmetry_index_hip,  "delta": delta(a.symmetry_index_hip,  b.symmetry_index_hip)},
            "knee": {"a": a.symmetry_index_knee, "b": b.symmetry_index_knee, "delta": delta(a.symmetry_index_knee, b.symmetry_index_knee)},
        },
    }
