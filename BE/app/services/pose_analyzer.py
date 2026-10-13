"""
YOLOv8-Pose based gait analysis — GPU-accelerated on Jetson AGX Thor.

Replaces the previous OpenPose Caffe CPU backend.  Inference runs on the
Thor GPU via PyTorch CUDA; typical latency is 10-20 ms per frame at 640×640.

Output keypoints are emitted in the same Body-25 slot layout used by the
rest of the codebase (angle functions, camera_pose router, etc.) so that no
downstream changes are required.  COCO-17 joints not present in Body-25, and
Body-25 joints not in COCO-17 (toe/heel), are left as None.
"""
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── YOLO model config ────────────────────────────────────────────────────────
# yolov8l-pose  : good balance (86MB, ~15ms on Thor GPU)
# yolov8x-pose  : best accuracy (137MB, ~25ms on Thor GPU) ← commercial default
_MODEL_NAME = "yolov8x-pose.engine"   # TensorRT FP16 — 4.7ms vs 15.7ms PyTorch
_MODEL_DIR  = Path(__file__).parent.parent.parent / "models" / "pose" / "yolov8"
_CONF_THRESHOLD = 0.50   # person detection confidence
_IOU_THRESHOLD  = 0.45   # NMS IoU threshold
_KP_CONF        = 0.40   # minimum keypoint confidence (raised from 0.30 → fewer jittery points)

# Inference input size (must be multiple of 32).
# 512×512 → ~36% faster than 640×640 on Jetson; person fills ≥50% of frame
# so spatial resolution loss is negligible for gait-analysis keypoints.
INPUT_SIZE = 512

MIN_KEYPOINTS_TO_DRAW = 5

# ── Body-25 keypoint indices (same as OpenPose) ───────────────────────────────
KP_NOSE        = 0
KP_NECK        = 1
KP_R_SHOULDER  = 2
KP_R_ELBOW     = 3
KP_R_WRIST     = 4
KP_L_SHOULDER  = 5
KP_L_ELBOW     = 6
KP_L_WRIST     = 7
KP_MID_HIP     = 8
KP_R_HIP       = 9
KP_R_KNEE      = 10
KP_R_ANKLE     = 11
KP_L_HIP       = 12
KP_L_KNEE      = 13
KP_L_ANKLE     = 14
KP_R_EYE       = 15
KP_L_EYE       = 16
KP_R_EAR       = 17
KP_L_EAR       = 18
KP_L_BIG_TOE   = 19
KP_L_SMALL_TOE = 20
KP_L_HEEL      = 21
KP_R_BIG_TOE   = 22
KP_R_SMALL_TOE = 23
KP_R_HEEL      = 24

_LOWER_BODY_JOINTS = (KP_L_HIP, KP_R_HIP, KP_L_KNEE, KP_R_KNEE, KP_L_ANKLE, KP_R_ANKLE)
_MIN_LOWER_BODY    = 1

# ── COCO-17 → Body-25 index mapping ──────────────────────────────────────────
# COCO-17: 0=nose,1=L_eye,2=R_eye,3=L_ear,4=R_ear,5=L_shoulder,6=R_shoulder,
#          7=L_elbow,8=R_elbow,9=L_wrist,10=R_wrist,11=L_hip,12=R_hip,
#          13=L_knee,14=R_knee,15=L_ankle,16=R_ankle
_COCO_TO_B25: dict[int, int] = {
    0:  KP_NOSE,
    1:  KP_L_EYE,
    2:  KP_R_EYE,
    3:  KP_L_EAR,
    4:  KP_R_EAR,
    5:  KP_L_SHOULDER,
    6:  KP_R_SHOULDER,
    7:  KP_L_ELBOW,
    8:  KP_R_ELBOW,
    9:  KP_L_WRIST,
    10: KP_R_WRIST,
    11: KP_L_HIP,
    12: KP_R_HIP,
    13: KP_L_KNEE,
    14: KP_R_KNEE,
    15: KP_L_ANKLE,
    16: KP_R_ANKLE,
}
# Computed Body-25 joints derived from COCO pairs
_COCO_NECK_PAIR    = (5, 6)   # avg(L_shoulder, R_shoulder) → KP_NECK
_COCO_MIDHIP_PAIR  = (11, 12) # avg(L_hip, R_hip)           → KP_MID_HIP

