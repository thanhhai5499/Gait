"""
Gait cycle detection from ankle Y-coordinate (lateral camera view).

Heel Strike (HS): ankle pixel Y reaches local maximum  → foot at lowest world point (ground contact)
Toe Off      (TO): ankle pixel Y reaches local minimum  → foot at highest world point (mid-swing)

Image-coordinate convention: Y increases downward, so
  • Foot near floor  → large Y value   (local maximum = HS)
  • Foot in the air  → small Y value   (local minimum ≈ TO / mid-swing)

Output metrics
--------------
cadence            (steps/min)   — from all HS events (both legs)
stride_time        (s)           — same-leg HS→HS interval
stance_phase_pct   (%)           — time from HS → TO as fraction of stride (~60 % normal)
swing_phase_pct    (%)           — 100 - stance_phase_pct
double_support_pct (%)           — not computed yet (requires 2-leg force or contact logic)
step_symmetry      (%)           — |L_stride − R_stride| / mean × 100  (0 = perfect)
event              str|None      — "heel_strike" | "toe_off" | None  (most recent this frame)
"""
from __future__ import annotations

import logging
from collections import deque

import numpy as np

logger = logging.getLogger(__name__)

# Body-25 keypoint indices for ankles
_KP_R_ANKLE = 11
_KP_L_ANKLE = 14


