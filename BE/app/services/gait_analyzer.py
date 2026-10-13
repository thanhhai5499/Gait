"""
Gait Analyzer Service
=====================
Computes biomechanical metrics from a list of SensorReading ORM objects.

Sensor mapping (18-field serial format):
  - left_hip, left_knee, right_hip, right_knee  — góc khớp (deg)
  - left_force_1/2, right_force_1/2             — FSR dual (ADC)
  - accel_x/y/z                                 — gia tốc IMU
  - gyro_x/y/z                                  — con quay hồi chuyển (deg/s)
  - magn_x/y/z                                  — từ trường (μT hoặc raw)

Metrics computed
----------------
Per joint (hip / knee, left & right):
  - mean, std, min, max, ROM (range of motion)

Per leg:
  - gait cycle count, avg cycle duration, cadence, stance-phase ratio

Symmetry:
  - Symmetry Index (SI) for hip, knee ROM
    SI = 2 * |X_left - X_right| / (|X_left| + |X_right|) * 100

IMU stats (accelerometer, gyroscope, magnetometer):
  - mean, std, rms (AC-coupled), range_p2p per axis

Overall score:
  - Heuristic 0-100 based on ROM closeness to normative values
    and symmetry indices.
"""
import logging
from typing import List, Optional

import numpy as np