# ── Skeleton rendering (Body-25 joint pairs) ──────────────────────────────────
_SKELETON: list[tuple[tuple[int, int], tuple[int, int, int]]] = [
    ((KP_NECK,       KP_NOSE),        (0, 220, 220)),
    ((KP_NECK,       KP_R_SHOULDER),  (0, 200, 0)),
    ((KP_R_SHOULDER, KP_R_ELBOW),     (0, 200, 0)),
    ((KP_R_ELBOW,    KP_R_WRIST),     (0, 200, 0)),
    ((KP_NECK,       KP_L_SHOULDER),  (0, 200, 0)),
    ((KP_L_SHOULDER, KP_L_ELBOW),     (0, 200, 0)),
    ((KP_L_ELBOW,    KP_L_WRIST),     (0, 200, 0)),
    ((KP_NECK,       KP_MID_HIP),     (200, 200, 0)),
    ((KP_MID_HIP,    KP_R_HIP),       (0, 80, 255)),
    ((KP_R_HIP,      KP_R_KNEE),      (0, 80, 255)),
    ((KP_R_KNEE,     KP_R_ANKLE),     (0, 80, 255)),
    ((KP_MID_HIP,    KP_L_HIP),       (255, 80, 0)),
    ((KP_L_HIP,      KP_L_KNEE),      (255, 80, 0)),
    ((KP_L_KNEE,     KP_L_ANKLE),     (255, 80, 0)),
]


class PoseAnalyzer:
    """
    YOLOv8-Pose singleton.  GPU-accelerated on Jetson AGX Thor.

    Thread-safe: _infer_lock serializes inference calls across the 3 camera
    threads.  With 10-20 ms GPU latency (vs 78 ms CPU) the lock queue drains
    in <60 ms for 3 cameras — still ≥15 fps per camera.
    """

    _model      = None          # ultralytics.YOLO instance
    _model_ok: bool = False
    _load_lock:  threading.Lock = threading.Lock()
    _infer_lock: threading.Lock = threading.Lock()
    _device: str = "cpu"        # set to "cuda:0" once GPU confirmed

    # ── Model loading ─────────────────────────────────────────────────────────
    @classmethod
    def load_model(cls) -> bool:
        if cls._model is not None:
            return cls._model_ok
        with cls._load_lock:
            if cls._model is not None:
                return cls._model_ok
            try:
                from ultralytics import YOLO
                import torch

                # Prefer GPU; fall back gracefully to CPU
                if torch.cuda.is_available():
                    cls._device = "cuda:0"
                    logger.info("PoseAnalyzer: CUDA available — using GPU (%s)",
                                torch.cuda.get_device_name(0))
                else:
                    cls._device = "cpu"
                    logger.warning("PoseAnalyzer: CUDA not available — using CPU (slower)")

                # Look for pre-downloaded model first; ultralytics auto-downloads otherwise
                _MODEL_DIR.mkdir(parents=True, exist_ok=True)
                local_pt = _MODEL_DIR / _MODEL_NAME
                model_path = str(local_pt) if local_pt.exists() else _MODEL_NAME

                logger.info("Loading %s on %s …", _MODEL_NAME, cls._device)
                cls._model = YOLO(model_path)  # task inferred from file for .engine

                # .engine / .onnx are already compiled for GPU — skip .to()
                _is_pt = model_path.endswith(".pt")
                if _is_pt:
                    cls._model.to(cls._device)

                # Warmup: one dummy pass so first real frame isn't slow
                dummy = np.zeros((INPUT_SIZE, INPUT_SIZE, 3), dtype=np.uint8)
                cls._model(dummy, verbose=False, device=0 if not _is_pt else cls._device)
                cls._model_ok = True
                logger.info("YOLOv8-Pose loaded successfully (device=%s, format=%s)",
                            cls._device, "TRT" if model_path.endswith(".engine") else "PyTorch")
            except Exception as exc:
                logger.error("Failed to load YOLOv8-Pose model: %s", exc, exc_info=True)
                cls._model_ok = False
        return cls._model_ok

    # ── Main inference entry point ────────────────────────────────────────────
    @classmethod
    def process_frame(
        cls,
        frame: np.ndarray,
        camera_role: str = "lateral",
        prev_bbox: Optional[tuple[int, int, int, int]] = None,
    ) -> dict:
        """
        Run YOLOv8-Pose on *frame* and return a result dict compatible with
        the existing camera_pose router and angle-calculation functions.

        Returns
        -------
        annotated_frame    : np.ndarray  – BGR frame with skeleton overlay
        keypoints          : list[25]    – (x,y,conf) or None, Body-25 layout
        angles             : dict        – joint angles (degrees)
        keypoints_detected : int         – 0 = no valid person
        processing_time_ms : float
        person_bbox        : (x1,y1,x2,y2) | None – for next-frame crop hint
        error              : str | None
        """
        t0 = time.perf_counter()

        if not cls.load_model() or cls._model is None:
            return _empty_result(frame, "YOLOv8 model not loaded")

        h, w = frame.shape[:2]

        _is_trt = _MODEL_NAME.endswith(".engine")
        predict_kwargs = dict(
            imgsz=INPUT_SIZE,
            conf=_CONF_THRESHOLD,
            iou=_IOU_THRESHOLD,
            device=0 if _is_trt else cls._device,
            verbose=False,
        )
        if not _is_trt and cls._device != "cpu":
            predict_kwargs["quantize"] = "fp16"
        with cls._infer_lock:
            results = cls._model.predict(frame, **predict_kwargs)

        keypoints = _extract_best_person(results, w, h)

        n_detected = sum(1 for kp in keypoints if kp is not None)
        lower_body_ok = (
            sum(1 for i in _LOWER_BODY_JOINTS if keypoints[i] is not None)
            >= _MIN_LOWER_BODY
        )
        detected = n_detected if (lower_body_ok and n_detected >= MIN_KEYPOINTS_TO_DRAW) else 0

        angles: dict = {}
        if detected > 0:
            angles = _calculate_angles(keypoints)
            if camera_role == "frontal":
                angles.update(calculate_frontal_angles(keypoints))
            elif camera_role == "posterior":
                angles.update(calculate_posterior_angles(keypoints))

        annotated = overlay_skeleton(frame.copy(), keypoints)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "annotated_frame":    annotated,
            "keypoints":          keypoints,
            "angles":             angles,
            "keypoints_detected": detected,
            "processing_time_ms": round(elapsed_ms, 1),
            "person_bbox":        _compute_person_bbox(keypoints, w, h),
            "error":              None,
        }


