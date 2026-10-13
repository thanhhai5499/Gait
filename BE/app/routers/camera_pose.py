"""
Camera + YOLOv8-Pose router — GPU-accelerated pose streaming on Jetson AGX Thor.

Architecture (per WebSocket connection):
  stream_task   – reads raw frames from camera at 30 FPS, overlays the LAST
                  known skeleton (cached from inference), encodes and sends.
  inference_task – runs YOLOv8-Pose on GPU continuously in a thread executor,
                  updating the shared keypoint cache whenever a new result is ready.

REST endpoint  → GET  /camera/list           (nginx: /api/camera/list)
WebSocket      → WS   /ws/camera/{camera_id} (nginx: /ws/camera/{id})
WebSocket      → WS   /ws/realsense          (nginx: /ws/realsense)
"""
import asyncio
import base64
import logging
import os
import platform
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.services.pose_analyzer import (
    PoseAnalyzer, overlay_skeleton,
    _calculate_angles, calculate_frontal_angles, calculate_posterior_angles,
)
from app.services.gait_tracker import KalmanSmoother, AngleSmoother
from app.services.gait_cycle_analyzer import GaitCycleDetector
from app.services.realsense_reader import RealSenseReader, detect_realsense, is_realsense_available

# Map from pose_3d output keys → canonical angle keys used throughout the system.
# When RealSense depth is available, 3D angles replace 2D angles in the fusion store
# because they eliminate perspective-projection error (~5-10° → ~1-2°).
# LƯU Ý: khóa "left_ankle"/"right_ankle" là tên lịch sử, giá trị bên trong là ĐỘ NGHIÊNG CẲNG CHÂN
# (knee→ankle so với phương thẳng đứng), KHÔNG phải góc khớp cổ chân. COCO-17 không có điểm gót/mũi
# chân nên không tính được góc cổ chân; thiết bị vật lý cũng không có cảm biến cổ chân.
_3D_TO_CANONICAL: dict[str, str] = {
    "left_knee_3d":         "left_knee",
    "right_knee_3d":        "right_knee",
    "left_hip_3d":          "left_hip",
    "right_hip_3d":         "right_hip",
    "left_ankle_3d":        "left_ankle",
    "right_ankle_3d":       "right_ankle",
    "trunk_inclination_3d": "trunk_inclination",
}

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Camera Pose"])

# ── Multi-camera metrics fusion store ─────────────────────────────────────────
# Each camera role writes its latest detected angles here.
# /api/gait/metrics fuses them by selecting the best source per metric.

_latest_metrics: dict[str, dict] = {}
_metrics_lock   = threading.Lock()

# Which camera view is most reliable for each gait metric (in priority order)
_METRIC_PRIORITY: dict[str, list[str]] = {
    "left_knee":               ["lateral", "frontal", "posterior"],
    "right_knee":              ["lateral", "frontal", "posterior"],
    "left_hip":                ["lateral", "frontal"],
    "right_hip":               ["lateral", "frontal"],
    "left_ankle":              ["lateral"],
    "right_ankle":             ["lateral"],
    "trunk_inclination":       ["lateral", "frontal"],
    "knee_symmetry_index":     ["lateral", "frontal", "posterior"],
    "left_hip_abduction":      ["frontal", "posterior"],
    "right_hip_abduction":     ["frontal", "posterior"],
    "lateral_trunk_lean":      ["frontal", "posterior"],
    "left_knee_valgus":        ["frontal"],
    "right_knee_valgus":       ["frontal"],
    "pelvic_obliquity":        ["posterior"],
    "left_hip_drop":           ["posterior"],
    "right_hip_drop":          ["posterior"],
    "left_foot_progression":   ["posterior"],
    "right_foot_progression":  ["posterior"],
    # Gait cycle temporal parameters (lateral camera only)
    "cadence":                 ["lateral"],
    "stride_time":             ["lateral"],
    "stance_phase_pct":        ["lateral"],
    "swing_phase_pct":         ["lateral"],
    "step_symmetry":           ["lateral"],
}


