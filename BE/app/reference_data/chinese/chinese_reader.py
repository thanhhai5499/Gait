"""
Chinese University Students dataset reader — spatiotemporal reference for young adults.

Loads:
  - chinese_norms_spatiotemporal.csv   (17 params × 2 sexes, with p-values)
  - chinese_demographics.csv           (Table 2 anthropometrics)
  - chinese_kinematics_regions.csv     (SPM significant sex-difference regions)
  - chinese_metadata.json

Source: Yu JS et al. (2023) World J Clin Cases 11(29):7061-7074.
        doi:10.12998/wjcc.v11.i29.7061 — PMC10631401
Population: Han Chinese university students, 18-35 years, BMI 18.5-23.9, n=171.
Device: Qualisys 3D motion capture (1100 Hz) + Kistler force plates.

Important unit note (vs Yishun):
    Yu reports speed in m/s and length in m;
    Yishun reports speed in cm/s and length in cm.
    Use the m_to_cm() helpers to bridge.

Usage:
    from chinese_reader import ChineseStudentsReference
    cn = ChineseStudentsReference()

    z = cn.zscore("men", "gait_speed", measured=1.10)   # measured in m/s
    print(cn.classify("women", "step_length", measured=0.55))
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

_HERE = Path(__file__).resolve().parent

Sex = Literal["men", "women"]


@dataclass(frozen=True)
class NormRow:
    sex: str
    parameter: str
    label: str
    unit: str
    mean: float
    sd: float
    n: int
    p_value: Optional[str] = None  # raw text from paper (e.g. "<0.05", "0.35", "NS")


@dataclass(frozen=True)
class DemographicsRow:
    group: str
    parameter: str
    unit: str
    mean: float
    sd: float
    n: int


@dataclass(frozen=True)
class KinematicRegion:
    joint: str
    plane: str
    parameter: str
    region_start_pct: int
    region_end_pct: int
    p_value: str
    note: str


@dataclass
class ChineseStudentsReference:
    base_dir: Path = field(default_factory=lambda: _HERE)
    metadata: dict = field(init=False)
    spatiotemporal: Dict[str, Dict[str, NormRow]] = field(init=False)  # sex -> param -> row
    demographics: Dict[str, Dict[str, DemographicsRow]] = field(init=False)  # group -> param
    kinematic_regions: List[KinematicRegion] = field(init=False)

    def __post_init__(self) -> None:
        self.metadata          = self._load_metadata()
        self.spatiotemporal    = self._load_spatiotemporal()
        self.demographics      = self._load_demographics()
        self.kinematic_regions = self._load_regions()

    # ─────────────────────────── loaders ────────────────────────────

    def _load_metadata(self) -> dict:
        with (self.base_dir / "chinese_metadata.json").open(encoding="utf-8-sig") as f:
            return json.load(f)

    def _load_spatiotemporal(self) -> Dict[str, Dict[str, NormRow]]:
        out: Dict[str, Dict[str, NormRow]] = {"men": {}, "women": {}}
        path = self.base_dir / "chinese_norms_spatiotemporal.csv"
        with path.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                row = NormRow(
                    sex=r["sex"], parameter=r["parameter"], label=r["label"],
                    unit=r["unit"], mean=float(r["mean"]), sd=float(r["sd"]),
                    n=int(r["n"]), p_value=r.get("p_value"),
                )
                out.setdefault(row.sex, {})[row.parameter] = row
        return out

    def _load_demographics(self) -> Dict[str, Dict[str, DemographicsRow]]:
        out: Dict[str, Dict[str, DemographicsRow]] = {}
        path = self.base_dir / "chinese_demographics.csv"
        with path.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                row = DemographicsRow(
                    group=r["group"], parameter=r["parameter"], unit=r["unit"],
                    mean=float(r["mean"]), sd=float(r["sd"]), n=int(r["n"]),
                )
                out.setdefault(row.group, {})[row.parameter] = row
        return out

    def _load_regions(self) -> List[KinematicRegion]:
        out: List[KinematicRegion] = []
        path = self.base_dir / "chinese_kinematics_regions.csv"
        with path.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                out.append(KinematicRegion(
                    joint=r["joint"], plane=r["plane"], parameter=r["parameter"],
                    region_start_pct=int(r["region_start_pct"]),
                    region_end_pct=int(r["region_end_pct"]),
                    p_value=r["p_value"], note=r["note"],
                ))
        return out

    # ───────────────────────── public API ───────────────────────────

    def get_norm(self, sex: Sex, parameter: str) -> NormRow:
        if sex not in self.spatiotemporal:
            raise KeyError(f"sex must be 'men' or 'women'; got {sex!r}")
        if parameter not in self.spatiotemporal[sex]:
            raise KeyError(f"Unknown parameter {parameter!r} for sex={sex}")
        return self.spatiotemporal[sex][parameter]

    def list_parameters(self) -> List[str]:
        return list(self.spatiotemporal["men"].keys())

    def zscore(self, sex: Sex, parameter: str, measured: float) -> float:
        row = self.get_norm(sex, parameter)
        if row.sd == 0:
            raise ValueError(f"SD is 0 for {sex}/{parameter}")
        return (measured - row.mean) / row.sd

    def classify(self, sex: Sex, parameter: str, measured: float) -> dict:
        """Z-score + clinical band (normal / borderline / abnormal).

        Thresholds match project methodology Section 5.2:
            |Z| < 1.0  → normal
            1.0 ≤ |Z| < 2.0  → borderline
            |Z| ≥ 2.0  → abnormal
        """
        row = self.get_norm(sex, parameter)
        z   = self.zscore(sex, parameter, measured)
        absz = abs(z)
        band = "normal" if absz < 1.0 else "borderline" if absz < 2.0 else "abnormal"
        return {
            "sex": sex, "parameter": parameter, "unit": row.unit,
            "measured": measured, "mean": row.mean, "sd": row.sd, "n": row.n,
            "z": z, "band": band, "p_value_sex_diff": row.p_value,
        }

    def regions_for_joint(self, joint: str) -> List[KinematicRegion]:
        """Return all SPM significant sex-difference regions for hip/knee/ankle."""
        return [r for r in self.kinematic_regions if r.joint == joint]

    # ─────────────────────── unit conversion helpers ────────────────

    @staticmethod
    def m_per_s_to_cm_per_s(v: float) -> float:
        return v * 100.0

    @staticmethod
    def m_to_cm(v: float) -> float:
        return v * 100.0


# ─────────────────────────── CLI demo ───────────────────────────────

def _demo() -> None:
    cn = ChineseStudentsReference()

    print("─ Chinese students spatiotemporal (men vs women) ─")
    for param in ("gait_speed", "cadence", "step_length", "stance_pct", "cycle_time"):
        m = cn.get_norm("men",   param)
        w = cn.get_norm("women", param)
        print(f"  {param:18s}  men {m.mean:7.3f}±{m.sd:5.3f}  "
              f"women {w.mean:7.3f}±{w.sd:5.3f}  unit={m.unit}  p={m.p_value}")

    print("\n─ Demographics ─")
    for grp in ("total", "men", "women"):
        d = cn.demographics[grp]
        print(f"  {grp:6s}  n={d['age'].n}  age={d['age'].mean:.2f}±{d['age'].sd:.2f}  "
              f"height={d['height'].mean:.2f}m  BMI={d['bmi'].mean:.2f}")

    print("\n─ Example: 24-year-old man, gait_speed = 1.10 m/s ─")
    print(cn.classify("men", "gait_speed", 1.10))

    print("\n─ Example: 22-year-old woman, step_length = 0.55 m ─")
    print(cn.classify("women", "step_length", 0.55))

    print("\n─ Knee SPM regions of sex difference ─")
    for r in cn.regions_for_joint("knee"):
        marker = "★" if r.p_value != "NS" else " "
        print(f"  {marker} {r.plane:11s} {r.parameter:25s}  "
              f"{r.region_start_pct:3d}-{r.region_end_pct:3d}%  p={r.p_value}")


if __name__ == "__main__":
    _demo()