# ── Person selection ──────────────────────────────────────────────────────────

def _extract_best_person(
    results, frame_w: int, frame_h: int
) -> list:
    """
    From YOLO results select the most relevant person and return Body-25 kps.

    Selection strategy: largest bounding-box area (person closest to camera /
    filling most of frame).  In a treadmill scenario there is typically one
    person, so this degenerates to just taking the only detection.
    """
    keypoints_b25: list = [None] * 25

    if not results or len(results) == 0:
        return keypoints_b25

    result = results[0]
    if result.keypoints is None or result.boxes is None:
        return keypoints_b25

    kp_data  = result.keypoints.data   # (N, 17, 3) tensor [x, y, conf]
    boxes    = result.boxes.xyxy       # (N, 4) tensor

    if kp_data is None or len(kp_data) == 0:
        return keypoints_b25

    # Pick person with largest bounding box area
    best_idx = 0
    if len(boxes) > 1:
        areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        best_idx = int(areas.argmax().item())

    kps = kp_data[best_idx]  # (17, 3) — x, y, conf in pixel coords

    # Map COCO-17 → Body-25 slots
    for coco_i, b25_i in _COCO_TO_B25.items():
        x, y, conf = float(kps[coco_i][0]), float(kps[coco_i][1]), float(kps[coco_i][2])
        if conf >= _KP_CONF and 0 <= x < frame_w and 0 <= y < frame_h:
            keypoints_b25[b25_i] = (int(round(x)), int(round(y)), round(conf, 3))

    # Compute derived Body-25 joints (Neck, MidHip) from COCO pairs
    for (c_a, c_b), b25_i in [
        (_COCO_NECK_PAIR,   KP_NECK),
        (_COCO_MIDHIP_PAIR, KP_MID_HIP),
    ]:
        ka = kps[c_a]; kb = kps[c_b]
        ca, cb = float(ka[2]), float(kb[2])
        if ca >= _KP_CONF and cb >= _KP_CONF:
            x = (float(ka[0]) + float(kb[0])) / 2
            y = (float(ka[1]) + float(kb[1])) / 2
            avg_c = (ca + cb) / 2
            if 0 <= x < frame_w and 0 <= y < frame_h:
                keypoints_b25[b25_i] = (int(round(x)), int(round(y)), round(avg_c, 3))
        elif ca >= _KP_CONF:
            x, y = float(ka[0]), float(ka[1])
            keypoints_b25[b25_i] = (int(round(x)), int(round(y)), round(ca, 3))
        elif cb >= _KP_CONF:
            x, y = float(kb[0]), float(kb[1])
            keypoints_b25[b25_i] = (int(round(x)), int(round(y)), round(cb, 3))

    return keypoints_b25