def _update_metrics(role: str, angles: dict, detected: int) -> None:
    with _metrics_lock:
        _latest_metrics[role] = {
            "angles":   angles,
            "detected": detected,
            "ts":       time.monotonic(),
        }


def _fuse_metrics() -> dict:
    """
    Return the best available value for each gait metric by iterating
    the camera priority list for that metric.  Only uses readings that
    arrived within the last 2 seconds and from a camera that detected a person.
    """
    with _metrics_lock:
        snapshot = {k: dict(v) for k, v in _latest_metrics.items()}

    now   = time.monotonic()
    fused: dict = {}

    for metric, priority in _METRIC_PRIORITY.items():
        for role in priority:
            cam = snapshot.get(role)
            if not cam:
                continue
            if cam.get("detected", 0) == 0:
                continue
            if now - cam.get("ts", 0) > 2.0:   # stale reading
                continue
            val = cam["angles"].get(metric)
            if val is not None:
                fused[metric] = val
                fused[f"{metric}_source"] = role
                break

    cameras_active = [r for r, c in snapshot.items() if c.get("detected", 0) > 0]
    fused["cameras_active"] = cameras_active
    return fused

_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="pose")

CAPTURE_FPS  = 30
STREAM_FPS   = 30
JPEG_QUALITY = 70

# Inference rate control — GPU (YOLOv8) is fast enough for all 3 cameras at full rate.
# 3 cameras × 20 ms GPU inference ≈ 60 ms round-trip → each camera ≥ 15 fps.
_INFERENCE_ACTIVE_HZ   = 30    # Hz per camera — TRT 4.7ms × 3 cam = 14ms << 33ms display period
_INFERENCE_IDLE_HZ     = 2     # Hz after IDLE_THRESHOLD consecutive empty frames
_IDLE_THRESHOLD        = 15    # consecutive no-person frames before switching to idle

# ── Platform-aware camera backends ───────────────────────────────────────────
# Windows: try DirectShow first (faster negotiation), then default (MSMF)
# Linux (Jetson): V4L2 only for probe — Brio 300 exposes secondary metadata nodes
#   that fail V4L2 but succeed with CAP_ANY at tiny resolutions (424×240, 256×144).
#   Probing V4L2-only filters them out; streaming still falls back to CAP_ANY as
#   a safety net in case a real camera needs it.
_IS_LINUX = platform.system() == "Linux"
_PROBE_BACKENDS: list[int] = (
    [cv2.CAP_V4L2]               if _IS_LINUX   # no CAP_ANY fallback during probe
    else [cv2.CAP_DSHOW, cv2.CAP_ANY]
)
_STREAM_BACKENDS: list[tuple[str, int]] = (
    [("V4L2", cv2.CAP_V4L2), ("ANY", cv2.CAP_ANY)] if _IS_LINUX
    else [("DSHOW", cv2.CAP_DSHOW), ("ANY", cv2.CAP_ANY)]
)

# ── Camera open lock ──────────────────────────────────────────────────────────
# Serialize camera opens: MSMF (Windows) / V4L2 (Linux) can fail when two
# cameras negotiate media types simultaneously in the same process.
_camera_open_lock = threading.Lock()

# ── Dynamic camera probe (runs once, cached) ──────────────────────────────────
_probe_cache: list[dict] | None = None
_probe_lock  = threading.Lock()


def _v4l2_device_name(index: int) -> str:
    """Read V4L2 device name from sysfs (Linux only)."""
    try:
        with open(f"/sys/class/video4linux/video{index}/name") as f:
            return f.read().strip()
    except Exception:
        return ""


def _is_realsense_node(index: int) -> bool:
    """True if this V4L2 index belongs to the RealSense device (skip from USB cam probe)."""
    name = _v4l2_device_name(index)
    return "RealSense" in name or "realsense" in name.lower()


