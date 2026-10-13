"""
Intel RealSense D435i reader.
Provides aligned RGB + Depth + IMU streams via pyrealsense2.
Falls back gracefully when pyrealsense2 is not installed.
"""
import logging
import threading
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_rs_available = False
rs = None
try:
    import pyrealsense2 as rs  # type: ignore
    _rs_available = True
    logger.info("pyrealsense2 loaded — RealSense D435i support enabled")
except ImportError:
    logger.warning("pyrealsense2 not installed — RealSense will not be available")


def is_realsense_available() -> bool:
    return _rs_available


def detect_realsense() -> Optional[dict]:
    """Return device info dict if a D435i is connected, else None."""
    if not _rs_available:
        return None
    try:
        ctx = rs.context()
        for dev in ctx.query_devices():
            name = dev.get_info(rs.camera_info.name)
            serial = dev.get_info(rs.camera_info.serial_number)
            if "D4" in name or "RealSense" in name:
                logger.info("RealSense detected: %s (s/n %s)", name, serial)
                return {
                    "index": "realsense",
                    "type":  "realsense",
                    "name":  name,
                    "serial": serial,
                    "width": 1280,
                    "height": 720,
                    "fps":   30,
                }
    except Exception as exc:
        logger.warning("RealSense detection failed: %s", exc)
    return None


class RealSenseReader:
    """
    Manages a single RealSense D435i pipeline.
    Thread-safe: call start() once, then read_frame() from any thread.
    """

    def __init__(self):
        if not _rs_available:
            raise RuntimeError("pyrealsense2 not installed")
        self._pipeline = None
        self._align    = None
        self._running  = False
        self._has_imu  = False
        self._imu_lock = threading.Lock()
        self._latest_imu: dict = {"accel": [0.0, 0.0, 0.0], "gyro": [0.0, 0.0, 0.0]}

    def start(self) -> bool:
        """Configure and start the RealSense pipeline. Returns True on success.
        Tries with IMU first; falls back to color+depth only if IMU unavailable.
        """
        for use_imu in [True, False]:
            try:
                pipeline = rs.pipeline()
                config   = rs.config()

                config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 30)
                config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 30)
                if use_imu:
                    config.enable_stream(rs.stream.accel, rs.format.motion_xyz32f, 100)
                    config.enable_stream(rs.stream.gyro,  rs.format.motion_xyz32f, 200)

                pipeline.start(config)
                self._pipeline = pipeline
                self._align    = rs.align(rs.stream.color)
                self._running  = True
                self._has_imu  = use_imu
                logger.info(
                    "RealSense pipeline started — 1280×720 RGB + depth%s",
                    " + IMU" if use_imu else " (no IMU)"
                )
                return True
            except Exception as exc:
                logger.warning("RealSense start %s IMU failed: %s", "with" if use_imu else "without", exc)

        logger.error("RealSense: all start attempts failed")
        return False

    def read_frame(self) -> Optional[dict]:
        """
        Block until the next frameset (100 ms timeout).
        Returns:
          color_frame   : np.ndarray  BGR 1280×720
          depth_raw     : np.ndarray  uint16 mm aligned to color
          depth_colormap: np.ndarray  BGR jet-colorized depth
          imu           : {"accel": [x,y,z], "gyro": [x,y,z]}
        Returns None on timeout or error.
        """
        if not self._pipeline or not self._running:
            return None
        try:
            frames = self._pipeline.wait_for_frames(timeout_ms=150)

            # Consume IMU motion frames (only when IMU was enabled at start)
            if self._has_imu:
                for frame in frames:
                    if frame.is_motion_frame():
                        m    = frame.as_motion_frame()
                        d    = m.get_motion_data()
                        prof = frame.get_profile().stream_type()
                        with self._imu_lock:
                            if prof == rs.stream.accel:
                                self._latest_imu["accel"] = [round(d.x, 3), round(d.y, 3), round(d.z, 3)]
                            elif prof == rs.stream.gyro:
                                self._latest_imu["gyro"]  = [round(d.x, 3), round(d.y, 3), round(d.z, 3)]

            aligned      = self._align.process(frames)
            color_frame  = aligned.get_color_frame()
            depth_frame  = aligned.get_depth_frame()

            if not color_frame or not depth_frame:
                return None

            color_img = np.asanyarray(color_frame.get_data())   # BGR
            depth_raw = np.asanyarray(depth_frame.get_data())   # uint16 mm

            depth_colormap = cv2.applyColorMap(
                cv2.convertScaleAbs(depth_raw, alpha=0.04),
                cv2.COLORMAP_JET,
            )

            with self._imu_lock:
                imu = {"accel": list(self._latest_imu["accel"]),
                       "gyro":  list(self._latest_imu["gyro"])}

            return {
                "color_frame":    color_img,
                "depth_raw":      depth_raw,
                "depth_colormap": depth_colormap,
                "imu":            imu,
            }
        except Exception as exc:
            logger.warning("RealSense read error: %s", exc)
            return None

    def get_intrinsics(self) -> Optional[dict]:
        """
        Return color stream intrinsics for 3D back-projection.
        Returns dict {fx, fy, cx, cy} or None if pipeline not started.
        """
        if not self._pipeline or not self._running:
            return None
        try:
            profile       = self._pipeline.get_active_profile()
            color_profile = profile.get_stream(rs.stream.color).as_video_stream_profile()
            intr          = color_profile.get_intrinsics()
            return {"fx": intr.fx, "fy": intr.fy, "cx": intr.ppx, "cy": intr.ppy}
        except Exception as exc:
            logger.warning("Failed to get RealSense intrinsics: %s", exc)
            return None

    def get_depth_at(self, depth_raw: np.ndarray, x: int, y: int, radius: int = 4) -> Optional[float]:
        """Return median depth in cm around pixel (x, y). Returns None if no valid data."""
        try:
            h, w = depth_raw.shape
            x1 = max(0, x - radius); x2 = min(w, x + radius)
            y1 = max(0, y - radius); y2 = min(h, y + radius)
            patch = depth_raw[y1:y2, x1:x2]
            valid = patch[patch > 0]
            if len(valid) == 0:
                return None
            return round(float(np.median(valid)) / 10.0, 1)  # mm → cm
        except Exception:
            return None

    def stop(self):
        self._running = False
        if self._pipeline:
            try:
                self._pipeline.stop()
            except Exception:
                pass
            self._pipeline = None
        logger.info("RealSense D435i stopped")