class GaitCycleDetector:
    """
    Detects gait events (HS/TO) and computes temporal gait parameters
    from ankle kinematics at ~15 Hz lateral camera stream.

    Designed to work with Kalman-smoothed keypoints from KalmanSmoother,
    which reduces pixel jitter enough to allow reliable local-extrema detection.

    Usage
    -----
    detector = GaitCycleDetector(fps=15)
    # In inference loop:
    metrics = detector.update(smoothed_keypoints, time.perf_counter())
    """

    # Peak / trough detection
    _W            = 5     # half-window in frames; confirmed extremum if center wins ±W frames
    _MIN_PROM     = 10    # px — minimum peak-to-valley prominence; filters Kalman residual noise
    # Event timing constraints
    _MIN_STEP_GAP = 0.30  # s — minimum time between same-type events on same leg
    _MIN_STRIDE   = 0.50  # s — shortest plausible stride (120 steps/min)
    _MAX_STRIDE   = 2.50  # s — longest  plausible stride (24  steps/min)

    def __init__(self, fps: float = 15.0, buffer_seconds: float = 10.0) -> None:
        self._fps    = fps
        self._maxbuf = int(fps * buffer_seconds)

        # Ankle Y-coordinate buffers (None = keypoint not detected)
        self._l_y: deque[float | None] = deque(maxlen=self._maxbuf)
        self._r_y: deque[float | None] = deque(maxlen=self._maxbuf)
        self._ts:  deque[float]        = deque(maxlen=self._maxbuf)

        # Event timestamp history (last 30 per type per leg)
        self._l_hs: deque[float] = deque(maxlen=30)
        self._r_hs: deque[float] = deque(maxlen=30)
        self._l_to: deque[float] = deque(maxlen=30)
        self._r_to: deque[float] = deque(maxlen=30)

        # "processed up to" timestamp — each time-point checked at most once
        self._l_hs_proc = float("-inf")
        self._r_hs_proc = float("-inf")
        self._l_to_proc = float("-inf")
        self._r_to_proc = float("-inf")

        self._out: dict = {
            "cadence":            None,
            "stride_time":        None,
            "stance_phase_pct":   None,
            "swing_phase_pct":    None,
            "double_support_pct": None,
            "step_symmetry":      None,
            "event":              None,
        }

    # ── Public API ─────────────────────────────────────────────────────────────

    def update(self, keypoints: list, timestamp: float) -> dict:
        """
        Process one inference frame.

        Parameters
        ----------
        keypoints : Body-25 list, each element (x, y, conf) or None
        timestamp : time.perf_counter() value at this frame

        Returns
        -------
        dict with cadence, stride_time, phase metrics, and most-recent event.
        All values are None until enough history has been collected.
        """
        l_kp = keypoints[_KP_L_ANKLE] if _KP_L_ANKLE < len(keypoints) else None
        r_kp = keypoints[_KP_R_ANKLE] if _KP_R_ANKLE < len(keypoints) else None

        self._l_y.append(float(l_kp[1]) if l_kp else None)
        self._r_y.append(float(r_kp[1]) if r_kp else None)
        self._ts.append(timestamp)

        W = self._W
        if len(self._ts) < W * 2 + 3:
            self._out["event"] = None
            return dict(self._out)

        l_arr  = self._fill_nans(np.array(list(self._l_y), dtype=float))
        r_arr  = self._fill_nans(np.array(list(self._r_y), dtype=float))
        ts_arr = np.array(list(self._ts))

        # Centre of the trailing window: W frames behind the latest frame
        cp     = len(ts_arr) - W - 1
        cp_ts  = float(ts_arr[cp])

        event: str | None = None

        # Left Heel Strike  (peak)
        if cp_ts > self._l_hs_proc + 0.04:
            self._l_hs_proc = cp_ts
            if self._is_peak(l_arr, cp):
                if not self._l_hs or cp_ts - self._l_hs[-1] >= self._MIN_STEP_GAP:
                    self._l_hs.append(cp_ts)
                    event = "heel_strike"
                    logger.debug("L-HS  t=%.3f", cp_ts)

        # Right Heel Strike (peak)
        if cp_ts > self._r_hs_proc + 0.04:
            self._r_hs_proc = cp_ts
            if self._is_peak(r_arr, cp):
                if not self._r_hs or cp_ts - self._r_hs[-1] >= self._MIN_STEP_GAP:
                    self._r_hs.append(cp_ts)
                    event = event or "heel_strike"
                    logger.debug("R-HS  t=%.3f", cp_ts)

        # Left Toe Off      (trough)
        if cp_ts > self._l_to_proc + 0.04:
            self._l_to_proc = cp_ts
            if self._is_trough(l_arr, cp):
                if not self._l_to or cp_ts - self._l_to[-1] >= self._MIN_STEP_GAP:
                    self._l_to.append(cp_ts)
                    event = event or "toe_off"
                    logger.debug("L-TO  t=%.3f", cp_ts)

        # Right Toe Off     (trough)
        if cp_ts > self._r_to_proc + 0.04:
            self._r_to_proc = cp_ts
            if self._is_trough(r_arr, cp):
                if not self._r_to or cp_ts - self._r_to[-1] >= self._MIN_STEP_GAP:
                    self._r_to.append(cp_ts)
                    event = event or "toe_off"
                    logger.debug("R-TO  t=%.3f", cp_ts)

        self._recompute(event)
        return dict(self._out)

    def reset(self) -> None:
        """Clear all history — call at session start/stop."""
        self._l_y.clear(); self._r_y.clear(); self._ts.clear()
        self._l_hs.clear(); self._r_hs.clear()
        self._l_to.clear(); self._r_to.clear()
        self._l_hs_proc = self._r_hs_proc = float("-inf")
        self._l_to_proc = self._r_to_proc = float("-inf")
        for k in self._out:
            self._out[k] = None

    # ── Signal analysis ────────────────────────────────────────────────────────

    @staticmethod
    def _fill_nans(arr: np.ndarray) -> np.ndarray:
        """Forward-fill NaN values (covers Kalman-predicted frames where ankle was occluded)."""
        mask = np.isnan(arr)
        if not mask.any():
            return arr
        if mask.all():
            return np.zeros_like(arr)
        idx = np.where(~mask, np.arange(len(arr)), 0)
        np.maximum.accumulate(idx, out=idx)
        return np.where(mask, arr[idx], arr)

    def _is_peak(self, arr: np.ndarray, pos: int) -> bool:
        """True if arr[pos] is the maximum in [pos-W, pos+W] with sufficient prominence."""
        W = self._W
        if pos < W or pos + W >= len(arr):
            return False
        win = arr[pos - W: pos + W + 1]
        if win[W] != win.max():
            return False
        return float(win.max() - win.min()) >= self._MIN_PROM

    def _is_trough(self, arr: np.ndarray, pos: int) -> bool:
        """True if arr[pos] is the minimum in [pos-W, pos+W] with sufficient prominence."""
        W = self._W
        if pos < W or pos + W >= len(arr):
            return False
        win = arr[pos - W: pos + W + 1]
        if win[W] != win.min():
            return False
        return float(win.max() - win.min()) >= self._MIN_PROM

    # ── Metric computation ─────────────────────────────────────────────────────

    def _recompute(self, event: str | None) -> None:
        cadence    = self._cadence()
        l_stride   = self._stride_time_for(self._l_hs)
        r_stride   = self._stride_time_for(self._r_hs)

        if l_stride and r_stride:
            stride_time = round((l_stride + r_stride) / 2.0, 3)
        else:
            stride_time = l_stride or r_stride

        stance_pct, swing_pct = self._phase_pcts()

        step_sym: float | None = None
        if l_stride and r_stride:
            avg = (l_stride + r_stride) / 2.0
            if avg > 0:
                step_sym = round(abs(l_stride - r_stride) / avg * 100.0, 1)

        self._out.update({
            "cadence":            cadence,
            "stride_time":        stride_time,
            "stance_phase_pct":   stance_pct,
            "swing_phase_pct":    swing_pct,
            "double_support_pct": None,
            "step_symmetry":      step_sym,
            "event":              event,
        })

    def _cadence(self) -> float | None:
        """
        Tính cadence thời gian thực (bước/phút), quy ước = số bước của CẢ HAI CHÂN mỗi phút.

        Công thức đang dùng: 60 / (khoảng cách thời gian trung bình giữa hai heel-strike
        XEN KẼ trái-phải liên tiếp).

        Về mặt toán học, công thức này TƯƠNG ĐƯƠNG với 120 / T_stride, trong đó T_stride là
        thời gian một chu kỳ bước đầy đủ của MỘT chân (khoảng cách giữa hai heel-strike liên
        tiếp CÙNG một chân, tương đương hai bước xen kẽ trái-phải):

            T_stride ≈ 2 × (khoảng cách heel-strike xen kẽ trái-phải)
            => 120 / T_stride ≈ 120 / [2 × khoảng cách xen kẽ] = 60 / khoảng cách xen kẽ

        Cách tính theo khoảng cách xen kẽ (đang dùng ở đây) được giữ nguyên thay vì đổi sang
        đo trực tiếp chu kỳ một chân, vì nó bền hơn khi một chân bị mất khung hình tạm thời
        (chỉ cần phát hiện được heel-strike của MỘT trong hai chân tại mỗi bước, không yêu cầu
        theo dõi liên tục cùng một chân qua nhiều chu kỳ).

        Xem thêm: docs/so_sanh_imu_camera.txt, Mục 5.3, để đối chiếu với công thức phía IMU
        (120 / T̄, T̄ đo trên một chân).
        """
        all_hs = sorted(list(self._l_hs) + list(self._r_hs))
        if len(all_hs) < 3:
            return None
        intervals = np.diff(all_hs[-12:])
        valid = intervals[(intervals >= 0.20) & (intervals <= 1.5)]
        if len(valid) < 2:
            return None
        return round(60.0 / float(np.mean(valid)), 1)

    def _stride_time_for(self, hs: deque) -> float | None:
        """Mean same-leg HS→HS interval from last 6 events."""
        lst = list(hs)
        if len(lst) < 2:
            return None
        intervals = np.diff(lst[-6:])
        valid = intervals[
            (intervals >= self._MIN_STRIDE) & (intervals <= self._MAX_STRIDE)
        ]
        return round(float(np.mean(valid)), 3) if len(valid) >= 1 else None

    def _phase_pcts(self) -> tuple[float | None, float | None]:
        """
        Estimate stance/swing ratio on the left leg.
        Stance = HS→TO interval; Swing = TO→next HS interval.
        Uses left-leg events only for consistency.
        """
        l_hs = list(self._l_hs)
        l_to = list(self._l_to)
        if len(l_hs) < 2 or not l_to:
            return None, None

        fracs: list[float] = []
        for i in range(max(0, len(l_hs) - 5), len(l_hs) - 1):
            hs_t      = l_hs[i]
            next_hs_t = l_hs[i + 1]
            stride_t  = next_hs_t - hs_t
            if not (self._MIN_STRIDE <= stride_t <= self._MAX_STRIDE):
                continue
            # First TO between this HS and the next HS
            tos = [t for t in l_to if hs_t < t < next_hs_t]
            if not tos:
                continue
            to_t = min(tos)
            fracs.append((to_t - hs_t) / stride_t)

        if not fracs:
            return None, None
        stance = round(float(np.mean(fracs)) * 100.0, 1)
        return stance, round(100.0 - stance, 1)