def _probe_cameras() -> list[dict]:
    """
    Probe indices 0-9 once, cache forever.
    Skips RealSense V4L2 nodes (handled separately via pyrealsense2).
    Uses platform-appropriate backend: V4L2 on Linux/Jetson, DSHOW on Windows.
    Brio 300 identified by achieving 1920×1080; built-in webcams cap at 720p.
    """
    global _probe_cache
    if _probe_cache is not None:
        return _probe_cache

    with _probe_lock:
        if _probe_cache is not None:
            return _probe_cache

        cameras: list[dict] = []
        for i in range(10):
            # On Linux, skip indices with no /dev/videoX node to avoid OpenCV stderr spam
            if _IS_LINUX and not os.path.exists(f"/dev/video{i}"):
                continue
            # Skip RealSense V4L2 nodes — those are probed separately
            if _IS_LINUX and _is_realsense_node(i):
                logger.debug("Probe: idx=%d skipped (RealSense node)", i)
                continue

            result: list[dict] = []

            def _try(idx=i):
                for backend in _PROBE_BACKENDS:
                    cap = cv2.VideoCapture(idx, backend)
                    if not cap.isOpened():
                        cap.release()
                        continue
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                    cap.set(cv2.CAP_PROP_FPS, 30)
                    # NOTE: do NOT set BUFFERSIZE=1 here — it causes OpenCV
                    # to skip alternate frames, halving the measured fps.
                    # warmup
                    for _ in range(10):
                        ret, _ = cap.read()
                        if ret:
                            break
                    else:
                        cap.release()
                        continue
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    # measure real fps (20 frames, no BUFFERSIZE override)
                    t0 = time.perf_counter()
                    n = 0
                    for _ in range(20):
                        r, _ = cap.read()
                        if r:
                            n += 1
                    elapsed = time.perf_counter() - t0
                    real_fps = round(n / elapsed, 1) if elapsed > 0 else 0.0
                    cap.release()
                    result.append({"index": idx, "width": w, "height": h, "fps": real_fps})
                    return

            t = threading.Thread(target=_try, daemon=True)
            t.start()
            t.join(timeout=10)

            if result:
                d = result[0]
                d["name"] = "Brio 300" if d["width"] >= 1280 and d["height"] >= 720 else f"Camera {i}"
                logger.info("Probe: idx=%d → %s %dx%d", i, d["name"], d["width"], d["height"])
                cameras.append(d)
            else:
                logger.debug("Probe: idx=%d timed-out or no camera", i)

        _probe_cache = cameras
        logger.info("Probe complete: %d camera(s) found on %s", len(cameras), platform.system())
        return cameras


def _start_background_probe() -> None:
    """Kick off the probe in the background so first /camera/list is fast."""
    t = threading.Thread(target=_probe_cameras, daemon=True, name="camera-probe")
    t.start()


# Start probe as soon as this module is imported (server startup)
_start_background_probe()


# ── REST ──────────────────────────────────────────────────────────────────────

@router.get("/camera/list", summary="List available camera indices with metadata")
async def list_cameras(refresh: bool = Query(False, description="Force re-probe even if cache exists")):
    global _probe_cache
    if refresh:
        with _probe_lock:
            _probe_cache = None
    loop = asyncio.get_event_loop()
    cameras = await loop.run_in_executor(_executor, _probe_cameras)
    # Append RealSense if connected
    rs_info = await loop.run_in_executor(_executor, detect_realsense)
    if rs_info:
        cameras = [rs_info] + cameras
    return {"cameras": cameras}