# ── Helper functions ──────────────────────────────────────────────────────────

def _empty_result(frame: np.ndarray, error: str) -> dict:
    return {
        "annotated_frame":    frame,
        "keypoints":          [None] * 25,
        "angles":             {},
        "keypoints_detected": 0,
        "processing_time_ms": 0.0,
        "person_bbox":        None,
        "error":              error,
    }


def _compute_person_bbox(
    keypoints: list, frame_w: int, frame_h: int, margin: float = 0.22
) -> Optional[tuple[int, int, int, int]]:
    pts = [(kp[0], kp[1]) for kp in keypoints if kp is not None]
    if len(pts) < 4:
        return None
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    bw = max(max(xs) - min(xs), 1); bh = max(max(ys) - min(ys), 1)
    x1 = max(0,       int(min(xs) - margin * bw))
    x2 = min(frame_w, int(max(xs) + margin * bw))
    y1 = max(0,       int(min(ys) - margin * bh))
    y2 = min(frame_h, int(max(ys) + margin * bh))
    if (x2 - x1) < frame_w * 0.10 or (y2 - y1) < frame_h * 0.10:
        return None
    return (x1, y1, x2, y2)


# ── Angle calculation ─────────────────────────────────────────────────────────

def _pt(keypoints: list, idx: int) -> Optional[np.ndarray]:
    kp = keypoints[idx]
    return np.array([kp[0], kp[1]], dtype=float) if kp is not None else None


def _angle_at(
    p1: Optional[np.ndarray],
    vertex: Optional[np.ndarray],
    p2: Optional[np.ndarray],
) -> Optional[float]:
    if p1 is None or vertex is None or p2 is None:
        return None
    v1, v2 = p1 - vertex, p2 - vertex
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return None
    cos_a = np.dot(v1, v2) / (n1 * n2)
    return float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0))))


def _segment_angle_from_vertical(
    proximal: Optional[np.ndarray],
    distal: Optional[np.ndarray],
) -> Optional[float]:
    """Angle (°) of segment proximal→distal relative to downward vertical [0,1].

    0° = perfectly vertical (straight down in pixel space).
    Increases as segment tilts forward/backward/sideways.
    Used for shank inclination as a proxy for ankle dorsiflexion.
    """
    if proximal is None or distal is None:
        return None
    seg = distal - proximal
    norm = np.linalg.norm(seg)
    if norm < 1e-6:
        return None
    cos_a = np.dot(seg / norm, np.array([0.0, 1.0]))
    return float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0))))


