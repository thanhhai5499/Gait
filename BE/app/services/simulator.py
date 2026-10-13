"""
Gait Data Simulator
===================
Sinh dữ liệu giả lập hai chân (6 khớp) theo đường sin/cos
mô phỏng chu kỳ bước đi bình thường, sau đó:
  1. Broadcast qua WebSocket (luôn luôn)
  2. Lưu vào DB (chỉ khi đang ở chế độ recording)

Dùng để test UI/dashboard mà không cần cảm biến vật lý.
"""
import asyncio
import logging
import math
import random
import threading
import time
from typing import Dict

from app.models import SensorReading, GaitPhase
from app.services.serial_reader import ws_manager
from app.database import SessionLocal

logger = logging.getLogger(__name__)

GAIT_PERIOD_S = 1.1   # giây / chu kỳ
SAMPLE_RATE_HZ = 50   # Hz


def _generate(t_s: float) -> dict:
    w = 2 * math.pi / GAIT_PERIOD_S
    n = lambda: random.gauss(0, 0.6)

    lh = 20 * math.sin(w * t_s) + 10 + n()
    lk = 55 * max(0.0, math.sin(w * t_s - 0.4)) + n()

    rh = 20 * math.sin(w * t_s + math.pi) + 10 + n()
    rk = 55 * max(0.0, math.sin(w * t_s + math.pi - 0.4)) + n()

    # FSR dual sensor per leg (ADC 0-1023) — peak ~800 khi stance
    f_scale = 600 + 300 * math.sin(w * t_s)
    fL1 = max(0.0, f_scale + random.gauss(0, 8)) if math.sin(w * t_s) > 0 else random.gauss(30, 5)
    fL2 = max(0.0, f_scale * 0.95 + random.gauss(0, 8)) if math.sin(w * t_s) > 0 else random.gauss(28, 5)
    f_scale_r = 600 + 300 * math.sin(w * t_s + math.pi)
    fR1 = max(0.0, f_scale_r + random.gauss(0, 8)) if math.sin(w * t_s + math.pi) > 0 else random.gauss(30, 5)
    fR2 = max(0.0, f_scale_r * 0.95 + random.gauss(0, 8)) if math.sin(w * t_s + math.pi) > 0 else random.gauss(28, 5)

    # IMU accelerometer (m/s²)
    ax = 0.5 * math.sin(w * t_s) + random.gauss(0, 0.1)
    ay = 0.3 * math.cos(w * t_s) + random.gauss(0, 0.1)
    az = 9.81 + 0.8 * math.sin(2 * w * t_s) + random.gauss(0, 0.15)

    # IMU gyroscope (deg/s)
    gx = 5  * math.cos(w * t_s)     + random.gauss(0, 1)
    gy = 3  * math.sin(w * t_s)     + random.gauss(0, 1)
    gz = 2  * math.sin(2 * w * t_s) + random.gauss(0, 1)

    # IMU magnetometer (μT)
    mx = 230 + random.gauss(0, 5)
    my = 120 + random.gauss(0, 5)
    mz = 45  + random.gauss(0, 3)

    # Phase từ gót chân (fL2 = gót trái, fR2 = gót phải)
    phase_l = GaitPhase.stance if fL2 > 300 else (GaitPhase.swing if fL2 < 100 else GaitPhase.unknown)
    phase_r = GaitPhase.stance if fR2 > 300 else (GaitPhase.swing if fR2 < 100 else GaitPhase.unknown)

    return {
        "left_hip":      round(lh, 2),
        "left_knee":     round(lk, 2),
        "right_hip":     round(rh, 2),
        "right_knee":    round(rk, 2),
        "left_force_1":  round(fL1, 1),
        "left_force_2":  round(fL2, 1),
        "right_force_1": round(fR1, 1),
        "right_force_2": round(fR2, 1),
        "accel_x":       round(ax, 3),
        "accel_y":       round(ay, 3),
        "accel_z":       round(az, 3),
        "gyro_x":        round(gx, 3),
        "gyro_y":        round(gy, 3),
        "gyro_z":        round(gz, 3),
        "magn_x":        round(mx, 2),
        "magn_y":        round(my, 2),
        "magn_z":        round(mz, 2),
        "phase_left":    phase_l,
        "phase_right":   phase_r,
        "signal_quality": 100,
    }


class GaitSimulator:

    def __init__(self):
        self._threads: Dict[int, threading.Thread] = {}
        self._stop_flags: Dict[int, threading.Event] = {}
        self._record_flags: Dict[int, threading.Event] = {}

    def start(self, session_id: int, loop: asyncio.AbstractEventLoop, record: bool = False) -> None:
        if session_id in self._threads and self._threads[session_id].is_alive():
            raise RuntimeError(f"Simulator already running for session {session_id}")

        stop_flag = threading.Event()
        record_flag = threading.Event()
        if record:
            record_flag.set()

        self._stop_flags[session_id] = stop_flag
        self._record_flags[session_id] = record_flag

        t = threading.Thread(
            target=self._run,
            args=(session_id, loop, stop_flag, record_flag),
            daemon=True,
            name=f"gait-sim-{session_id}",
        )
        self._threads[session_id] = t
        t.start()
        logger.info("Simulator started for session %s (record=%s)", session_id, record)

    def set_recording(self, session_id: int, recording: bool) -> None:
        flag = self._record_flags.get(session_id)
        if flag:
            if recording:
                flag.set()
            else:
                flag.clear()
            logger.info("Simulator session %s recording=%s", session_id, recording)

    def stop(self, session_id: int) -> None:
        flag = self._stop_flags.pop(session_id, None)
        if flag:
            flag.set()
        self._threads.pop(session_id, None)
        self._record_flags.pop(session_id, None)
        logger.info("Simulator stopped for session %s", session_id)

    def is_running(self, session_id: int) -> bool:
        t = self._threads.get(session_id)
        return t is not None and t.is_alive()

    def _run(self, session_id: int, loop: asyncio.AbstractEventLoop,
             stop_flag: threading.Event, record_flag: threading.Event):
        dt = 1.0 / SAMPLE_RATE_HZ
        t_ms = 0.0

        while not stop_flag.is_set():
            data = _generate(t_ms / 1000.0)

            # 1. Lưu DB — chỉ khi đang recording
            if record_flag.is_set():
                db = SessionLocal()
                try:
                    db.add(SensorReading(session_id=session_id, timestamp_ms=t_ms, **data))
                    db.commit()
                except Exception as exc:
                    logger.warning("Simulator DB write error: %s", exc)
                    db.rollback()
                finally:
                    db.close()

            # 2. Broadcast WS — luôn luôn (để xem trước)
            ws_data = {**data, "timestamp_ms": t_ms,
                       "phase_left":  data["phase_left"].value,
                       "phase_right": data["phase_right"].value}
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast(session_id, {
                    "type": "reading",
                    "session_id": session_id,
                    "data": ws_data,
                }),
                loop,
            )

            t_ms = round(t_ms + dt * 1000, 3)
            time.sleep(dt)


sim_registry = GaitSimulator()