@router.get("/gait/metrics", summary="Fused gait metrics from all active cameras")
async def get_gait_metrics():
    """
    Returns a single dict of gait angles, each sourced from the camera most
    suitable for that metric.  Only values from cameras that detected a person
    in the last 2 seconds are included.

    Example: left_knee comes from RealSense lateral view; pelvic_obliquity
    comes from the posterior USB camera.
    """
    return _fuse_metrics()


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/camera/{camera_id}")
async def camera_pose_ws(
    websocket: WebSocket,
    camera_id: int,
    token: str = Query(None, description="JWT access token"),
    role: str = Query("frontal", description="Camera view role: frontal | posterior"),
):
    await websocket.accept()
    loop = asyncio.get_event_loop()

    if token:
        try:
            from app.auth.utils import decode_token
            decode_token(token)
        except Exception:
            try:
                await websocket.send_json({"type": "error", "message": "Token không hợp lệ"})
                await websocket.close(code=4001)
            except Exception:
                pass
            return

    # ── Open camera (serialized to avoid simultaneous MSMF conflicts) ──
    cap: cv2.VideoCapture = await loop.run_in_executor(
        _executor, lambda: _open_camera(camera_id)
    )
    if not cap.isOpened():
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Không thể mở camera {camera_id}. Kiểm tra camera đã cắm chưa.",
            })
            await websocket.close()
        except Exception:
            pass
        return

    actual_w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    try:
        await websocket.send_json({
            "type": "status",
            "message": f"Camera {camera_id} mở thành công — {actual_w}×{actual_h} @ {actual_fps:.0f}fps. Đang tải YOLOv8-Pose model…",
            "resolution": {"width": actual_w, "height": actual_h, "fps": actual_fps},
        })
    except Exception:
        await loop.run_in_executor(_executor, cap.release)
        return

    await loop.run_in_executor(_executor, PoseAnalyzer.load_model)
    try:
        await websocket.send_json({"type": "status", "message": "YOLOv8-Pose GPU sẵn sàng. Bắt đầu stream…"})
    except Exception:
        await loop.run_in_executor(_executor, cap.release)
        return

    state: dict = {
        "raw_frame":       None,
        "keypoints":       [],
        "angles":          {},
        "detected":        0,
        "proc_ms":         0.0,
        "inf_count":       0,
        "frame_id":        0,
        "role":            role,
        "bbox":            None,
        "smoother":        KalmanSmoother(),
        "angle_smoother":  AngleSmoother(),
        "cycle_detector":  GaitCycleDetector(fps=_INFERENCE_ACTIVE_HZ) if role == "lateral" else None,
        "last_inf_ts":     0.0,   # timestamp of last completed inference (for forward prediction)
    }
    stop = asyncio.Event()

    async def inference_loop() -> None:
        consecutive_empty = 0
        last_inferred_at  = 0.0

        # All cameras run at the same rate — GPU inference is fast enough.
        _active_hz = _INFERENCE_ACTIVE_HZ
        _idle_hz   = _INFERENCE_IDLE_HZ

        while not stop.is_set():
            raw = state["raw_frame"]
            if raw is None:
                await asyncio.sleep(0.02)
                continue

            now      = time.perf_counter()
            idle     = consecutive_empty >= _IDLE_THRESHOLD
            interval = 1.0 / (_idle_hz if idle else _active_hz)

            if now - last_inferred_at < interval:
                await asyncio.sleep(0.01)
                continue

            frame_copy       = raw.copy()
            last_inferred_at = now
            try:
                bbox = state["bbox"]
                result = await loop.run_in_executor(
                    _executor,
                    lambda: PoseAnalyzer.process_frame(
                        frame_copy, camera_role=state["role"], prev_bbox=bbox
                    )
                )

                # Smooth raw keypoints with per-camera Kalman smoother
                smoothed = state["smoother"].update(result["keypoints"])

                # Recompute angles from smoothed positions for stable readings
                n_sm = sum(1 for kp in smoothed if kp is not None)
                if n_sm >= 5:
                    sm_angles = _calculate_angles(smoothed)
                    if state["role"] == "frontal":
                        sm_angles.update(calculate_frontal_angles(smoothed))
                    elif state["role"] == "posterior":
                        sm_angles.update(calculate_posterior_angles(smoothed))
                else:
                    sm_angles = {}

                # Stage 2: EMA smoothing on computed angles (removes residual jitter)
                sm_angles = state["angle_smoother"].update(sm_angles)

                # Gait cycle detection (lateral camera only)
                if state["cycle_detector"] is not None and result["keypoints_detected"] > 0:
                    cycle = state["cycle_detector"].update(smoothed, time.perf_counter())
                    sm_angles.update({k: v for k, v in cycle.items() if v is not None and k != "event"})

                state["keypoints"]    = smoothed
                state["angles"]       = sm_angles
                state["detected"]     = result["keypoints_detected"]
                state["proc_ms"]      = result["processing_time_ms"]
                state["bbox"]         = result["person_bbox"]
                state["last_inf_ts"]  = time.perf_counter()
                state["inf_count"]   += 1
                _update_metrics(state["role"], sm_angles, result["keypoints_detected"])

                if result["keypoints_detected"] == 0:
                    consecutive_empty += 1
                    if consecutive_empty >= _IDLE_THRESHOLD:
                        state["bbox"] = None
                else:
                    consecutive_empty = 0
            except Exception as exc:
                logger.warning("Inference error cam %d: %s", camera_id, exc)
                await asyncio.sleep(0.1)

    async def stream_loop() -> None:
        interval      = 1.0 / STREAM_FPS
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]

        while not stop.is_set():
            t0 = time.perf_counter()

            ret, frame = await loop.run_in_executor(_executor, cap.read)
            if not ret or frame is None:
                try:
                    await websocket.send_json({"type": "error", "message": "Camera ngắt kết nối bất ngờ."})
                except Exception:
                    pass
                stop.set()
                break

            state["raw_frame"] = frame

            # Forward-predict keypoints to compensate inference latency:
            # extrapolate Kalman velocity forward by however many inference
            # frames have elapsed since the last completed inference.
            inf_age_frames = (time.perf_counter() - state["last_inf_ts"]) * _INFERENCE_ACTIVE_HZ
            kps = state["smoother"].predict_display(inf_age_frames)
            annotated = await loop.run_in_executor(_executor, lambda: overlay_skeleton(frame.copy(), kps))

            ok, buf = await loop.run_in_executor(_executor, lambda: cv2.imencode(".jpg", annotated, encode_params))
            if not ok:
                continue

            try:
                await websocket.send_json({
                    "type":               "frame",
                    "camera_id":          camera_id,
                    "role":               state["role"],
                    "frame_id":           state["frame_id"],
                    "server_ts":          int(time.monotonic() * 1000),
                    "frame":              base64.b64encode(buf).decode(),
                    "angles":             state["angles"],
                    "keypoints_detected": state["detected"],
                    "processing_time_ms": state["proc_ms"],
                    "resolution":         {"width": actual_w, "height": actual_h},
                })
                state["frame_id"] += 1
            except (WebSocketDisconnect, RuntimeError):
                stop.set()
                break

            elapsed   = time.perf_counter() - t0
            sleep_for = interval - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    inference_task = asyncio.create_task(inference_loop())
    stream_task    = asyncio.create_task(stream_loop())

    try:
        while not stop.is_set():
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                if msg.strip() == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        logger.info("Camera %d client disconnected", camera_id)
    except Exception as exc:
        logger.exception("Camera %d unexpected error: %s", camera_id, exc)
    finally:
        stop.set()
        inference_task.cancel()
        stream_task.cancel()
        await asyncio.gather(inference_task, stream_task, return_exceptions=True)
        await loop.run_in_executor(_executor, cap.release)
        logger.info("Camera %d released — inference ran %d times", camera_id, state["inf_count"])