def _knee_flexion_signed(
    hip: Optional[np.ndarray],
    knee: Optional[np.ndarray],
    ankle: Optional[np.ndarray],
    facing_sign: float,
) -> Optional[float]:
    """Knee flexion/extension CÓ DẤU. 0° = duỗi thẳng hoàn toàn (hip-knee-ankle
    thẳng hàng). Dương = gập (đa số ROM khi đi). Âm = duỗi quá mức
    (hyperextension) — hiếm, biên độ nhỏ, nhưng NTU có ghi nhận giá trị âm cho
    peak_ext_deg nên cần biểu diễn được (trước đây _angle_at dùng arccos →
    luôn không âm, không thể ra hyperextension — cùng lớp lỗi đã sửa ở hông).

    Kỹ thuật giống _hip_flexion_trunk(): so góc có dấu giữa hướng "cẳng chân
    tiếp tục thẳng theo đùi" (mốc 0°) và vector cẳng chân thực tế, dùng
    cross-product lấy dấu, nhân facing_sign để chuẩn hoá theo hướng quay mặt.

    LƯU Ý: chưa kiểm chứng với video thật — cần verify: duỗi thẳng → ~0°,
    gập gối khi bước → dương. Nếu dấu ngược, đảo dấu trong hàm này.
    """
    if any(x is None for x in [hip, knee, ankle]) or facing_sign == 0.0:
        return None
    thigh_vec = knee - hip
    thigh_norm = float(np.linalg.norm(thigh_vec))
    if thigh_norm < 1e-6:
        return None
    thigh_dir = thigh_vec / thigh_norm

    shank_vec = ankle - knee
    shank_norm = float(np.linalg.norm(shank_vec))
    if shank_norm < 1e-6:
        return None
    shank_dir = shank_vec / shank_norm

    # Điểm ảo nếu cẳng chân tiếp tục thẳng theo hướng đùi — mốc 0° (duỗi thẳng).
    straight_ref = knee + thigh_dir
    magnitude = _angle_at(straight_ref, knee, ankle)
    if magnitude is None:
        return None

    cross = thigh_dir[0] * shank_dir[1] - thigh_dir[1] * shank_dir[0]
    sign = 1.0 if cross >= 0 else -1.0

    return round(sign * facing_sign * magnitude, 1)


def _facing_sign(keypoints: list) -> float:
    """+1.0 nếu người quay mặt về phía +x khung hình, -1.0 nếu quay mặt -x,
    0.0 nếu không xác định được (thiếu keypoint mũi/tai).

    Suy từ vị trí mũi so với tai (nhìn nghiêng — lateral view): mũi lệch về
    phía nào so với tai thì mặt hướng về phía đó. Cần thiết để chuẩn hoá dấu
    góc hông — không thể biết gập(+)/duỗi(-) nếu không biết người đang quay
    mặt hướng nào trong khung hình (xem _hip_flexion_trunk).
    """
    nose = _pt(keypoints, KP_NOSE)
    ear = _pt(keypoints, KP_L_EAR)
    if ear is None:
        ear = _pt(keypoints, KP_R_EAR)
    if nose is None or ear is None:
        return 0.0
    return 1.0 if nose[0] > ear[0] else -1.0


def _hip_flexion_trunk(
    neck: Optional[np.ndarray],
    mid_hip: Optional[np.ndarray],
    hip: Optional[np.ndarray],
    knee: Optional[np.ndarray],
    facing_sign: float,
) -> Optional[float]:
    """Hip flexion/extension CÓ DẤU, dùng trục thân người (trunk axis) làm mốc.

    Trước đây dùng _angle_at() (arccos → luôn không âm, [0°,180°]) nên góc hông
    từ camera không bao giờ ra được số âm — không thể biểu diễn duỗi hông
    (extension) như quy ước NTU/thiết bị vật lý (flexion dương, extension âm;
    xem angle_convention.hip trong ntu_kinematics_metadata.json — cùng lớp lỗi
    vừa sửa ở firmware/main.c::read_angles_calibrated).

    Cách tính: lấy góc có dấu giữa hướng "thẳng xuống dọc thân" (down_ref — mốc
    0° khi đứng thẳng, đùi thẳng xuống) và vector đùi (hip→knee). Dấu suy từ
    cross-product giữa 2 vector đó trong mặt phẳng ảnh, rồi nhân với
    facing_sign để dấu luôn là gập(+)/duỗi(-) đúng nghĩa bất kể người quay mặt
    hướng nào trong khung hình.

    LƯU Ý: chưa kiểm chứng được với video thật (không có camera/hardware khi
    sửa) — cần verify: đứng thẳng → gần 0°, đá chân ra trước (gập) → dương,
    đưa chân ra sau (duỗi) → âm. Nếu dấu bị ngược, đảo dấu ở _facing_sign().
    """
    if any(x is None for x in [neck, mid_hip, hip, knee]) or facing_sign == 0.0:
        return None
    trunk_vec = neck - mid_hip
    trunk_norm = float(np.linalg.norm(trunk_vec))
    if trunk_norm < 1e-6:
        return None
    trunk_unit = trunk_vec / trunk_norm

    thigh_vec = knee - hip
    thigh_norm = float(np.linalg.norm(thigh_vec))
    if thigh_norm < 1e-6:
        return None

    # Điểm ảo "thẳng xuống" từ hip dọc trục thân — mốc 0° (đứng thẳng).
    down_ref = hip - trunk_unit
    magnitude = _angle_at(down_ref, hip, knee)
    if magnitude is None:
        return None

    down_dir = -trunk_unit
    thigh_dir = thigh_vec / thigh_norm
    cross = down_dir[0] * thigh_dir[1] - down_dir[1] * thigh_dir[0]
    sign = -1.0 if cross >= 0 else 1.0

    return round(sign * facing_sign * magnitude, 1)


