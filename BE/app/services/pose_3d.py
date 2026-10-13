"""
3D keypoint back-projection and joint angle computation using RealSense depth.

Back-projection formula (pinhole model):
    X_m = (x_px - cx) * d / fx
    Y_m = (y_px - cy) * d / fy
    Z_m = d                        (depth in metres, camera optical axis)

where (fx, fy, cx, cy) come from RealSenseReader.get_intrinsics() and
d is the median depth in a small patch around the keypoint (mm → m).

Compared to 2D angle computation this eliminates perspective distortion caused
by the subject not being exactly perpendicular to the camera plane (~5-10° error
in typical clinical treadmill setups becomes ~1-2° with 3D).
"""
from __future__ import annotations

import numpy as np

# Body-25 keypoint indices used for 3D angle computation
_KP_NECK      = 1
_KP_MID_HIP   = 8
_KP_R_HIP     = 9
_KP_R_KNEE    = 10
_KP_R_ANKLE   = 11
_KP_L_HIP     = 12
_KP_L_KNEE    = 13
_KP_L_ANKLE   = 14

_DEPTH_PATCH_R    = 4      # px radius for median depth sampling
_MIN_VALID_DEPTH  = 0.15   # m  — closer than this is likely noise
_MAX_VALID_DEPTH  = 8.0    # m  — farther than this is unreliable for joints
_MIN_PATCH_POINTS = 3      # minimum valid pixels for a reliable depth sample


def keypoints_to_3d(
    keypoints_2d: list,
    depth_raw: np.ndarray,
    intrinsics: dict,
) -> list:
    """
    Convert Body-25 2D keypoints to metric 3D coordinates using the depth map.

    Parameters
    ----------
    keypoints_2d : Body-25 list, each element (x_px, y_px, conf) or None
    depth_raw    : uint16 ndarray shape (H, W), values in mm, aligned to colour
    intrinsics   : dict with keys fx, fy, cx, cy (from RealSenseReader.get_intrinsics)

    Returns
    -------
    list of 25 elements, each (X_m, Y_m, Z_m, conf) or None
    """
    fx = intrinsics["fx"]
    fy = intrinsics["fy"]
    cx = intrinsics["cx"]
    cy = intrinsics["cy"]
    h, w = depth_raw.shape
    r = _DEPTH_PATCH_R

    result: list = []
    for kp in keypoints_2d:
        if kp is None:
            result.append(None)
            continue

        x_px, y_px, conf = float(kp[0]), float(kp[1]), float(kp[2])
        ix, iy = int(round(x_px)), int(round(y_px))

        x1 = max(0, ix - r); x2 = min(w, ix + r + 1)
        y1 = max(0, iy - r); y2 = min(h, iy + r + 1)
        patch = depth_raw[y1:y2, x1:x2]
        valid = patch[patch > 0]

        if len(valid) < _MIN_PATCH_POINTS:
            result.append(None)
            continue

        d = float(np.median(valid)) / 1000.0  # mm → m
        if not (_MIN_VALID_DEPTH <= d <= _MAX_VALID_DEPTH):
            result.append(None)
            continue

        X = (x_px - cx) * d / fx
        Y = (y_px - cy) * d / fy
        result.append((X, Y, d, conf))

    return result


def angle_3d(p1: tuple, vertex: tuple, p2: tuple) -> float | None:
    """
    Compute the joint angle (degrees) at *vertex* formed by p1 → vertex → p2.

    Parameters
    ----------
    p1, vertex, p2 : (X, Y, Z, ...) tuples; only the first 3 components are used

    Returns
    -------
    float angle in degrees, or None if vectors are degenerate
    """
    v1 = np.array(p1[:3], dtype=float) - np.array(vertex[:3], dtype=float)
    v2 = np.array(p2[:3], dtype=float) - np.array(vertex[:3], dtype=float)

    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 < 1e-6 or n2 < 1e-6:
        return None

    cos_a = float(np.dot(v1, v2) / (n1 * n2))
    return round(float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0)))), 1)


