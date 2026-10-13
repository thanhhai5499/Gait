"""
NTU Dataset reader — reference values for Southeast Asian gait kinematics.

Loads the four primary artifacts in this folder:
  - ntu_norms_spatiotemporal.csv   (5 scalar parameters)
  - ntu_norms_joint_angles.csv     (8 scalar parameters for knee + hip)
  - ntu_waveform_hip.npy           (6, 101) — mean/sd/±2sd/q75/q25 by % gait cycle
  - ntu_waveform_knee.npy          (6, 101)

See README.md (cùng thư mục) for row semantics, sign conventions, and warnings.

Source: Roberts et al., Sci Data 2026 — DR-NTU Dataverse.
Population: Southeast Asian, Singapore, 50–80 years.

Usage:
    from ntu_reader import NTUReference
    ntu = NTUReference()
    z   = ntu.zscore("knee", "peak_flexion_deg", measured=48.0)
    cor = ntu.waveform_corridor("knee")
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Literal, Optional

import numpy as np

_HERE = Path(__file__).resolve().parent

WAVEFORM_ROW_NAMES = (
    "mean",        # row 0: point-wise mean
    "sd",          # row 1: point-wise standard deviation
    "upper_2sd",   # row 2: mean + 2·sd  (95% corridor upper)
    "lower_2sd",   # row 3: mean − 2·sd  (95% corridor lower)
    "q75",         # row 4: 75th percentile
    "q25",         # row 5: 25th percentile
)

Joint = Literal["hip", "knee"]


@dataclass(frozen=True)
class NormRow:
    """One row from a norms CSV (mean ± sd, quartiles, range, sample size)."""
    parameter: str
    mean: float
    sd: float
    median: float
    q25: float
    q75: float
    n: int
    # spatiotemporal CSV also carries min/max; joint_angles CSV does not.
    min: Optional[float] = None
    max: Optional[float] = None
    joint: Optional[str] = None   # only for joint-angle rows


@dataclass
class NTUReference:
    """In-memory access to NTU normative data."""

    base_dir: Path = field(default_factory=lambda: _HERE)
    metadata: dict = field(init=False)
    spatiotemporal: Dict[str, NormRow] = field(init=False)
    joint_angles: Dict[str, Dict[str, NormRow]] = field(init=False)  # joint → param → row
    _waveforms: Dict[str, np.ndarray] = field(init=False)

    def __post_init__(self) -> None:
        self.metadata        = self._load_metadata()
        self.spatiotemporal  = self._load_spatiotemporal()
        self.joint_angles    = self._load_joint_angles()
        self._waveforms      = self._load_waveforms()

    # ─────────────────────────── loaders ────────────────────────────

    def _load_metadata(self) -> dict:
        path = self.base_dir / "ntu_kinematics_metadata.json"
        with path.open(encoding="utf-8-sig") as f:
            return json.load(f)

    def _load_spatiotemporal(self) -> Dict[str, NormRow]:
        path = self.base_dir / "ntu_norms_spatiotemporal.csv"
        out: Dict[str, NormRow] = {}
        with path.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                out[r["parameter"]] = NormRow(
                    parameter=r["parameter"],
                    mean=float(r["mean"]),
                    sd=float(r["sd"]),
                    median=float(r["median"]),
                    q25=float(r["q25"]),
                    q75=float(r["q75"]),
                    min=float(r["min"]),
                    max=float(r["max"]),
                    n=int(r["n"]),
                )
        return out

    def _load_joint_angles(self) -> Dict[str, Dict[str, NormRow]]:
        path = self.base_dir / "ntu_norms_joint_angles.csv"
        out: Dict[str, Dict[str, NormRow]] = {"hip": {}, "knee": {}}
        with path.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                joint = r["joint"]
                out.setdefault(joint, {})[r["parameter"]] = NormRow(
                    parameter=r["parameter"],
                    mean=float(r["mean"]),
                    sd=float(r["sd"]),
                    median=float(r["median"]),
                    q25=float(r["q25"]),
                    q75=float(r["q75"]),
                    n=int(r["n"]),
                    joint=joint,
                )
        return out

    def _load_waveforms(self) -> Dict[str, np.ndarray]:
        return {
            "hip":  np.load(self.base_dir / "ntu_waveform_hip.npy"),
            "knee": np.load(self.base_dir / "ntu_waveform_knee.npy"),
        }

    # ───────────────────────── public API ───────────────────────────

    def get_norm(self, group: str, parameter: str) -> NormRow:
        """Look up a NormRow by group ('spatiotemporal' | 'hip' | 'knee') and parameter name."""
        if group == "spatiotemporal":
            if parameter not in self.spatiotemporal:
                raise KeyError(f"Unknown spatiotemporal parameter: {parameter!r}")
            return self.spatiotemporal[parameter]
        if group in self.joint_angles:
            if parameter not in self.joint_angles[group]:
                raise KeyError(f"Unknown {group} parameter: {parameter!r}")
            return self.joint_angles[group][parameter]
        raise KeyError(f"Unknown group: {group!r}")

    def zscore(self, group: str, parameter: str, measured: float) -> float:
        """Standard score: (measured − mean) / sd, using NTU normative mean & sd."""
        row = self.get_norm(group, parameter)
        if row.sd == 0:
            raise ValueError(f"SD is 0 for {group}/{parameter}; Z-score undefined")
        return (measured - row.mean) / row.sd

    def classify(self, group: str, parameter: str, measured: float) -> dict:
        """Return Z-score + clinical band (normal / borderline / abnormal).

        Thresholds match Section 5.2 of the project methodology document:
            |Z| < 1.0 → normal,  1.0 ≤ |Z| < 2.0 → borderline,  |Z| ≥ 2.0 → abnormal.
        """
        row = self.get_norm(group, parameter)
        z = self.zscore(group, parameter, measured)
        abs_z = abs(z)
        if abs_z < 1.0:
            band = "normal"
        elif abs_z < 2.0:
            band = "borderline"
        else:
            band = "abnormal"
        return {
            "group": group,
            "parameter": parameter,
            "measured": measured,
            "mean": row.mean,
            "sd": row.sd,
            "z": z,
            "band": band,
            "n": row.n,
        }

    # ────────────────────────── waveforms ───────────────────────────

    def waveform_corridor(self, joint: Joint) -> Dict[str, np.ndarray]:
        """Return all 6 reference curves for a joint, keyed by name.

        Each value is a (101,) array sampled at 0, 1, …, 100 % gait cycle.
        Keys: mean, sd, upper_2sd, lower_2sd, q75, q25.
        """
        if joint not in self._waveforms:
            raise KeyError(f"Unknown joint: {joint!r}; expected 'hip' or 'knee'")
        arr = self._waveforms[joint]
        return {name: arr[i].copy() for i, name in enumerate(WAVEFORM_ROW_NAMES)}

    def compare_waveform(
        self,
        joint: Joint,
        patient_curve: Iterable[float],
    ) -> dict:
        """Compare a patient's normalised gait-cycle curve against NTU corridor.

        Args:
            joint: 'hip' or 'knee'.
            patient_curve: array-like of length 101 (already resampled to 0–100 %).

        Returns:
            dict with point-wise Z-scores, RMSE vs mean, and counts of out-of-corridor points.
        """
        curve = np.asarray(list(patient_curve), dtype=float)
        if curve.shape != (101,):
            raise ValueError(
                f"patient_curve must be length 101 (0–100 % gait cycle); got {curve.shape}"
            )
        ref = self.waveform_corridor(joint)
        mean, sd  = ref["mean"], ref["sd"]
        upper, lower = ref["upper_2sd"], ref["lower_2sd"]

        # Guard against zero sd at a sample (shouldn't happen in NTU, but be safe).
        safe_sd = np.where(sd == 0, np.nan, sd)
        z_curve = (curve - mean) / safe_sd

        outside = (curve > upper) | (curve < lower)
        rmse    = float(np.sqrt(np.mean((curve - mean) ** 2)))

        return {
            "joint": joint,
            "rmse_vs_mean_deg": rmse,
            "z_curve": z_curve,
            "points_outside_95pct_corridor": int(outside.sum()),
            "total_points": 101,
            "fraction_outside": float(outside.mean()),
        }


# ─────────────────────────── CLI demo ───────────────────────────────

def _demo() -> None:
    ntu = NTUReference()

    print("─ NTU spatiotemporal norms ─")
    for name, row in ntu.spatiotemporal.items():
        print(f"  {name:22s}  mean={row.mean:7.3f}  sd={row.sd:6.3f}  n={row.n}")

    print("\n─ NTU joint-angle norms ─")
    for joint, params in ntu.joint_angles.items():
        for name, row in params.items():
            print(f"  {joint:5s}  {name:18s}  mean={row.mean:7.2f}  sd={row.sd:5.2f}")

    print("\n─ Example: patient with peak knee flexion = 48° ─")
    print(ntu.classify("knee", "peak_flexion_deg", 48.0))

    print("\n─ Example: patient with gait speed = 0.85 m/s ─")
    print(ntu.classify("spatiotemporal", "gait_speed_ms", 0.85))

    print("\n─ Knee waveform corridor (% cycle → mean ± 2σ) ─")
    cor = ntu.waveform_corridor("knee")
    for pct in (0, 25, 50, 70, 100):
        print(
            f"  {pct:3d}%   mean={cor['mean'][pct]:6.2f}  "
            f"corridor=[{cor['lower_2sd'][pct]:6.2f}, {cor['upper_2sd'][pct]:6.2f}]"
        )


if __name__ == "__main__":
    _demo()