def _calculate_angles(keypoints: list) -> dict:
    p = lambda i: _pt(keypoints, i)

    # Trunk references
    neck = p(KP_NECK)
    if neck is None:
        ls, rs = p(KP_L_SHOULDER), p(KP_R_SHOULDER)
        if ls is not None and rs is not None:
            neck = (ls + rs) / 2.0

    mid_hip = p(KP_MID_HIP)
    if mid_hip is None:
        lh, rh = p(KP_L_HIP), p(KP_R_HIP)
        if lh is not None and rh is not None:
            mid_hip = (lh + rh) / 2.0

    facing_sign = _facing_sign(keypoints)

    angles: dict = {
        # Knee flexion/extension CÓ DẤU (xem _knee_flexion_signed).
        "left_knee":  _knee_flexion_signed(p(KP_L_HIP),  p(KP_L_KNEE),  p(KP_L_ANKLE), facing_sign),
        "right_knee": _knee_flexion_signed(p(KP_R_HIP),  p(KP_R_KNEE),  p(KP_R_ANKLE), facing_sign),
        # Hip flexion/extension CÓ DẤU dùng trục thân người (xem _hip_flexion_trunk).
        "left_hip":  _hip_flexion_trunk(neck, mid_hip, p(KP_L_HIP), p(KP_L_KNEE), facing_sign),
        "right_hip": _hip_flexion_trunk(neck, mid_hip, p(KP_R_HIP), p(KP_R_KNEE), facing_sign),
        # Shank inclination (camera-only metric — no ankle potentiometer on physical device).
        # angle of shin segment (knee→ankle) from vertical = proxy for dorsiflexion.
        # NOT comparable with physical ankle — kept for live display only.
        "left_ankle":  _segment_angle_from_vertical(p(KP_L_KNEE), p(KP_L_ANKLE)),
        "right_ankle": _segment_angle_from_vertical(p(KP_R_KNEE), p(KP_R_ANKLE)),
    }

    neck, mid_hip = p(KP_NECK), p(KP_MID_HIP)
    if neck is not None and mid_hip is not None:
        trunk = neck - mid_hip
        norm = np.linalg.norm(trunk)
        if norm > 1e-6:
            cos_a = np.dot(trunk / norm, np.array([0.0, -1.0]))
            angles["trunk_inclination"] = float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0))))
        else:
            angles["trunk_inclination"] = None
    else:
        angles["trunk_inclination"] = None

    lk, rk = angles["left_knee"], angles["right_knee"]
    if lk is not None and rk is not None and (abs(lk) + abs(rk)) > 0:
        angles["knee_symmetry_index"] = round(200.0 * abs(lk - rk) / (abs(lk) + abs(rk)), 1)
    else:
        angles["knee_symmetry_index"] = None

    return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in angles.items()}


# ── Frontal / posterior camera angles ────────────────────────────────────────

