"""
Group (cohort) analysis — admin only
  GET /admin/group-analysis — average gait metrics for users filtered by
                               sex + age range, using each user's most
                               recently analyzed session.
"""
from statistics import mean
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.auth.utils import require_admin

router = APIRouter(prefix="/admin", tags=["Group Analysis"])


def _avg(values: List[Optional[float]]) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return round(mean(clean), 2) if clean else None


def _avg_joint_stats(stats_list: List[Optional[dict]]) -> Optional[dict]:
    clean = [s for s in stats_list if s]
    if not clean:
        return None
    return {
        "mean": _avg([s.get("mean") for s in clean]),
        "std":  _avg([s.get("std")  for s in clean]),
        "min":  _avg([s.get("min")  for s in clean]),
        "max":  _avg([s.get("max")  for s in clean]),
        "rom":  _avg([s.get("rom")  for s in clean]),
        "n":    len(clean),
    }


def _avg_gait_cycle(gc_list: List[Optional[dict]]) -> Optional[dict]:
    clean = [g for g in gc_list if g]
    if not clean:
        return None
    return {
        "count":                 _avg([g.get("count") for g in clean]),
        "avg_duration_s":        _avg([g.get("avg_duration_s") for g in clean]),
        "cadence_steps_per_min": _avg([g.get("cadence_steps_per_min") for g in clean]),
        "stance_ratio":          _avg([g.get("stance_ratio") for g in clean]),
        "n":                     len(clean),
    }


def _band_from_z(z: Optional[float]) -> str:
    if z is None:
        return "unavailable"
    az = abs(z)
    if az < 1.0:
        return "normal"
    if az < 2.0:
        return "borderline"
    return "abnormal"


def _si_band(si: Optional[float]) -> str:
    if si is None:
        return "unavailable"
    if si < 10:
        return "normal"
    if si < 25:
        return "borderline"
    return "abnormal"


def _aggregate_symmetry(all_symmetry: List[dict]) -> List[dict]:
    by_param: Dict[str, List[dict]] = {}
    for ev in all_symmetry:
        by_param.setdefault(ev.get("parameter"), []).append(ev)

    out = []
    for param, evs in by_param.items():
        measured_avg = _avg([e.get("measured") for e in evs])
        first = evs[0]
        out.append({
            "parameter": param,
            "label":     first.get("label"),
            "measured":  measured_avg,
            "unit":      first.get("unit"),
            "threshold": first.get("threshold"),
            "band":      _si_band(measured_avg),
            "note":      None,
            "n":         len(evs),
        })
    return out


def _aggregate_evaluations(all_evals: List[dict]) -> List[dict]:
    """Group per-user evaluation dicts (already computed at analyze-time)
    by `parameter`, average z/measured, and re-classify the band from the
    averaged z-score."""
    by_param: Dict[str, List[dict]] = {}
    for ev in all_evals:
        by_param.setdefault(ev.get("parameter"), []).append(ev)

    out = []
    for param, evs in by_param.items():
        z_avg = _avg([e.get("z") for e in evs])
        first = evs[0]
        out.append({
            "parameter":  param,
            "measured":   _avg([e.get("measured") for e in evs]),
            "unit":       first.get("unit"),
            "dataset":    first.get("dataset"),
            "mean":       _avg([e.get("mean") for e in evs]),
            "sd":         _avg([e.get("sd") for e in evs]),
            "z":          z_avg,
            "band":       _band_from_z(z_avg),
            "age_group":  first.get("age_group"),
            "n":          len(evs),
        })
    return out


@router.get("/group-analysis")
def group_analysis(
    sex: Optional[str] = Query(None, pattern="^(male|female)$", description="Bỏ trống = tất cả"),
    age_min: int = Query(..., ge=0, le=130),
    age_max: int = Query(..., ge=0, le=130),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    query = db.query(models.User).filter(
        models.User.age.isnot(None),
        models.User.age >= age_min,
        models.User.age <= age_max,
    )
    if sex:
        query = query.filter(models.User.sex == models.Sex(sex))
    users = query.all()

    members = []
    for user in users:
        session = (
            db.query(models.MeasurementSession)
            .join(models.GaitAnalysis)
            .filter(models.MeasurementSession.user_id == user.id)
            .order_by(models.MeasurementSession.start_time.desc().nullslast(),
                      models.MeasurementSession.created_at.desc())
            .first()
        )
        if not session or not session.analysis:
            continue
        members.append({"user": user, "session": session, "analysis": session.analysis})

    if not members:
        return {
            "filters": {"sex": sex, "age_min": age_min, "age_max": age_max},
            "member_count": 0,
            "members": [],
            "avg_gait_score": None,
            "rom_avg": None,
            "symmetry_avg": None,
            "gait_cycle_avg": None,
            "reference_evaluations": None,
        }

    analyses = [m["analysis"] for m in members]

    rom_avg = {
        "left_hip":   _avg_joint_stats([a.left_hip_stats   for a in analyses]),
        "left_knee":  _avg_joint_stats([a.left_knee_stats  for a in analyses]),
        "right_hip":  _avg_joint_stats([a.right_hip_stats  for a in analyses]),
        "right_knee": _avg_joint_stats([a.right_knee_stats for a in analyses]),
    }

    symmetry_avg = {
        "hip":  _avg([a.symmetry_index_hip  for a in analyses]),
        "knee": _avg([a.symmetry_index_knee for a in analyses]),
    }

    gait_cycle_avg = {
        "left":  _avg_gait_cycle([a.left_gait_cycle  for a in analyses]),
        "right": _avg_gait_cycle([a.right_gait_cycle for a in analyses]),
    }

    all_kinematic: List[dict] = []
    all_spatiotemporal: List[dict] = []
    all_symmetry: List[dict] = []
    for a in analyses:
        ref = a.reference_evaluations or {}
        all_kinematic.extend(ref.get("kinematic") or [])
        all_spatiotemporal.extend(ref.get("spatiotemporal") or [])
        all_symmetry.extend(ref.get("symmetry") or [])

    reference_evaluations = None
    if all_kinematic or all_spatiotemporal or all_symmetry:
        kinematic      = _aggregate_evaluations(all_kinematic)
        spatiotemporal = _aggregate_evaluations(all_spatiotemporal)
        symmetry       = _aggregate_symmetry(all_symmetry)

        summary = {"normal": 0, "borderline": 0, "abnormal": 0, "unavailable": 0}
        for ev in (*kinematic, *spatiotemporal, *symmetry):
            summary[ev["band"]] = summary.get(ev["band"], 0) + 1

        reference_evaluations = {
            "kinematic": kinematic,
            "spatiotemporal": spatiotemporal,
            "symmetry": symmetry,
            "clinical_notes": [],
            "summary": summary,
            "patient": None,
        }

    return {
        "filters": {"sex": sex, "age_min": age_min, "age_max": age_max},
        "member_count": len(members),
        "members": [
            {
                "user_id":      m["user"].id,
                "full_name":    m["user"].full_name,
                "age":          m["user"].age,
                "sex":          m["user"].sex.value if m["user"].sex else None,
                "session_id":   m["session"].id,
                "session_code": m["session"].session_code,
                "gait_score":   m["analysis"].gait_score,
            }
            for m in members
        ],
        "avg_gait_score": _avg([a.gait_score for a in analyses]),
        "rom_avg": rom_avg,
        "symmetry_avg": symmetry_avg,
        "gait_cycle_avg": gait_cycle_avg,
        "reference_evaluations": reference_evaluations,
    }
