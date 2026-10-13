"""
Serial Reader Service
=====================
Reads sensor data from a COM port in a background thread and:
  1. Parses each line into a SensorReadingIn
  2. Persists it to the DB
  3. Broadcasts it over WebSocket to all connected clients for that session

Expected serial data format — 18 fields, comma-separated:

   0: timestamp_ms    ms từ millis()
   1: left_hip        Deg (A0)
   2: left_knee       Deg (A1)
   3: right_hip       Deg (A2)
   4: right_knee      Deg (A3)
   5: left_force_1    ADC (A4)
   6: left_force_2    ADC (A5)
   7: right_force_1   ADC (A6)
   8: right_force_2   ADC (A7)
   9: accel_x         Gia tốc X  (I2C sda_20, scl_21)
  10: accel_y         Gia tốc Y
  11: accel_z         Gia tốc Z
  12: gyro_x          Vận tốc góc X
  13: gyro_y          Vận tốc góc Y
  14: gyro_z          Vận tốc góc Z
  15: magn_x          Từ trường X
  16: magn_y          Từ trường Y
  17: magn_z          Từ trường Z

Example (minimum 18 fields):
  1234,12.3,-5.6,11.1,-4.5,512,498,510,505,0.02,-0.04,9.81,0.5,-0.3,0.1,230,120,45

Auto-computed phase: BE derives stance/swing from average of the two force
sensors per foot (avg > FORCE_STANCE_THRESHOLD → stance).
"""
import asyncio
import glob
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Set

import serial
import serial.tools.list_ports