def calculate_frontal_angles(keypoints: list) -> dict:
    p = lambda i: _pt(keypoints, i)
    angles: dict = {}

    for side, hip_idx, knee_idx in [
        ("left",  KP_L_HIP, KP_L_KNEE),
        ("right", KP_R_HIP, KP_R_KNEE),
    ]:
        hip, knee = p(hip_idx), p(knee_idx)
        if hip is not None and knee is not None:
            thigh = knee - hip
            norm = np.linalg.norm(thigh)
            if norm > 1e-6:
                cos_a = np.dot(thigh / norm, np.array([0.0, 1.0]))
                angles[f"{side}_hip_abduction"] = round(
                    float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0)))), 1)
            else:
                angles[f"{side}_hip_abduction"] = None
        else:
            angles[f"{side}_hip_abduction"] = None

    neck, mid_hip = p(KP_NECK), p(KP_MID_HIP)
    if neck is not None and mid_hip is not None:
        trunk = neck - mid_hip
        norm = np.linalg.norm(trunk)
        if norm > 1e-6:
            cos_a = np.dot(trunk / norm, np.array([0.0, -1.0]))
            angles["lateral_trunk_lean"] = round(
                float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0)))), 1)
        else:
            angles["lateral_trunk_lean"] = None
    else:
        angles["lateral_trunk_lean"] = None

    for side, hip_idx, knee_idx, ankle_idx in [
        ("left",  KP_L_HIP,  KP_L_KNEE,  KP_L_ANKLE),
        ("right", KP_R_HIP,  KP_R_KNEE,  KP_R_ANKLE),
    ]:
        angles[f"{side}_knee_valgus"] = _angle_at(p(hip_idx), p(knee_idx), p(ankle_idx))

    return angles


def calculate_posterior_angles(keypoints: list) -> dict:
    p = lambda i: _pt(keypoints, i)
    angles: dict = {}

    l_hip, r_hip = p(KP_L_HIP), p(KP_R_HIP)
    if l_hip is not None and r_hip is not None:
        pelvis = r_hip - l_hip
        norm = np.linalg.norm(pelvis)
        if norm > 1e-6:
            cos_a = np.dot(pelvis / norm, np.array([1.0, 0.0]))
            angles["pelvic_obliquity"] = round(
                float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0)))), 1)
        else:
            angles["pelvic_obliquity"] = None
    else:
        angles["pelvic_obliquity"] = None

    mid_hip = p(KP_MID_HIP)
    for side, hip_idx in [("left", KP_L_HIP), ("right", KP_R_HIP)]:
        hip = p(hip_idx)
        if hip is not None and mid_hip is not None:
            angles[f"{side}_hip_drop"] = round(float(hip[1] - mid_hip[1]), 1)
        else:
            angles[f"{side}_hip_drop"] = None

    # Foot progression: no heel/toe in COCO-17 — use ankle→knee direction reversed
    for side, ankle_idx, knee_idx in [
        ("left",  KP_L_ANKLE, KP_L_KNEE),
        ("right", KP_R_ANKLE, KP_R_KNEE),
    ]:
        ankle, knee = p(ankle_idx), p(knee_idx)
        if ankle is not None and knee is not None:
            # foot direction approximated as downward extension of shank
            foot_dir = ankle - knee
            norm = np.linalg.norm(foot_dir)
            if norm > 1e-6:
                cos_a = np.dot(foot_dir / norm, np.array([0.0, 1.0]))
                angles[f"{side}_foot_progression"] = round(
                    float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0)))), 1)
            else:
                angles[f"{side}_foot_progression"] = None
        else:
            angles[f"{side}_foot_progression"] = None

    return angles


# ── Skeleton overlay ──────────────────────────────────────────────────────────

def overlay_skeleton(frame: np.ndarray, keypoints: list) -> np.ndarray:
    if not keypoints:
        return frame
    if sum(1 for kp in keypoints if kp is not None) < MIN_KEYPOINTS_TO_DRAW:
        return frame
    if sum(1 for i in _LOWER_BODY_JOINTS if i < len(keypoints) and keypoints[i] is not None) < _MIN_LOWER_BODY:
        return frame

    for (a, b), color in _SKELETON:
        kp_a = keypoints[a] if a < len(keypoints) else None
        kp_b = keypoints[b] if b < len(keypoints) else None
        if kp_a and kp_b:
            cv2.line(frame, (kp_a[0], kp_a[1]), (kp_b[0], kp_b[1]),
                     color, 3, cv2.LINE_AA)

    for kp in keypoints:
        if kp:
            cv2.circle(frame, (kp[0], kp[1]), 7, (255, 255, 255), -1)
            cv2.circle(frame, (kp[0], kp[1]), 5, (30, 30, 30), -1)

    return frame
