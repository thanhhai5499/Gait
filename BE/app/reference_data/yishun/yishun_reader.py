"""
Yishun Study reader — primary spatiotemporal reference (Southeast Asia, 21-90 yr).

Loads:
  - yishun_norms_overall.csv  (Table 2: 13 params × 2 sexes)
  - yishun_norms_by_age.csv   (Tables 3+4: 14 params × 9 age groups × 2 sexes)
  - yishun_metadata.json

Source: Lau LK et al. (2020) Clin Interv Aging 15:1753-1765. doi:10.2147/CIA.S270407
Population: Southeast Asian, Singapore, n=507 adults aged 21-90.
Device: GAITRite 6m walkway, 120 Hz, habitual walking pace, barefoot.

Usage:
    from yishun_reader import YishunReference

    ys = YishunReference()

    # Look up norm for 65-year-old man, gait speed
    row = ys.get_norm_for_age(sex="men", age=65, parameter="gait_speed")
    print(row.mean, row.sd, row.age_group)

    # Z-score (measured in cm/s — same units as dataset)
    z = ys.zscore_for_age("men", 65, "gait_speed", measured=85.0)

    # Classify (returns z, band: normal / borderline / abnormal)
    result = ys.classify_for_age("men", 65, "gait_speed", measured=85.0)
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Literal, Optional

_HERE = Path(__file__).resolve().parent

Sex = Literal["men", "women"]

# 9 age groups in the source paper, in order.
AGE_GROUPS = ("21-30", "31-40", "41-50", "51-60", "61-65",
              "66-70", "71-75", "76-80", "81+")


def age_to_group(age: int) -> str:
    """Map an integer age to the Yishun age-group label (string)."""
    if age < 21:
        raise ValueError(f"Yishun reference covers age >= 21; got {age}")
    if age <= 30: return "21-30"
    if age <= 40: return "31-40"
    if age <= 50: return "41-50"
    if age <= 60: return "51-60"
    if age <= 65: return "61-65"
    if age <= 70: return "66-70"
    if age <= 75: return "71-75"
    if age <= 80: return "76-80"
    return "81+"


@dataclass(frozen=True)
class NormRow:
    sex: str
    parameter: str
    label: str
    unit: str
    mean: float
    sd: float
    n: int
    age_group: Optional[str] = None  # None for "overall" rows


@dataclass
class YishunReference:
    base_dir: Path = field(default_factory=lambda: _HERE)
    metadata: dict = field(init=False)
    overall: Dict[str, Dict[str, NormRow]] = field(init=False)   # sex -> param -> row
    by_age:  Dict[str, Dict[str, Dict[str, NormRow]]] = field(init=False)  # sex -> age -> param -> row

    def __post_init__(self) -> None:
        self.metadata = self._load_metadata()
        self.overall  = self._load_overall()
        self.by_age   = self._load_by_age()

    # ─────────────────────────── loaders ────────────────────────────

    def _load_metadata(self) -> dict:
        with (self.base_dir / "yishun_metadata.json").open(encoding="utf-8-sig") as f:
            return json.load(f)

    def _load_overall(self) -> Dict[str, Dict[str, NormRow]]:
        out: Dict[str, Dict[str, NormRow]] = {"men": {}, "women": {}}
        path = self.base_dir / "yishun_norms_overall.csv"
        with path.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                row = NormRow(
                    sex=r["sex"],
                    parameter=r["parameter"],
                    label=r["label"],
                    unit=r["unit"],
                    mean=float(r["mean"]),
                    sd=float(r["sd"]),
                    n=int(r["n"]),
                    age_group=None,
                )
                out.setdefault(row.sex, {})[row.parameter] = row
        return out

    def _load_by_age(self) -> Dict[str, Dict[str, Dict[str, NormRow]]]:
        out: Dict[str, Dict[str, Dict[str, NormRow]]] = {"men": {}, "women": {}}
        path = self.base_dir / "yishun_norms_by_age.csv"
        with path.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                row = NormRow(
                    sex=r["sex"],
                    parameter=r["parameter"],
                    label=r["label"],
                    unit=r["unit"],
                    mean=float(r["mean"]),
                    sd=float(r["sd"]),
                    n=int(r["n"]),
                    age_group=r["age_group"],
                )
                out.setdefault(row.sex, {}).setdefault(row.age_group, {})[row.parameter] = row
        return out

    # ───────────────────────── public API ───────────────────────────

    def get_norm_overall(self, sex: Sex, parameter: str) -> NormRow:
        if sex not in self.overall:
            raise KeyError(f"sex must be 'men' or 'women'; got {sex!r}")
        if parameter not in self.overall[sex]:
            raise KeyError(f"Unknown parameter {parameter!r} for {sex} overall")
        return self.overall[sex][parameter]

    def get_norm_by_age(self, sex: Sex, age_group: str, parameter: str) -> NormRow:
        if sex not in self.by_age:
            raise KeyError(f"sex must be 'men' or 'women'; got {sex!r}")
        if age_group not in self.by_age[sex]:
            raise KeyError(
                f"Unknown age_group {age_group!r}; expected one of {AGE_GROUPS}"
            )
        params = self.by_age[sex][age_group]
        if parameter not in params:
            raise KeyError(f"Unknown parameter {parameter!r} for {sex} {age_group}")
        return params[parameter]

    def get_norm_for_age(self, sex: Sex, age: int, parameter: str) -> NormRow:
        """Convenience: map age (int) -> age_group -> NormRow."""
        return self.get_norm_by_age(sex, age_to_group(age), parameter)

    # ───────────────────────── Z-score & classify ───────────────────

    @staticmethod
    def _classify_band(z: float) -> str:
        absz = abs(z)
        if absz < 1.0:
            return "normal"
        if absz < 2.0:
            return "borderline"
        return "abnormal"

    def zscore_by_age(self, sex: Sex, age_group: str, parameter: str, measured: float) -> float:
        row = self.get_norm_by_age(sex, age_group, parameter)
        if row.sd == 0:
            raise ValueError(f"SD is 0 for {sex}/{age_group}/{parameter}")
        return (measured - row.mean) / row.sd

    def zscore_for_age(self, sex: Sex, age: int, parameter: str, measured: float) -> float:
        return self.zscore_by_age(sex, age_to_group(age), parameter, measured)

    def classify_by_age(self, sex: Sex, age_group: str, parameter: str, measured: float) -> dict:
        """Z-score + clinical band; thresholds per project methodology Section 5.2."""
        row = self.get_norm_by_age(sex, age_group, parameter)
        z   = self.zscore_by_age(sex, age_group, parameter, measured)
        return {
            "sex": sex, "age_group": age_group, "parameter": parameter,
            "unit": row.unit, "measured": measured,
            "mean": row.mean, "sd": row.sd, "n": row.n,
            "z": z, "band": self._classify_band(z),
        }

    def classify_for_age(self, sex: Sex, age: int, parameter: str, measured: float) -> dict:
        result = self.classify_by_age(sex, age_to_group(age), parameter, measured)
        result["age"] = age
        return result

    # ─────────────────────── unit conversion helpers ────────────────

    @staticmethod
    def m_per_s_to_cm_per_s(v: float) -> float:
        """Convert m/s -> cm/s (Yishun gait_speed unit)."""
        return v * 100.0

    @staticmethod
    def m_to_cm(v: float) -> float:
        """Convert m -> cm (Yishun length unit)."""
        return v * 100.0


# ─────────────────────────── CLI demo ───────────────────────────────

def _demo() -> None:
    ys = YishunReference()

    print("─ Yishun overall (men vs women) ─")
    for param in ("gait_speed", "cadence", "step_length", "stance_pct"):
        m = ys.get_norm_overall("men",   param)
        w = ys.get_norm_overall("women", param)
        print(f"  {param:18s}  men {m.mean:6.2f}±{m.sd:5.2f}  "
              f"women {w.mean:6.2f}±{w.sd:5.2f}  unit={m.unit}")

    print("\n─ Trajectory of gait_speed (cm/s) across age groups, men ─")
    for ag in AGE_GROUPS:
        r = ys.get_norm_by_age("men", ag, "gait_speed")
        print(f"  {ag:6s}  mean={r.mean:6.2f}  sd={r.sd:5.2f}  n={r.n}")

    print("\n─ Example: 65-year-old man, measured gait_speed 0.85 m/s ─")
    measured_cm_s = YishunReference.m_per_s_to_cm_per_s(0.85)
    print(ys.classify_for_age("men", 65, "gait_speed", measured_cm_s))

    print("\n─ Example: 72-year-old woman, cadence 88 steps/min ─")
    print(ys.classify_for_age("women", 72, "cadence", 88))


if __name__ == "__main__":
    _demo()