from app.schemas import SensorReadingIn, RealtimeMessage
from app.models import GaitPhase, SessionStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WebSocket connection manager (shared across the app)
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages active WebSocket connections keyed by session_id."""

    def __init__(self):
        self._connections: Dict[int, Set] = {}

    async def connect(self, session_id: int, websocket):
        await websocket.accept()
        self._connections.setdefault(session_id, set()).add(websocket)
        logger.info("WS client connected to session %s", session_id)

    def disconnect(self, session_id: int, websocket):
        if session_id in self._connections:
            self._connections[session_id].discard(websocket)
        logger.info("WS client disconnected from session %s", session_id)

    async def broadcast(self, session_id: int, message: dict):
        """Send JSON message to all clients subscribed to session_id."""
        connections = list(self._connections.get(session_id, []))
        dead = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections[session_id].discard(ws)


ws_manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Phase detection from raw FSR force
# ---------------------------------------------------------------------------

# Ngưỡng ADC để xác định gait phase từ FSR (trung bình 2 cảm biến/chân).
# Arduino ADC 10-bit: 0-1023. Stance khi trung bình > 300, swing khi < 100.
FORCE_STANCE_THRESHOLD = 300.0
FORCE_SWING_THRESHOLD  = 100.0


def _phase_from_force(force: float) -> GaitPhase:
    """Suy ra gait phase từ lực FSR trung bình. Vùng giữa 2 ngưỡng = unknown
    để tránh flickering quanh điểm chuyển pha."""
    if force >= FORCE_STANCE_THRESHOLD:
        return GaitPhase.stance
    if force <= FORCE_SWING_THRESHOLD:
        return GaitPhase.swing
    return GaitPhase.unknown


def _avg_force(toe: Optional[float], heel: Optional[float]) -> Optional[float]:
    """Trung bình mũi chân + gót chân, bỏ qua None."""
    vals = [v for v in (toe, heel) if v is not None]
    return sum(vals) / len(vals) if vals else None


# ---------------------------------------------------------------------------
# Sensor packet parser
# ---------------------------------------------------------------------------

def parse_line(line: str, session_start_ms: float) -> Optional[SensorReadingIn]:
    """
    Parse a single serial line into SensorReadingIn.
    Returns None if the line is malformed.
    """
    line = line.strip()
    if not line or line.startswith("#"):   # skip comments / empty lines
        return None

    parts = line.split(",")
    if len(parts) < 18:
        logger.debug("Short line ignored (need 18 fields): %r", line)
        return None

    def _f(token: str) -> Optional[float]:
        t = token.strip()
        if t in ("", "nan", "NaN", "NAN"):
            return None
        try:
            return float(t)
        except ValueError:
            return None

    try:
        timestamp_ms  = float(parts[0])
        left_hip      = _f(parts[1])
        left_knee     = _f(parts[2])
        right_hip     = _f(parts[3])
        right_knee    = _f(parts[4])
        left_force_1  = _f(parts[5])
        left_force_2  = _f(parts[6])
        right_force_1 = _f(parts[7])
        right_force_2 = _f(parts[8])
        accel_x       = _f(parts[9])
        accel_y       = _f(parts[10])
        accel_z       = _f(parts[11])
        gyro_x        = _f(parts[12])
        gyro_y        = _f(parts[13])
        gyro_z        = _f(parts[14])
        magn_x        = _f(parts[15])
        magn_y        = _f(parts[16])
        magn_z        = _f(parts[17])

        # Phase detection: dùng gót chân (force_2) vì heel strike là điểm chuyển pha chính.
        # Nếu gót không có dữ liệu thì fallback sang trung bình cả hai.
        left_heel  = left_force_2  if left_force_2  is not None else _avg_force(left_force_1,  left_force_2)
        right_heel = right_force_2 if right_force_2 is not None else _avg_force(right_force_1, right_force_2)
        phase_left  = _phase_from_force(left_heel  or 0.0)
        phase_right = _phase_from_force(right_heel or 0.0)

        return SensorReadingIn(
            timestamp_ms=timestamp_ms,
            left_hip=left_hip,
            left_knee=left_knee,
            right_hip=right_hip,
            right_knee=right_knee,
            left_force_1=left_force_1,
            left_force_2=left_force_2,
            right_force_1=right_force_1,
            right_force_2=right_force_2,
            accel_x=accel_x,
            accel_y=accel_y,
            accel_z=accel_z,
            gyro_x=gyro_x,
            gyro_y=gyro_y,
            gyro_z=gyro_z,
            magn_x=magn_x,
            magn_y=magn_y,
            magn_z=magn_z,
            phase_left=phase_left,
            phase_right=phase_right,
        )
    except (ValueError, IndexError) as exc:
        logger.debug("Parse error on %r: %s", line, exc)
        return None


# ---------------------------------------------------------------------------
# Per-session reader (runs in its own thread)
# ---------------------------------------------------------------------------

class SerialReaderThread(threading.Thread):
    """
    Background thread that:
    - Opens the COM port
    - Reads lines, broadcasts via WebSocket (always)
    - Saves to DB only when record_flag is set
    """

    def __init__(
        self,
        session_id: int,
        com_port: str,
        baud_rate: int,
        db_factory,       # callable() -> SQLAlchemy Session
        loop: asyncio.AbstractEventLoop,
        record: bool = False,
    ):
        super().__init__(daemon=True, name=f"serial-{session_id}")
        self.session_id = session_id
        self.com_port = com_port
        self.baud_rate = baud_rate
        self.db_factory = db_factory
        self.loop = loop
        self._stop_event = threading.Event()
        self._record_flag = threading.Event()
        if record:
            self._record_flag.set()
        self.samples_received = 0
        self._serial: Optional[serial.Serial] = None

    def stop(self):
        self._stop_event.set()
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass

    def run(self):
        from app import models  # local import to avoid circular deps

        logger.info("Opening %s @ %d baud for session %s",
                    self.com_port, self.baud_rate, self.session_id)
        try:
            self._serial = serial.Serial(
                self.com_port,
                self.baud_rate,
                timeout=1.0,
            )
        except serial.SerialException as exc:
            logger.error("Cannot open %s: %s", self.com_port, exc)
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast(self.session_id, {
                    "type": "error",
                    "session_id": self.session_id,
                    "data": {"message": f"Cannot open port: {exc}"},
                }),
                self.loop,
            )
            return

        session_start_ms = time.monotonic() * 1000.0

        while not self._stop_event.is_set():
            try:
                raw = self._serial.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace")
            except serial.SerialException as exc:
                logger.error("Serial read error: %s", exc)
                break

            reading = parse_line(line, session_start_ms)
            if reading is None:
                continue

            self.samples_received += 1

            # Persist to DB — chỉ khi đang recording
            if not self._record_flag.is_set():
                asyncio.run_coroutine_threadsafe(
                    ws_manager.broadcast(self.session_id, {
                        "type": "reading",
                        "session_id": self.session_id,
                        "data": reading.model_dump(),
                    }),
                    self.loop,
                )
                continue

            db = self.db_factory()
            try:
                db_reading = models.SensorReading(
                    session_id=self.session_id,
                    timestamp_ms=reading.timestamp_ms,
                    left_hip=reading.left_hip,
                    left_knee=reading.left_knee,
                    right_hip=reading.right_hip,
                    right_knee=reading.right_knee,
                    left_force_1=reading.left_force_1,
                    left_force_2=reading.left_force_2,
                    right_force_1=reading.right_force_1,
                    right_force_2=reading.right_force_2,
                    accel_x=reading.accel_x,
                    accel_y=reading.accel_y,
                    accel_z=reading.accel_z,
                    gyro_x=reading.gyro_x,
                    gyro_y=reading.gyro_y,
                    gyro_z=reading.gyro_z,
                    magn_x=reading.magn_x,
                    magn_y=reading.magn_y,
                    magn_z=reading.magn_z,
                    phase_left=reading.phase_left,
                    phase_right=reading.phase_right,
                    signal_quality=reading.signal_quality,
                )
                db.add(db_reading)
                db.commit()
            except Exception as exc:
                logger.error("DB write error: %s", exc)
                db.rollback()
            finally:
                db.close()

            # Broadcast via WebSocket (non-blocking)
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast(self.session_id, {
                    "type": "reading",
                    "session_id": self.session_id,
                    "data": reading.model_dump(),
                }),
                self.loop,
            )

        if self._serial and self._serial.is_open:
            self._serial.close()
        logger.info("Serial reader stopped for session %s (%d samples)",
                    self.session_id, self.samples_received)


# ---------------------------------------------------------------------------
# Reader registry (one reader per active session)
# ---------------------------------------------------------------------------

class SerialReaderRegistry:
    """Singleton that tracks all running reader threads."""

    def __init__(self):
        self._readers: Dict[int, SerialReaderThread] = {}
        self._lock = threading.Lock()

    def is_running(self, session_id: int) -> bool:
        with self._lock:
            reader = self._readers.get(session_id)
            return reader is not None and reader.is_alive()

    def get_status(self, session_id: int) -> dict:
        with self._lock:
            reader = self._readers.get(session_id)
        if reader is None:
            return {"connected": False, "com_port": None, "baud_rate": None, "samples_received": 0}
        return {
            "connected": reader.is_alive(),
            "com_port": reader.com_port,
            "baud_rate": reader.baud_rate,
            "samples_received": reader.samples_received,
        }

    def start(
        self,
        session_id: int,
        com_port: str,
        baud_rate: int,
        db_factory,
        loop: asyncio.AbstractEventLoop,
        record: bool = False,
    ) -> SerialReaderThread:
        with self._lock:
            if session_id in self._readers and self._readers[session_id].is_alive():
                raise RuntimeError(f"Session {session_id} already has an active reader")
            reader = SerialReaderThread(session_id, com_port, baud_rate, db_factory, loop, record=record)
            self._readers[session_id] = reader
        reader.start()
        return reader

    def set_recording(self, session_id: int, recording: bool) -> None:
        with self._lock:
            reader = self._readers.get(session_id)
            if reader:
                if recording:
                    reader._record_flag.set()
                else:
                    reader._record_flag.clear()

    def stop(self, session_id: int):
        with self._lock:
            reader = self._readers.pop(session_id, None)
        if reader:
            reader.stop()
            reader.join(timeout=3.0)

    def stop_all(self):
        with self._lock:
            readers = list(self._readers.items())
            self._readers.clear()
        for sid, reader in readers:
            reader.stop()
            reader.join(timeout=3.0)


serial_registry = SerialReaderRegistry()


# ---------------------------------------------------------------------------
# List available ports (utility)
# ---------------------------------------------------------------------------

def list_serial_ports() -> list[dict]:
    ports = serial.tools.list_ports.comports()
    return [
        {"port": p.device, "description": p.description, "hwid": p.hwid}
        for p in sorted(ports, key=lambda p: p.device)
    ]


def auto_detect_ch340() -> Optional[dict]:
    """
    Tự động phát hiện thiết bị CH340/CH343 (QinHeng Electronics).
    Trả về thông tin port đầu tiên tìm thấy, hoặc None nếu không có.

    VID: 1A86 (QinHeng Electronics)
    - PID 7523: CH340 → /dev/ttyUSB*
    - PID 55d3: CH343 → /dev/ttyCH343USB* (WCH driver) hoặc /dev/ttyACM*
    """
    QINHENG_PIDS = {"1a86:7523", "1a86:55d3", "1a86:5523", "1a86:55d4"}

    # 1. Ưu tiên: tìm /dev/ttyCH343USB* (WCH ch343 driver tạo node riêng,
    #    pyserial không scan được pattern này)
    for dev in sorted(glob.glob("/dev/ttyCH343USB*")):
        logger.info("CH343 detected at %s (ttyCH343USB glob)", dev)
        return {
            "port": dev,
            "description": "USB Single Serial (CH343)",
            "hwid": "USB VID:PID=1A86:55D3",
            "detected_by": "ttyCH343USB_glob"
        }

    # 2. Fallback: pyserial scan ttyUSB* / ttyACM* / ttyS*
    for p in serial.tools.list_ports.comports():
        hwid_lower = p.hwid.lower()
        desc_lower = p.description.lower()

        for vid_pid in QINHENG_PIDS:
            if f"vid:pid={vid_pid}" in hwid_lower:
                logger.info("QinHeng device detected at %s (VID:PID=%s)", p.device, vid_pid)
                return {
                    "port": p.device,
                    "description": p.description,
                    "hwid": p.hwid,
                    "detected_by": "vid_pid"
                }

        if "ch340" in desc_lower or "ch343" in desc_lower or "usb-serial ch34" in desc_lower:
            logger.info("QinHeng device detected at %s (description match)", p.device)
            return {
                "port": p.device,
                "description": p.description,
                "hwid": p.hwid,
                "detected_by": "description"
            }

    logger.warning("No CH340/CH343 device detected")
    return None