from app.models import SensorReading, GaitAnalysis, GaitPhase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normative ROM values (degrees) — simplified adult walking norms
# (For Z-score against real datasets see app.services.reference_norms)
# ---------------------------------------------------------------------------
NORMS = {
    # Nguồn: NTU Dataset 2026 — Roberts et al. Sci Data (Đông Nam Á, 50-80 tuổi, n=70)
    # app/reference_data/ntu/ntu_norms_joint_angles.csv → hip/knee, ROM_deg, mean
    "hip":  {"mean": 5.0,  "rom": 30.49},
    "knee": {"mean": 25.0, "rom": 44.8},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_array(values: List[Optional[float]]) -> np.ndarray:
    return np.array([v for v in values if v is not None], dtype=float)


def _joint_stats(arr: np.ndarray) -> Optional[dict]:
    """min/max dùng percentile 5-95 (không phải cực trị tuyệt đối) để khớp
    công thức bên camera (computeJointStats trong CameraAnalysis.jsx) — một
    mẫu nhiễu/spike ADC không còn thổi phồng ROM/peak flexion-extension."""
    if arr.size == 0:
        return None
    p5, p95 = float(np.percentile(arr, 5)), float(np.percentile(arr, 95))
    return {
        "mean": float(np.mean(arr)),
        "std":  float(np.std(arr)),
        "min":  p5,
        "max":  p95,
        "rom":  p95 - p5,
    }


def _symmetry_index(rom_left: Optional[float], rom_right: Optional[float]) -> Optional[float]:
    if rom_left is None or rom_right is None:
        return None
    denom = abs(rom_left) + abs(rom_right)
    if denom == 0:
        return 0.0
    return float(2 * abs(rom_left - rom_right) / denom * 100)


# Chu kỳ dáng đi hợp lệ phải nằm trong khoảng này — khớp NTU cycle_filter_seconds
# (app/reference_data/ntu/ntu_kinematics_metadata.json). Cũng dùng làm khoảng
# debounce tối thiểu giữa 2 heel-strike, vì 0.5s là chu kỳ nhanh nhất khả dĩ
# về mặt sinh lý — nhiễu tín hiệu dao động quanh ngưỡng không thể tạo heel-strike
# hợp lệ nhanh hơn mức này.
_CYCLE_MIN_S = 0.5
_CYCLE_MAX_S = 2.5


def _gait_cycle_metrics(
    phases: List[GaitPhase],
    timestamps_ms: List[float],
) -> Optional[dict]:
    """Detect gait cycles from phase transitions (swing → stance = heel strike).

    Returns None if fewer than 2 valid cycles detected.
    stance_ratio / swing_ratio: per-cycle average (không bị lệch bởi
    recording bắt đầu/kết thúc giữa chu kỳ).

    cadence_steps_per_min tính theo định nghĩa lâm sàng (Yishun/GAITRite):
    tổng số bước CẢ HAI CHÂN mỗi phút. avg_duration_s là 1 chu kỳ dáng đi của
    MỘT chân (= 2 bước), nên cadence = 120 / avg_duration_s, không phải 60.
    """
    if len(phases) < 4:
        return None

    heel_strikes: list = []
    last_known_gc = None
    for i, p in enumerate(phases):
        if p == GaitPhase.stance and last_known_gc == GaitPhase.swing:
            # Debounce: bỏ qua heel-strike ứng viên nếu quá gần lần trước —
            # tránh nhiễu tín hiệu dao động quanh ngưỡng tạo heel-strike giả.
            if not heel_strikes or (timestamps_ms[i] - timestamps_ms[heel_strikes[-1]]) / 1000.0 >= _CYCLE_MIN_S:
                heel_strikes.append(i)
        if p != GaitPhase.unknown:
            last_known_gc = p

    if len(heel_strikes) < 2:
        return None

    lo_ms, hi_ms = _CYCLE_MIN_S * 1000.0, _CYCLE_MAX_S * 1000.0

    durations_ms: list = []
    cycle_stance_ratios: list = []
    for i in range(1, len(heel_strikes)):
        dur = timestamps_ms[heel_strikes[i]] - timestamps_ms[heel_strikes[i - 1]]
        if dur < lo_ms or dur > hi_ms:
            continue  # chu kỳ bất thường (nhiễu / dừng giữa chừng) — loại theo NTU cycle_filter_seconds
        durations_ms.append(dur)
        seg = phases[heel_strikes[i - 1] : heel_strikes[i]]
        if seg:
            n_st = sum(1 for p in seg if p == GaitPhase.stance)
            cycle_stance_ratios.append(n_st / len(seg))

    if not durations_ms:
        return None

    avg_dur_s = float(np.mean(durations_ms)) / 1000.0
    cadence = 120.0 / avg_dur_s if avg_dur_s > 0 else 0.0

    stance_ratio = float(np.mean(cycle_stance_ratios)) if cycle_stance_ratios else 0.0
    swing_ratio  = round(1.0 - stance_ratio, 3)

    return {
        "count":                 len(durations_ms),
        "avg_duration_s":        round(avg_dur_s, 3),
        "cadence_steps_per_min": round(cadence, 1),
        "stance_ratio":          round(stance_ratio, 3),
        "swing_ratio":           swing_ratio,
    }


# ---------------------------------------------------------------------------
# FSR force analysis — heel strike & toe push-off per foot
# ---------------------------------------------------------------------------

# Ngưỡng tiếp xúc tối thiểu (tính theo % range tín hiệu)
FSR_CONTACT_THRESHOLD = 100.0
# Tín hiệu phải có range >= MIN_SIGNAL_RANGE mới đủ để phân tích
_FSR_MIN_SIGNAL_RANGE = 50.0


def _adaptive_phases(force_arr: np.ndarray, fallback: List[GaitPhase]) -> List[GaitPhase]:
    """Tính gait phase từ tín hiệu lực theo ngưỡng adaptive.

    Ngưỡng cứng (300/100 ADC) thất bại khi mỗi cảm biến có range mV khác nhau.
    Hàm này dùng min/max thực tế của session:
      - swing   : ≤ min + 10% range
      - stance  : ≥ min + 35% range
      - unknown : khoảng giữa (tránh flicker)
    Nếu range < _FSR_MIN_SIGNAL_RANGE (tín hiệu phẳng), fallback sang phase đã lưu.
    """
    if force_arr.size == 0:
        return fallback
    sig_min   = float(force_arr.min())
    sig_range = float(force_arr.max()) - sig_min
    if sig_range < _FSR_MIN_SIGNAL_RANGE:
        return fallback
    swing_thresh  = sig_min + 0.10 * sig_range
    stance_thresh = sig_min + 0.35 * sig_range
    phases: List[GaitPhase] = []
    for v in force_arr:
        if v <= swing_thresh:
            phases.append(GaitPhase.swing)
        elif v >= stance_thresh:
            phases.append(GaitPhase.stance)
        else:
            phases.append(GaitPhase.unknown)
    return phases


def _find_peaks_direct(
    signal: np.ndarray,
    ts: np.ndarray,
    min_height_pct: float = 0.40,
    min_gap_s: float = 0.30,
) -> list:
    """Tìm local maxima trong tín hiệu lực — không dùng phase labels.

    Heel strike = local maximum vượt ngưỡng height tối thiểu
    với khoảng cách tối thiểu giữa các peak (ràng buộc sinh lý học).

    Ưu điểm so với phase-based: không phụ thuộc vào việc tín hiệu
    swing xuống đủ thấp để vượt swing_threshold.
    """
    if signal.size < 10:
        return []
    sig_range = float(signal.max() - signal.min())
    if sig_range < _FSR_MIN_SIGNAL_RANGE:
        return []

    min_height = float(signal.min()) + min_height_pct * sig_range
    # Khoảng cách tối thiểu giữa các peak (tính theo số mẫu)
    dt_ms = float(np.median(np.diff(ts))) if len(ts) > 1 else 20.0
    min_gap = max(3, int(min_gap_s * 1000.0 / dt_ms))
    half_w  = max(2, min_gap // 4)  # cửa sổ local-max check

    peaks: list = []
    for i in range(half_w, len(signal) - half_w):
        if signal[i] < min_height:
            continue
        # Local maximum trong cửa sổ 2*half_w
        if signal[i] < signal[i - half_w : i + half_w + 1].max():
            continue
        # Khoảng cách tối thiểu với peak trước
        if peaks and (i - peaks[-1]) < min_gap:
            continue
        peaks.append(i)
    return peaks


def _find_valleys_direct(
    signal: np.ndarray,
    ts: np.ndarray,
    max_height_pct: float = 0.25,
    min_gap_s: float = 0.30,
) -> list:
    """Tìm local minima — dùng để detect toe-off (lúc force giảm đến đáy)."""
    return _find_peaks_direct(-signal, ts, min_height_pct=max_height_pct, min_gap_s=min_gap_s)


def _fsr_foot_stats(
    readings: List[SensorReading],
    toe_attr: str,
    heel_attr: str,
    phase_attr: str,
) -> Optional[dict]:
    """Phân tích lực FSR một chân.

    toe_attr  : 'left_force_1'  / 'right_force_1'  (mũi chân)
    heel_attr : 'left_force_2'  / 'right_force_2'  (gót chân)
    phase_attr: 'phase_left'    / 'phase_right'    (dùng làm fallback)

    Heel strike detection: dùng local peak detection trực tiếp trên tín hiệu lực,
    không phụ thuộc vào phase labels (tránh lỗi 44 vs 2 khi một sensor
    không xuống đủ thấp để cross swing_threshold).
    """
    ts     = np.array([r.timestamp_ms for r in readings], dtype=float)
    toe_f  = np.array([getattr(r, toe_attr)  or 0.0 for r in readings], dtype=float)
    heel_f = np.array([getattr(r, heel_attr) or 0.0 for r in readings], dtype=float)
    n = len(readings)

    # ── Heel strike: direct local peak detection on heel force signal ──────
    heel_strike_idx = _find_peaks_direct(heel_f, ts, min_height_pct=0.40, min_gap_s=0.30)

    # Toe-off không cần detect riêng — toe push-off peak lấy trực tiếp
    # trong từng gait cycle (giữa 2 heel strike liên tiếp)

    # ── heel peak force at each strike ────────────────────────────────────
    heel_peaks = []
    loading_rates = []
    WINDOW = 25  # ~500ms @ 50Hz

    for idx in heel_strike_idx:
        end = min(idx + WINDOW, n)
        window = heel_f[idx:end]
        if window.size == 0:
            continue
        peak = float(window.max())
        if peak > FSR_CONTACT_THRESHOLD:
            heel_peaks.append(peak)
            # loading rate: max slope trong 10 mẫu đầu
            w10 = window[:10]
            if w10.size > 1:
                dt_arr = np.diff(ts[idx:idx + 10])
                dt_arr[dt_arr == 0] = 1.0
                slopes = np.diff(w10) / dt_arr[:len(np.diff(w10))]
                pos = slopes[slopes > 0]
                if pos.size:
                    loading_rates.append(float(pos.mean()))

    # ── toe push-off peak: max lực mũi trong mỗi chu kỳ bước ───────────
    # Đúng với sinh lý học: gót chạm trước → mũi đẩy cuối chu kỳ trước khi gót tiếp theo chạm
    toe_peaks = []
    for i, hs_start in enumerate(heel_strike_idx):
        hs_end = heel_strike_idx[i + 1] if i + 1 < len(heel_strike_idx) else n
        window = toe_f[hs_start:hs_end]
        if window.size == 0:
            continue
        peak = float(window.max())
        if peak > FSR_CONTACT_THRESHOLD:
            toe_peaks.append(peak)

    result: dict = {}

    if heel_peaks:
        result["heel"] = {
            "peak_mean":   round(float(np.mean(heel_peaks)), 1),
            "peak_std":    round(float(np.std(heel_peaks)),  1),
            "peak_max":    round(float(np.max(heel_peaks)),  1),
            "n_strikes":   len(heel_peaks),
        }

    if loading_rates:
        result["loading_rate"] = {
            "mean": round(float(np.mean(loading_rates)), 3),
            "std":  round(float(np.std(loading_rates)),  3),
            "unit": "ADC/ms",
            "note": "Tốc độ tăng lực gót khi tiếp đất — cao = va chạm mạnh",
        }

    if toe_peaks:
        result["toe"] = {
            "peak_mean": round(float(np.mean(toe_peaks)), 1),
            "peak_std":  round(float(np.std(toe_peaks)),  1),
            "peak_max":  round(float(np.max(toe_peaks)),  1),
            "n_pushoffs": len(toe_peaks),
        }

    return result if result else None


def _fsr_stats(readings: List[SensorReading]) -> Optional[dict]:
    """Tổng hợp phân tích FSR cả hai chân + symmetry index lực."""
    # Kiểm tra có dữ liệu FSR không
    if all(r.left_force_2 is None for r in readings):
        return None

    left  = _fsr_foot_stats(readings, "left_force_1",  "left_force_2",  "phase_left")
    right = _fsr_foot_stats(readings, "right_force_1", "right_force_2", "phase_right")

    if left is None and right is None:
        return None

    symmetry: dict = {}
    if left and right:
        lh = left.get("heel",  {}).get("peak_mean")
        rh = right.get("heel", {}).get("peak_mean")
        lt = left.get("toe",   {}).get("peak_mean")
        rt = right.get("toe",  {}).get("peak_mean")
        si_heel = _symmetry_index(lh, rh)
        si_toe  = _symmetry_index(lt, rt)
        if si_heel is not None:
            symmetry["heel_si"] = round(si_heel, 1)
        if si_toe is not None:
            symmetry["toe_si"] = round(si_toe, 1)

    return {
        "left":     left,
        "right":    right,
        "symmetry": symmetry or None,
        "note":     "ADC 0-1023. Loading rate: ADC/ms tại thời điểm gót tiếp đất.",
    }


# ---------------------------------------------------------------------------
# Double support — cả hai chân cùng tiếp đất
# ---------------------------------------------------------------------------

def _double_support(
    contact_left: List[GaitPhase],
    contact_right: List[GaitPhase],
    timestamps_ms: List[float],
) -> Optional[dict]:
    """Tỷ lệ thời gian cả hai chân cùng tiếp đất (double support).

    Dùng pha tiếp xúc toàn chân (max(heel, toe)) — bao gồm cả
    Pre-Swing (BAC 5) khi gót đã nhấc nhưng mũi vẫn còn đẩy đất.
    Bình thường ở người trưởng thành: ~20-25% gait cycle.
    Tỷ lệ cao → đi chậm, mất thăng bằng, bệnh lý.
    """
    n = min(len(contact_left), len(contact_right), len(timestamps_ms))
    if n == 0:
        return None

    ts = timestamps_ms[:n]
    ds_mask = [
        contact_left[i] == GaitPhase.stance and contact_right[i] == GaitPhase.stance
        for i in range(n)
    ]
    ds_count = sum(ds_mask)
    ratio = ds_count / n

    bouts_ms: list = []
    start_ms = None
    for i, ds in enumerate(ds_mask):
        if ds and start_ms is None:
            start_ms = ts[i]
        elif not ds and start_ms is not None:
            bouts_ms.append(ts[i] - start_ms)
            start_ms = None
    if start_ms is not None:
        bouts_ms.append(ts[-1] - start_ms)

    result: dict = {
        "ratio":     round(ratio, 3),
        "ratio_pct": round(ratio * 100, 1),
        "n_bouts":   len(bouts_ms),
    }
    if bouts_ms:
        result["avg_duration_ms"] = round(float(np.mean(bouts_ms)), 1)
        result["std_duration_ms"] = round(float(np.std(bouts_ms)),  1)

    return result


# ---------------------------------------------------------------------------
# Pelvic sway from spine accelerometer
# ---------------------------------------------------------------------------

def _axis_sway_stats(arr: np.ndarray) -> dict:
    """Mean/std/RMS/peak-to-peak for one accel axis. RMS is AC-coupled
    (DC component — gravity for the z-axis — removed)."""
    ac = arr - arr.mean()
    return {
        "mean":       round(float(arr.mean()), 4),
        "std":        round(float(ac.std()), 4),
        "rms":        round(float(np.sqrt((ac ** 2).mean())), 4),
        "range_p2p":  round(float(arr.max() - arr.min()), 4),
        "n_samples":  int(arr.size),
    }


def _pelvis_sway_stats(readings: List[SensorReading]) -> Optional[dict]:
    """Aggregate accelerometer statistics across a session."""
    ax = _safe_array([r.accel_x for r in readings])
    ay = _safe_array([r.accel_y for r in readings])
    az = _safe_array([r.accel_z for r in readings])

    if ax.size == 0 and ay.size == 0 and az.size == 0:
        return None

    return {
        "x_mediolateral":     _axis_sway_stats(ax) if ax.size else None,
        "y_anteroposterior":  _axis_sway_stats(ay) if ay.size else None,
        "z_vertical":         _axis_sway_stats(az) if az.size else None,
        "primary_axis":       "z_vertical",
        "note": (
            "RMS được tính sau khi loại bỏ thành phần DC. Đơn vị theo Arduino "
            "gửi (m/s² hoặc g). z_vertical là chỉ số chính phản ánh độ lệch "
            "hông lên xuống — RMS cao = đi không ổn định / mất thăng bằng."
        ),
    }


def _pelvis_gyro_stats(readings: List[SensorReading]) -> Optional[dict]:
    """Aggregate gyroscope statistics across a session."""
    gx = _safe_array([r.gyro_x for r in readings])
    gy = _safe_array([r.gyro_y for r in readings])
    gz = _safe_array([r.gyro_z for r in readings])

    if gx.size == 0 and gy.size == 0 and gz.size == 0:
        return None

    return {
        "x_roll":   _axis_sway_stats(gx) if gx.size else None,
        "y_pitch":  _axis_sway_stats(gy) if gy.size else None,
        "z_yaw":    _axis_sway_stats(gz) if gz.size else None,
        "note": (
            "Tốc độ góc quay (deg/s). RMS cao = chuyển động xoay không ổn định."
        ),
    }


def _magn_stats(readings: List[SensorReading]) -> Optional[dict]:
    """Aggregate magnetometer statistics across a session.

    Tính heading (góc hướng đi so với Bắc từ) từ magn_x và magn_y.
    """
    mx = _safe_array([r.magn_x for r in readings])
    my = _safe_array([r.magn_y for r in readings])
    mz = _safe_array([r.magn_z for r in readings])

    if mx.size == 0 and my.size == 0 and mz.size == 0:
        return None

    result: dict = {
        "x": _axis_sway_stats(mx) if mx.size else None,
        "y": _axis_sway_stats(my) if my.size else None,
        "z": _axis_sway_stats(mz) if mz.size else None,
        "note": "Từ trường (μT hoặc raw ADC). Dùng để xác định hướng đi.",
    }

    # Tính heading nếu có cả X và Y
    if mx.size and my.size and mx.size == my.size:
        headings_deg = np.degrees(np.arctan2(my, mx)) % 360.0
        result["heading"] = {
            "mean_deg":    round(float(np.mean(headings_deg)), 1),
            "std_deg":     round(float(np.std(headings_deg)), 1),
            "range_p2p":   round(float(headings_deg.max() - headings_deg.min()), 1),
            "n_samples":   int(headings_deg.size),
        }

    return result


# ---------------------------------------------------------------------------
# Score & remarks
# ---------------------------------------------------------------------------

def _gait_score_breakdown(
    lh_stats, lk_stats,
    rh_stats, rk_stats,
    si_hip, si_knee,
) -> dict:
    """Chi tiết cách tính Điểm đánh giá (gait_score): 100 điểm khởi đầu,
    trừ dần theo độ lệch ROM 4 khớp so với chuẩn và độ mất đối xứng (SI)
    hông/gối. Trả về từng thành phần để hiển thị lên FE."""
    base = 100.0
    items: list = []

    def rom_penalty(stats, joint: str, label: str):
        norm_rom = NORMS[joint]["rom"]
        if stats is None:
            penalty = 15.0
            rom_value = None
        else:
            rom_value = stats["rom"]
            penalty = min(abs(rom_value - norm_rom) / 2.0, 15.0)
        items.append({
            "label":       f"ROM {label}",
            "penalty":     round(penalty, 1),
            "max_penalty": 15.0,
            "value":       round(rom_value, 1) if rom_value is not None else None,
            "norm":        norm_rom,
            "unit":        "deg",
            "formula":     "min(|ROM đo - ROM chuẩn| / 2, 15)",
        })
        return penalty

    p1 = rom_penalty(lh_stats, "hip",  "Hông trái")
    p2 = rom_penalty(lk_stats, "knee", "Gối trái")
    p3 = rom_penalty(rh_stats, "hip",  "Hông phải")
    p4 = rom_penalty(rk_stats, "knee", "Gối phải")

    def si_penalty(si: Optional[float], label: str):
        if si is None:
            penalty = 5.0
        else:
            penalty = min(si / 10.0, 10.0)
        items.append({
            "label":       f"Đối xứng (SI) {label}",
            "penalty":     round(penalty, 1),
            "max_penalty": 10.0,
            "value":       round(si, 1) if si is not None else None,
            "norm":        0.0,
            "unit":        "%",
            "formula":     "min(SI / 10, 10)",
        })
        return penalty

    p5 = si_penalty(si_hip,  "hông")
    p6 = si_penalty(si_knee, "gối")

    total_penalty = p1 + p2 + p3 + p4 + p5 + p6
    score = round(max(0.0, base - total_penalty), 1)

    return {
        "base_score":    base,
        "total_penalty": round(total_penalty, 1),
        "final_score":   score,
        "items":         items,
    }


def _gait_score(
    lh_stats, lk_stats,
    rh_stats, rk_stats,
    si_hip, si_knee,
) -> float:
    return _gait_score_breakdown(
        lh_stats, lk_stats, rh_stats, rk_stats, si_hip, si_knee,
    )["final_score"]


def _build_remarks(
    lh, lk, rh, rk,
    si_hip, si_knee,
    lgait, rgait,
    sway,
    magn=None,
    fsr=None,
    ds=None,
) -> str:
    lines = []

    def rom_remark(stats, side: str, joint: str):
        if stats is None:
            return
        norm = NORMS[joint]["rom"]
        rom = stats["rom"]
        if rom < norm * 0.7:
            lines.append(f"{side} {joint} ROM thấp ({rom:.1f}° vs norm {norm:.0f}°) — khả năng co cứng khớp.")
        elif rom > norm * 1.3:
            lines.append(f"{side} {joint} ROM cao ({rom:.1f}° vs norm {norm:.0f}°) — kiểm tra sự ổn định dây chằng.")

    rom_remark(lh, "Trái", "hip")
    rom_remark(lk, "Trái", "knee")
    rom_remark(rh, "Phải", "hip")
    rom_remark(rk, "Phải", "knee")

    def si_remark(si: Optional[float], joint: str):
        if si is None:
            return
        if si > 15:
            lines.append(f"Mất cân xứng khớp {joint} đáng kể (SI={si:.1f}%) — cần đánh giá thêm.")
        elif si > 8:
            lines.append(f"Khớp {joint} có xu hướng mất cân xứng nhẹ (SI={si:.1f}%).")

    si_remark(si_hip, "hông")
    si_remark(si_knee, "gối")

    if lgait and rgait:
        diff = abs(lgait["cadence_steps_per_min"] - rgait["cadence_steps_per_min"])
        if diff > 5:
            lines.append(f"Nhịp bước hai chân chênh lệch {diff:.1f} bước/phút.")

    # Pelvic vertical sway interpretation (qualitative — no published threshold here)
    if sway and sway.get("z_vertical"):
        z_rms = sway["z_vertical"]["rms"]
        if z_rms > 2.5:
            lines.append(
                f"Độ lệch hông theo phương đứng cao (RMS={z_rms:.2f}) — "
                "đi không ổn định, có thể mất thăng bằng."
            )

    # Magnetometer heading deviation
    if magn and magn.get("heading"):
        h_std = magn["heading"]["std_deg"]
        if h_std > 30:
            lines.append(
                f"Hướng đi biến động lớn (std={h_std:.1f}°) — "
                "người dùng có thể đi không thẳng hướng."
            )

    # FSR — force symmetry
    if fsr and fsr.get("symmetry"):
        si_h = fsr["symmetry"].get("heel_si")
        si_t = fsr["symmetry"].get("toe_si")
        if si_h is not None and si_h > 15:
            lines.append(f"Lực tiếp đất gót chân mất cân xứng (SI={si_h:.1f}%) — tải lực không đều hai chân.")
        if si_t is not None and si_t > 15:
            lines.append(f"Lực đẩy mũi chân mất cân xứng (SI={si_t:.1f}%) — push-off không đều.")

    # Double support
    if ds is not None:
        pct = ds["ratio_pct"]
        if pct > 35:
            lines.append(f"Thời gian chống 2 chân cao ({pct:.1f}%) — dấu hiệu đi chậm hoặc mất thăng bằng.")
        elif pct < 10:
            lines.append(f"Thời gian chống 2 chân thấp ({pct:.1f}%) — cần kiểm tra lại dữ liệu pha.")

    if not lines:
        lines.append("Các thông số trong ngưỡng bình thường. Không phát hiện bất thường rõ ràng.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def analyze_session(session_id: int, readings: List[SensorReading]) -> GaitAnalysis:
    """Given a list of SensorReading ORM objects for a session,
    compute all metrics and return a (unsaved) GaitAnalysis instance."""
    if not readings:
        return GaitAnalysis(
            session_id=session_id,
            remarks="Không có dữ liệu đo lường.",
            gait_score=0.0,
        )

    readings = sorted(readings, key=lambda r: r.timestamp_ms)
    ts = [r.timestamp_ms for r in readings]

    # Joint angle arrays
    lh = _safe_array([r.left_hip   for r in readings])
    lk = _safe_array([r.left_knee  for r in readings])
    rh = _safe_array([r.right_hip  for r in readings])
    rk = _safe_array([r.right_knee for r in readings])

    lh_stats = _joint_stats(lh)
    lk_stats = _joint_stats(lk)
    rh_stats = _joint_stats(rh)
    rk_stats = _joint_stats(rk)

    # Gait cycles — adaptive phases từ tín hiệu lực gót (heel force)
    # Gót là sensor chính cho heel-strike detection (BAC 1)
    left_heel_f  = np.array([r.left_force_2  or 0.0 for r in readings], dtype=float)
    right_heel_f = np.array([r.right_force_2 or 0.0 for r in readings], dtype=float)
    phases_left  = _adaptive_phases(left_heel_f,  [r.phase_left  for r in readings])
    phases_right = _adaptive_phases(right_heel_f, [r.phase_right for r in readings])
    lgait = _gait_cycle_metrics(phases_left,  ts)
    rgait = _gait_cycle_metrics(phases_right, ts)

    # Double support: dùng toàn chân (heel OR toe) — BAC 5 (Pre-Swing)
    # gót đã nhấc nhưng mũi vẫn còn đẩy đất → cần tính vào double support
    left_toe_f   = np.array([r.left_force_1  or 0.0 for r in readings], dtype=float)
    right_toe_f  = np.array([r.right_force_1 or 0.0 for r in readings], dtype=float)
    contact_left  = _adaptive_phases(
        np.maximum(left_heel_f,  left_toe_f),
        [r.phase_left  for r in readings],
    )
    contact_right = _adaptive_phases(
        np.maximum(right_heel_f, right_toe_f),
        [r.phase_right for r in readings],
    )

    # Symmetry
    si_hip = _symmetry_index(
        lh_stats["rom"] if lh_stats else None,
        rh_stats["rom"] if rh_stats else None,
    )
    si_knee = _symmetry_index(
        lk_stats["rom"] if lk_stats else None,
        rk_stats["rom"] if rk_stats else None,
    )

    # IMU stats
    sway = _pelvis_sway_stats(readings)
    gyro = _pelvis_gyro_stats(readings)
    magn = _magn_stats(readings)

    # FSR force analysis
    fsr = _fsr_stats(readings)
    ds  = _double_support(contact_left, contact_right, ts)

    score_breakdown = _gait_score_breakdown(
        lh_stats, lk_stats,
        rh_stats, rk_stats,
        si_hip, si_knee,
    )
    score = score_breakdown["final_score"]

    remarks = _build_remarks(
        lh_stats, lk_stats,
        rh_stats, rk_stats,
        si_hip, si_knee,
        lgait, rgait,
        sway,
        magn,
        fsr,
        ds,
    )

    return GaitAnalysis(
        session_id=session_id,
        left_hip_stats=lh_stats,
        left_knee_stats=lk_stats,
        right_hip_stats=rh_stats,
        right_knee_stats=rk_stats,
        left_gait_cycle=lgait,
        right_gait_cycle=rgait,
        symmetry_index_hip=si_hip,
        symmetry_index_knee=si_knee,
        pelvis_sway_stats=sway,
        pelvis_gyro_stats=gyro,
        magn_stats=magn,
        fsr_stats=fsr,
        double_support=ds,
        gait_score=score,
        score_breakdown=score_breakdown,
        remarks=remarks,
    )