# ── Blocking helpers ──────────────────────────────────────────────────────────

def _open_camera(camera_id: int) -> cv2.VideoCapture:
    """
    Open camera for streaming.
    - Serialized via _camera_open_lock to prevent simultaneous media negotiation.
    - Uses V4L2 on Linux/Jetson, DSHOW on Windows, falls back to CAP_ANY.
    - No FOURCC before first read: causes MF_E_NO_MORE_TYPES on Windows MSMF.
    - 20 warmup reads to let the driver stabilize after property changes.
    """
    with _camera_open_lock:
        for backend_name, backend in _STREAM_BACKENDS:
            cap = cv2.VideoCapture(camera_id, backend)
            if not cap.isOpened():
                cap.release()
                logger.debug("Camera %d: %s backend failed to open", camera_id, backend_name)
                continue

            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

            for target_w, target_h in [(1280, 720)]:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH,  target_w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)
                cap.set(cv2.CAP_PROP_FPS, CAPTURE_FPS)

                ret = False
                for _ in range(20):
                    ret, _ = cap.read()
                    if ret:
                        break

                if ret:
                    aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    logger.info("Camera %d opened via %s at %dx%d", camera_id, backend_name, aw, ah)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    return cap

                logger.warning("Camera %d: %s %dx%d failed, trying lower", camera_id, backend_name, target_w, target_h)

            cap.release()

        logger.error("Camera %d: all backends and resolutions failed", camera_id)
        return cv2.VideoCapture()


