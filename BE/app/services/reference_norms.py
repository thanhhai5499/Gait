"""
Reference Norms Service
=======================
Unified API over the three normative gait datasets bundled in
`app/reference_data/`:

  - NTU Dataset 2026   — kinematics (joint angle peaks + waveforms),
                          Southeast Asian, 50-80 years.
  - Yishun Study 2020  — spatiotemporal (gait speed, cadence, step length,
                          stance%, …), Southeast Asian, 21-90 years, by 9
                          age groups × 2 sexes.
  - Chinese Students 2023 — spatiotemporal for young adults (18-35 years)
                            + SPM kinematics regions (qualitative only).

This service answers two questions for the rest of the backend:

  1. Given a measured value (parameter, value, patient age, patient sex),
     which dataset is the best reference, and what is the Z-score + band?

  2. Given an entire GaitAnalysis row + a walk distance + patient age/sex,
     produce a list of Z-score evaluations for every parameter the system
     can derive from the sensors.

Bands follow the project methodology document (Section 5.2):
    |Z| < 1.0          → "normal"
    1.0 ≤ |Z| < 2.0    → "borderline"
    |Z| ≥ 2.0          → "abnormal"

All three readers convert input units appropriately so the caller can
always work in SI units (m, m/s, deg, s, steps/min, %).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional

from app.reference_data.ntu.ntu_reader import NTUReference
from app.reference_data.yishun.yishun_reader import YishunReference, age_to_group
from app.reference_data.chinese.chinese_reader import ChineseStudentsReference

logger = logging.getLogger(__name__)

Sex = Literal["men", "women"]
Band = Literal["normal", "borderline", "abnormal", "unavailable"]


# ---------------------------------------------------------------------------
# Lazy singletons — load each dataset once per process
# ---------------------------------------------------------------------------

_ntu: Optional[NTUReference] = None
_yishun: Optional[YishunReference] = None
_chinese: Optional[ChineseStudentsReference] = None


def get_ntu() -> NTUReference:
    global _ntu
    if _ntu is None:
        _ntu = NTUReference()
    return _ntu


def get_yishun() -> YishunReference:
    global _yishun
    if _yishun is None:
        _yishun = YishunReference()
    return _yishun


def get_chinese() -> ChineseStudentsReference:
    global _chinese
    if _chinese is None:
        _chinese = ChineseStudentsReference()
    return _chinese


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------

@dataclass
class Evaluation:
    """One Z-score evaluation against the best-fit reference dataset."""
    parameter: str
    measured: Optional[float]
    unit: str
    dataset: str                # 'ntu' | 'yishun' | 'chinese' | 'none'
    mean: Optional[float]
    sd: Optional[float]
    z: Optional[float]
    band: Band
    age_group: Optional[str]    # only for Yishun
    n: Optional[int]
    note: Optional[str] = None  # explanation if dataset is 'none' or fallback

    def to_dict(self) -> dict:
        return {
            "parameter":  self.parameter,
            "measured":   self.measured,
            "unit":       self.unit,
            "dataset":    self.dataset,
            "mean":       self.mean,
            "sd":         self.sd,
            "z":          self.z,
            "band":       self.band,
            "age_group":  self.age_group,
            "n":          self.n,
            "note":       self.note,
        }


# ---------------------------------------------------------------------------
# Dataset picker — which reference to use for a given parameter + patient
# ---------------------------------------------------------------------------

# Joint-angle scalar params live only in NTU.
NTU_KINEMATIC_KEYS = {
    "knee_peak_flexion_deg":  ("knee", "peak_flexion_deg"),
    "knee_peak_ext_deg":      ("knee", "peak_ext_deg"),
    "knee_stance_min_deg":    ("knee", "stance_min_deg"),
    "knee_rom_deg":           ("knee", "ROM_deg"),
    "hip_peak_flexion_deg":   ("hip",  "peak_flexion_deg"),
    "hip_peak_ext_deg":       ("hip",  "peak_ext_deg"),
    "hip_stance_min_deg":     ("hip",  "stance_min_deg"),
    "hip_rom_deg":            ("hip",  "ROM_deg"),
}

# Spatiotemporal params we can route to Yishun (primary) or Chinese (fallback).
SPATIOTEMPORAL_KEYS = {
    "gait_speed",
    "cadence",
    "step_length",
    "stride_length",
    "stride_width",
    "stance_pct",
    "double_support_time",
    "single_support_time",
    "cycle_time",
}


def _band(z: Optional[float]) -> Band:
    if z is None:
        return "unavailable"
    a = abs(z)
    if a < 1.0:
        return "normal"
    if a < 2.0:
        return "borderline"
    return "abnormal"


# ---------------------------------------------------------------------------
# Per-parameter evaluation
# ---------------------------------------------------------------------------

def evaluate_kinematic(parameter: str, measured: Optional[float]) -> Evaluation:
    """Z-score a joint-angle scalar (peak flexion, ROM, …) against NTU.

    `parameter` must be one of NTU_KINEMATIC_KEYS.
    NTU is age 50-80, but it is the only scalar source we have — the caller
    is responsible for warning the user if patient is outside that range.
    """
    if parameter not in NTU_KINEMATIC_KEYS:
        return Evaluation(parameter, measured, "deg", "none",
                          None, None, None, "unavailable", None, None,
                          note=f"Unknown kinematic parameter {parameter!r}")

    if measured is None:
        return Evaluation(parameter, None, "deg", "none",
                          None, None, None, "unavailable", None, None,
                          note="No measurement provided")

    joint, key = NTU_KINEMATIC_KEYS[parameter]
    try:
        ntu = get_ntu()
        row = ntu.get_norm(joint, key)
        z   = ntu.zscore(joint, key, measured)
        return Evaluation(
            parameter=parameter, measured=measured, unit="deg",
            dataset="ntu", mean=row.mean, sd=row.sd, z=z, band=_band(z),
            age_group=None, n=row.n,
        )
    except Exception as e:
        logger.exception("Kinematic evaluation failed for %s", parameter)
        return Evaluation(parameter, measured, "deg", "none",
                          None, None, None, "unavailable", None, None,
                          note=f"Error: {e}")


def evaluate_spatiotemporal(
    parameter: str,
    measured: Optional[float],
    age: int,
    sex: Sex,
) -> Evaluation:
    """Z-score a spatiotemporal value (m/s, steps/min, %, s) using Yishun
    (age 21-90, by age group + sex) or Chinese (18-20, overall by sex).

    Input units are SI:
      - gait_speed     → m/s   (Yishun stores cm/s, we convert)
      - step_length    → m     (Yishun stores cm, we convert)
      - stride_width   → m     (Yishun stores cm, we convert)
      - cadence        → steps/min
      - stance_pct     → percent (e.g. 62.5)
      - cycle_time, double/single_support_time → seconds
      - stride_length  → m  (only Chinese has this)
    """
    if measured is None:
        return Evaluation(parameter, None, "", "none",
                          None, None, None, "unavailable", None, None,
                          note="No measurement provided")

    if parameter not in SPATIOTEMPORAL_KEYS:
        return Evaluation(parameter, measured, "", "none",
                          None, None, None, "unavailable", None, None,
                          note=f"Unknown spatiotemporal parameter {parameter!r}")

    # Pick dataset by age
    use_chinese = age < 21
    use_yishun  = 21 <= age <= 90

    if not (use_chinese or use_yishun):
        return Evaluation(parameter, measured, "", "none",
                          None, None, None, "unavailable", None, None,
                          note=f"Age {age} outside supported range (18-90)")

    try:
        if use_yishun:
            return _eval_yishun(parameter, measured, age, sex)
        return _eval_chinese(parameter, measured, sex)
    except KeyError as e:
        return Evaluation(parameter, measured, "", "none",
                          None, None, None, "unavailable", None, None,
                          note=f"Parameter not in reference: {e}")
    except Exception as e:
        logger.exception("Spatiotemporal evaluation failed")
        return Evaluation(parameter, measured, "", "none",
                          None, None, None, "unavailable", None, None,
                          note=f"Error: {e}")


def _eval_yishun(parameter: str, measured: float, age: int, sex: Sex) -> Evaluation:
    """Map an SI-unit measurement to a Yishun-unit measurement, then Z-score."""
    ys = get_yishun()

    # Yishun parameter name + unit conversion
    if parameter == "gait_speed":
        ys_param, value, unit = "gait_speed", measured * 100, "cm/s"
    elif parameter == "step_length":
        ys_param, value, unit = "step_length", measured * 100, "cm"
    elif parameter == "stride_width":
        ys_param, value, unit = "stride_width", measured * 100, "cm"
    elif parameter == "cadence":
        ys_param, value, unit = "cadence", measured, "steps/min"
    elif parameter == "stance_pct":
        ys_param, value, unit = "stance_pct", measured, "%"
    elif parameter == "double_support_time":
        ys_param, value, unit = "double_support_time", measured, "s"
    elif parameter == "single_support_time":
        ys_param, value, unit = "single_support_time", measured, "s"
    elif parameter == "stride_length":
        return Evaluation(parameter, measured, "m", "none",
                          None, None, None, "unavailable", None, None,
                          note="stride_length not in Yishun — only step_length")
    elif parameter == "cycle_time":
        # Yishun reports stride_time-equivalent only via cadence (1/cycle_time*60 ≈ cadence/2).
        return Evaluation(parameter, measured, "s", "none",
                          None, None, None, "unavailable", None, None,
                          note="cycle_time not in Yishun — use cadence instead")
    else:
        return Evaluation(parameter, measured, "", "none",
                          None, None, None, "unavailable", None, None,
                          note=f"No Yishun mapping for {parameter}")

    row = ys.get_norm_for_age(sex, age, ys_param)
    z   = ys.zscore_for_age(sex, age, ys_param, value)
    return Evaluation(
        parameter=parameter, measured=measured, unit=unit,
        dataset="yishun", mean=row.mean, sd=row.sd, z=z, band=_band(z),
        age_group=row.age_group, n=row.n,
    )


def _eval_chinese(parameter: str, measured: float, sex: Sex) -> Evaluation:
    """For age 18-20 (and as a fallback). Chinese keeps units in SI already
    (m, m/s) so very little conversion needed."""
    cn = get_chinese()

    # Chinese param name = same as our SI keys, with one rename.
    cn_param = parameter
    if cn_param not in cn.list_parameters():
        return Evaluation(parameter, measured, "", "none",
                          None, None, None, "unavailable", None, None,
                          note=f"Chinese has no parameter {parameter}")

    row = cn.get_norm(sex, cn_param)
    z   = cn.zscore(sex, cn_param, measured)
    return Evaluation(
        parameter=parameter, measured=measured, unit=row.unit,
        dataset="chinese", mean=row.mean, sd=row.sd, z=z, band=_band(z),
        age_group=None, n=row.n,
    )


# ---------------------------------------------------------------------------
# Session-level evaluation
# ---------------------------------------------------------------------------

def evaluate_session(
    *,
    analysis,                       # models.GaitAnalysis (JSON-loaded)
    walk_distance_m: Optional[float],
    age: int,
    sex: Sex,
) -> Dict[str, List[Evaluation]]:
    """Run Z-score evaluations across every parameter we can derive.

    Returns:
      {
        "kinematic":      [Evaluation, ...]   # joint angle peaks/ROM
        "spatiotemporal": [Evaluation, ...]   # cadence, stance%, gait_speed, …
      }

    The caller is expected to pass a GaitAnalysis ORM row (or dict) that
    has the per-joint `*_stats` (mean/min/max/rom) and `*_gait_cycle`
    metrics produced by `gait_analyzer.analyze_session`.
    """
    kinematic: List[Evaluation] = []
    spatial: List[Evaluation] = []

    # ── Joint-angle peaks (use better of left/right per joint) ─────────
    def _stats(field: str) -> Optional[dict]:
        v = getattr(analysis, field, None) if not isinstance(analysis, dict) \
            else analysis.get(field)
        return v if v else None

    def _max_of(left: Optional[dict], right: Optional[dict]) -> Optional[float]:
        cands = [s["max"] for s in (left, right) if s and "max" in s]
        return max(cands) if cands else None

    def _min_of(left: Optional[dict], right: Optional[dict]) -> Optional[float]:
        cands = [s["min"] for s in (left, right) if s and "min" in s]
        return min(cands) if cands else None

    def _rom_avg(left: Optional[dict], right: Optional[dict]) -> Optional[float]:
        cands = [s["rom"] for s in (left, right) if s and "rom" in s]
        if not cands:
            return None
        return sum(cands) / len(cands)

    lh, rh = _stats("left_hip_stats"),  _stats("right_hip_stats")
    lk, rk = _stats("left_knee_stats"), _stats("right_knee_stats")

    # Kinematics — 8 tham số NTU
    kinematic.append(evaluate_kinematic("knee_peak_flexion_deg", _max_of(lk, rk)))
    kinematic.append(evaluate_kinematic("knee_peak_ext_deg",     _min_of(lk, rk)))
    kinematic.append(evaluate_kinematic("knee_rom_deg",          _rom_avg(lk, rk)))
    kinematic.append(evaluate_kinematic("hip_peak_flexion_deg",  _max_of(lh, rh)))
    kinematic.append(evaluate_kinematic("hip_peak_ext_deg",      _min_of(lh, rh)))
    kinematic.append(evaluate_kinematic("hip_rom_deg",           _rom_avg(lh, rh)))

    # ── Spatiotemporal (use best-of-leg gait cycle if available) ───────
    lgc = _stats("left_gait_cycle")
    rgc = _stats("right_gait_cycle")

    def _gc_field(key: str) -> Optional[float]:
        vals = [gc[key] for gc in (lgc, rgc) if gc and gc.get(key) is not None]
        if not vals:
            return None
        return sum(vals) / len(vals)

    cadence_avg = _gc_field("cadence_steps_per_min")
    cycle_avg_s = _gc_field("avg_duration_s")
    stance_avg  = _gc_field("stance_ratio")            # ratio in [0,1]

    spatial.append(evaluate_spatiotemporal("cadence", cadence_avg, age, sex))
    if stance_avg is not None:
        spatial.append(evaluate_spatiotemporal("stance_pct", stance_avg * 100, age, sex))
    else:
        spatial.append(evaluate_spatiotemporal("stance_pct", None, age, sex))

    # Gait speed: needs walk_distance_m + total walking time.
    gait_speed: Optional[float] = None
    if walk_distance_m and lgc and lgc.get("avg_duration_s") and cadence_avg:
        cycles_l = lgc.get("count") or 0
        cycles_r = (rgc or {}).get("count", 0) or 0
        cycles   = max(cycles_l, cycles_r)
        total_time_s = cycles * cycle_avg_s if cycle_avg_s and cycles else None
        if total_time_s and total_time_s > 0:
            gait_speed = walk_distance_m / total_time_s

    spatial.append(evaluate_spatiotemporal("gait_speed", gait_speed, age, sex))

    # Step length: gait_speed (m/s) / (cadence/60) = m per step
    step_length_m: Optional[float] = None
    if gait_speed is not None and cadence_avg and cadence_avg > 0:
        step_length_m = gait_speed / (cadence_avg / 60.0)
    spatial.append(evaluate_spatiotemporal("step_length", step_length_m, age, sex))

    # Cycle time (s) — Yishun không có tham số này nhưng ghi lại để FE hiển thị
    spatial.append(evaluate_spatiotemporal("cycle_time", cycle_avg_s, age, sex))

    return {"kinematic": kinematic, "spatiotemporal": spatial}


# ---------------------------------------------------------------------------
# Dataset info — for UI to show which reference is being used
# ---------------------------------------------------------------------------

def dataset_summary() -> dict:
    """Return metadata for all three loaded datasets."""
    return {
        "ntu":     get_ntu().metadata,
        "yishun":  get_yishun().metadata,
        "chinese": get_chinese().metadata,
    }