def compute_angles_3d(keypoints_3d: list) -> dict:
    """
    Compute all lateral gait angles in 3D from a Body-25 3D keypoint list.

    Returns a dict with keys like "left_knee_3d", "right_knee_3d", etc.
    Only angles where all three required keypoints have valid depth are included.
    """
    def kp(idx: int):
        return keypoints_3d[idx] if idx < len(keypoints_3d) else None

    angles: dict = {}

    def _add(name: str, i1: int, iv: int, i2: int) -> None:
        p1 = kp(i1); v = kp(iv); p2 = kp(i2)
        if p1 and v and p2:
            a = angle_3d(p1, v, p2)
            if a is not None:
                angles[name] = a

    # Convert to flexion convention: 0° = full extension, positive = flexion.
    # Raw 3D angle: 180° when standing, decreases with flexion → flexion = 180° - raw.
    def _add_flex(name: str, i1: int, iv: int, i2: int) -> None:
        p1 = kp(i1); v = kp(iv); p2 = kp(i2)
        if p1 and v and p2:
            a = angle_3d(p1, v, p2)
            if a is not None:
                angles[name] = round(180.0 - a, 1)

    def _add_hip_flex(name: str, hip_idx: int, knee_idx: int) -> None:
        """Hip flexion using 3D trunk-axis direction (mid_hip→neck) as reference.

        Avoids the ~5-10° bias of using the absolute neck position when trunk
        leans forward during walking — the same fix applied in the 2D pipeline.
        """
        neck_3d    = kp(_KP_NECK)
        mid_hip_3d = kp(_KP_MID_HIP)
        hip_3d     = kp(hip_idx)
        knee_3d    = kp(knee_idx)
        if not all([neck_3d, mid_hip_3d, hip_3d, knee_3d]):
            return
        trunk_vec  = np.array(neck_3d[:3]) - np.array(mid_hip_3d[:3])
        trunk_norm = float(np.linalg.norm(trunk_vec))
        if trunk_norm < 1e-6:
            return
        trunk_unit = trunk_vec / trunk_norm
        # Virtual reference point above each hip along the trunk axis
        hip_ref_3d = tuple(np.array(hip_3d[:3]) + trunk_unit * trunk_norm) + (1.0,)
        a = angle_3d(hip_ref_3d, hip_3d, knee_3d)
        if a is not None:
            angles[name] = round(180.0 - a, 1)

    _add_flex("left_knee_3d",  _KP_L_HIP, _KP_L_KNEE, _KP_L_ANKLE)
    _add_flex("right_knee_3d", _KP_R_HIP, _KP_R_KNEE, _KP_R_ANKLE)
    _add_hip_flex("left_hip_3d",  _KP_L_HIP, _KP_L_KNEE)
    _add_hip_flex("right_hip_3d", _KP_R_HIP, _KP_R_KNEE)

    # Trunk inclination: angle between neck→mid_hip segment and downward vertical (0,1,0).
    # RealSense camera coordinates: X=right, Y=down, Z=forward → vertical = (0,1,0).
    neck = kp(_KP_NECK); midhip = kp(_KP_MID_HIP)
    if neck and midhip:
        trunk_vec = np.array(midhip[:3]) - np.array(neck[:3])
        n = float(np.linalg.norm(trunk_vec))
        if n > 1e-6:
            cos_a = float(np.dot(trunk_vec / n, np.array([0.0, 1.0, 0.0])))
            angles["trunk_inclination_3d"] = round(
                float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0)))), 1
            )

    # Shank (tibial) inclination: angle of knee→ankle segment from downward vertical.
    # Proxy for ankle dorsiflexion — 0° = shin vertical, increases as tibia tilts.
    # COCO-17 has no heel/toe points so this is the best available ankle metric.
    def _shank_incl(knee_idx: int, ankle_idx: int, name: str) -> None:
        kn = kp(knee_idx); an = kp(ankle_idx)
        if not kn or not an:
            return
        seg = np.array(an[:3]) - np.array(kn[:3])
        n = float(np.linalg.norm(seg))
        if n < 1e-6:
            return
        cos_a = float(np.dot(seg / n, np.array([0.0, 1.0, 0.0])))
        angles[name] = round(float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0)))), 1)

    _shank_incl(_KP_L_KNEE, _KP_L_ANKLE, "left_ankle_3d")
    _shank_incl(_KP_R_KNEE, _KP_R_ANKLE, "right_ankle_3d")

    return angles