# ── RealSense D435i WebSocket ─────────────────────────────────────────────────

@router.websocket("/ws/realsense")
async def realsense_pose_ws(
    websocket: WebSocket,
    token: str = Query(None, description="JWT access token"),
):
    """
    Stream RGB + Depth + IMU from Intel RealSense D435i with OpenPose overlay.
    Sends same frame message format as /ws/camera/{id} plus:
      depth_at_joints: {joint_name: distance_cm}
      imu: {accel: [x,y,z], gyro: [x,y,z]}
      depth_frame: base64 JPEG of jet-colorized depth map
    """
    await websocket.accept()
    loop = asyncio.get_event_loop()

    if token:
        try:
            from app.auth.utils import decode_token
            decode_token(token)
        except Exception:
            try:
                await websocket.send_json({"type": "error", "message": "Token không hợp lệ"})
                await websocket.close(code=4001)
            except Exception:
                pass
            return

    if not is_realsense_available():
        try:
            await websocket.send_json({"type": "error", "message": "pyrealsense2 không được cài đặt trên server."})
            await websocket.close()
        except Exception:
            pass
        return

    reader = RealSenseReader()
    try:
        await websocket.send_json({"type": "status", "message": "Đang khởi động RealSense D435i…"})
    except Exception:
        return

    started = await loop.run_in_executor(_executor, reader.start)
    if not started:
        try:
            await websocket.send_json({"type": "error", "message": "Không thể mở RealSense D435i. Kiểm tra camera đã cắm chưa."})
            await websocket.close()
        except Exception:
            pass
        return

    try:
        await websocket.send_json({"type": "status", "message": "RealSense mở thành công. Đang tải YOLOv8-Pose model…", "resolution": {"width": 1280, "height": 720, "fps": 30}})
    except Exception:
        await loop.run_in_executor(_executor, reader.stop)
        return

    await loop.run_in_executor(_executor, PoseAnalyzer.load_model)
    try:
        await websocket.send_json({"type": "status", "message": "YOLOv8-Pose GPU sẵn sàng. Bắt đầu stream RealSense…"})
    except Exception:
        await loop.run_in_executor(_executor, reader.stop)
        return

    state: dict = {
        "raw_frame":      None,
        "depth_raw":      None,
        "keypoints":      [],
        "angles":         {},
        "angles_3d":      {},
        "detected":       0,
        "proc_ms":        0.0,
        "imu":            {"accel": [0.0, 0.0, 0.0], "gyro": [0.0, 0.0, 0.0]},
        "inf_count":      0,
        "frame_id":       0,
        "role":           "lateral",
        "bbox":           None,
        "smoother":       KalmanSmoother(),
        "angle_smoother": AngleSmoother(),
        "cycle_detector": GaitCycleDetector(fps=_INFERENCE_ACTIVE_HZ),
        "intrinsics":     None,
        "last_inf_ts":    0.0,
    }
    stop = asyncio.Event()
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]

    async def inference_loop() -> None:
        consecutive_empty = 0
        last_inferred_at  = 0.0

        while not stop.is_set():
            raw = state["raw_frame"]
            if raw is None:
                await asyncio.sleep(0.02)
                continue

            now      = time.perf_counter()
            idle     = consecutive_empty >= _IDLE_THRESHOLD
            interval = 1.0 / (_INFERENCE_IDLE_HZ if idle else _INFERENCE_ACTIVE_HZ)

            if now - last_inferred_at < interval:
                await asyncio.sleep(0.01)
                continue

            frame_copy       = raw.copy()
            last_inferred_at = now
            try:
                bbox = state["bbox"]
                result = await loop.run_in_executor(
                    _executor,
                    lambda: PoseAnalyzer.process_frame(
                        frame_copy, camera_role="lateral", prev_bbox=bbox
                    )
                )

                smoothed = state["smoother"].update(result["keypoints"])
                n_sm = sum(1 for kp in smoothed if kp is not None)
                sm_angles = _calculate_angles(smoothed) if n_sm >= 5 else {}

                # Stage 2: EMA on angles
                sm_angles = state["angle_smoother"].update(sm_angles)

                # Gait cycle detection
                if result["keypoints_detected"] > 0:
                    cycle = state["cycle_detector"].update(smoothed, time.perf_counter())
                    sm_angles.update({k: v for k, v in cycle.items() if v is not None and k != "event"})

                # 3D angles from depth (lazy-load intrinsics once)
                if state["intrinsics"] is None:
                    state["intrinsics"] = await loop.run_in_executor(_executor, reader.get_intrinsics)

                if state["depth_raw"] is not None and state["intrinsics"] and n_sm >= 5:
                    try:
                        from app.services.pose_3d import keypoints_to_3d, compute_angles_3d
                        kps_3d = await loop.run_in_executor(
                            _executor,
                            lambda: keypoints_to_3d(smoothed, state["depth_raw"], state["intrinsics"])
                        )
                        angles_3d = compute_angles_3d(kps_3d)
                        state["angles_3d"] = angles_3d

                        # Overwrite 2D angles with 3D where depth is valid.
                        # 3D eliminates perspective-projection error (±5-10° → ±1-2°).
                        for k3d, kcan in _3D_TO_CANONICAL.items():
                            v = angles_3d.get(k3d)
                            if v is not None:
                                sm_angles[kcan] = v
                    except Exception as exc_3d:
                        logger.debug("3D angle error: %s", exc_3d)

                # Recompute knee symmetry from merged (possibly 3D) knee angles
                lk = sm_angles.get("left_knee")
                rk = sm_angles.get("right_knee")
                if lk is not None and rk is not None and (abs(lk) + abs(rk)) > 0:
                    sm_angles["knee_symmetry_index"] = round(
                        200.0 * abs(lk - rk) / (abs(lk) + abs(rk)), 1
                    )

                state["keypoints"]   = smoothed
                state["angles"]      = sm_angles
                state["detected"]    = result["keypoints_detected"]
                state["proc_ms"]     = result["processing_time_ms"]
                state["bbox"]        = result["person_bbox"]
                state["last_inf_ts"] = time.perf_counter()
                state["inf_count"]  += 1
                # Feed merged (3D-preferred) angles to fusion store
                _update_metrics("lateral", sm_angles, result["keypoints_detected"])

                if result["keypoints_detected"] == 0:
                    consecutive_empty += 1
                    if consecutive_empty >= _IDLE_THRESHOLD:
                        state["bbox"] = None
                else:
                    consecutive_empty = 0
            except Exception as exc:
                logger.warning("RealSense inference error: %s", exc)
                await asyncio.sleep(0.1)

    async def stream_loop() -> None:
        interval = 1.0 / STREAM_FPS

        while not stop.is_set():
            t0 = time.perf_counter()

            frame_data = await loop.run_in_executor(_executor, reader.read_frame)
            if frame_data is None:
                await asyncio.sleep(0.02)
                continue

            color  = frame_data["color_frame"]
            depth_raw   = frame_data["depth_raw"]
            depth_cmap  = frame_data["depth_colormap"]
            imu         = frame_data["imu"]

            state["raw_frame"] = color
            state["depth_raw"] = depth_raw
            state["imu"]       = imu

            # Forward-predict to compensate inference latency
            inf_age_frames = (time.perf_counter() - state["last_inf_ts"]) * _INFERENCE_ACTIVE_HZ
            kps = state["smoother"].predict_display(inf_age_frames)
            annotated = await loop.run_in_executor(_executor, lambda: overlay_skeleton(color.copy(), kps))

            # Compute depth at each detected joint (cm)
            depth_at_joints: dict = {}
            if kps and depth_raw is not None:
                from app.services.pose_analyzer import (
                    KP_L_KNEE, KP_R_KNEE, KP_L_HIP, KP_R_HIP,
                    KP_L_ANKLE, KP_R_ANKLE, KP_NECK, KP_MID_HIP,
                )
                joint_map = {
                    "left_knee":  KP_L_KNEE,  "right_knee":  KP_R_KNEE,
                    "left_hip":   KP_L_HIP,   "right_hip":   KP_R_HIP,
                    "left_ankle": KP_L_ANKLE, "right_ankle": KP_R_ANKLE,
                    "neck":       KP_NECK,    "mid_hip":     KP_MID_HIP,
                }
                for name, idx in joint_map.items():
                    kp = kps[idx] if idx < len(kps) else None
                    if kp:
                        d = reader.get_depth_at(depth_raw, kp[0], kp[1])
                        if d is not None:
                            depth_at_joints[name] = d

            ok_c, buf_c = await loop.run_in_executor(_executor, lambda: cv2.imencode(".jpg", annotated, encode_params))
            ok_d, buf_d = await loop.run_in_executor(_executor, lambda: cv2.imencode(".jpg", depth_cmap, encode_params))

            if not ok_c:
                continue

            try:
                await websocket.send_json({
                    "type":               "frame",
                    "camera_id":          "realsense",
                    "role":               "lateral",
                    "frame_id":           state["frame_id"],
                    "server_ts":          int(time.monotonic() * 1000),
                    "frame":              base64.b64encode(buf_c).decode(),
                    "depth_frame":        base64.b64encode(buf_d).decode() if ok_d else None,
                    "angles":             state["angles"],
                    "angles_3d":          state["angles_3d"],
                    "has_3d":             bool(state["angles_3d"]),
                    "keypoints_detected": state["detected"],
                    "processing_time_ms": state["proc_ms"],
                    "resolution":         {"width": 1280, "height": 720},
                    "depth_at_joints":    depth_at_joints,
                    "imu":                imu,
                })
                state["frame_id"] += 1
            except (WebSocketDisconnect, RuntimeError):
                stop.set()
                break

            elapsed = time.perf_counter() - t0
            sleep_for = interval - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    inference_task = asyncio.create_task(inference_loop())
    stream_task    = asyncio.create_task(stream_loop())

    try:
        while not stop.is_set():
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                if msg.strip() == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        logger.info("RealSense client disconnected")
    except Exception as exc:
        logger.exception("RealSense WS unexpected error: %s", exc)
    finally:
        stop.set()
        inference_task.cancel()
        stream_task.cancel()
        await asyncio.gather(inference_task, stream_task, return_exceptions=True)
        await loop.run_in_executor(_executor, reader.stop)
        logger.info("RealSense released — inference ran %d times", state["inf_count"])


# ── Fused gait-metrics WebSocket ──────────────────────────────────────────────

@router.websocket("/ws/gait-metrics")
async def gait_metrics_ws(
    websocket: WebSocket,
    token: str = Query(None),
    hz: float = Query(10.0, ge=1.0, le=30.0, description="Push rate in Hz"),
):
    """
    Streams fused gait metrics at *hz* Hz (default 10 Hz).
    Aggregates the latest angles from all connected cameras and selects
    the most reliable source per metric (lateral > frontal > posterior
    for knee/hip; posterior for pelvic tilt; etc.).

    Message format:
      { "type": "metrics", "ts": <ms>, "metrics": { <metric>: <value>, ... },
        "cameras_active": ["lateral", "frontal"] }
    """
    await websocket.accept()

    if token:
        try:
            from app.auth.utils import decode_token
            decode_token(token)
        except Exception:
            try:
                await websocket.send_json({"type": "error", "message": "Token không hợp lệ"})
                await websocket.close(code=4001)
            except Exception:
                pass
            return

    interval = 1.0 / hz
    try:
        while True:
            t0 = time.monotonic()
            fused = _fuse_metrics()
            try:
                await websocket.send_json({
                    "type":    "metrics",
                    "ts":      int(time.monotonic() * 1000),
                    "metrics": fused,
                    "cameras_active": fused.pop("cameras_active", []),
                })
            except (WebSocketDisconnect, RuntimeError):
                break
            elapsed = time.monotonic() - t0
            sleep_for = interval - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("gait-metrics WS error: %s", exc)
