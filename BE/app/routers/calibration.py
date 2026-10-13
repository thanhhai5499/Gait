"""
Camera calibration REST endpoints.

GET  /api/calibration           — read current calibration values
PUT  /api/calibration           — update camera / treadmill parameters
POST /api/calibration/test      — compute pixel_per_cm from two reference points

pixel_per_cm derivation
-----------------------
Given two reference points measured in pixels (P1, P2) and their known real-world
distance in cm, pixel_per_cm = pixel_distance / real_cm.

This is used by GaitCycleDetector to convert ankle pixel displacement → step_length_cm.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "camera_calibration.yaml"

router = APIRouter(prefix="/api/calibration", tags=["Calibration"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class CameraCalib(BaseModel):
    height_cm:     Optional[float] = Field(None, ge=10, le=500)
    distance_cm:   Optional[float] = Field(None, ge=10, le=2000)
    tilt_deg:      Optional[float] = Field(None, ge=-45, le=45)
    pan_deg:       Optional[float] = Field(None, ge=-90, le=90)
    pixel_per_cm:  Optional[float] = Field(None, ge=0.1, le=500)


class TreadmillCalib(BaseModel):
    width_cm:       Optional[float] = Field(None, ge=20, le=200)
    belt_speed_kmh: Optional[float] = Field(None, ge=0, le=20)


class CalibUpdate(BaseModel):
    lateral:   Optional[CameraCalib]   = None
    frontal:   Optional[CameraCalib]   = None
    posterior: Optional[CameraCalib]   = None
    treadmill: Optional[TreadmillCalib] = None


class PixelPoint(BaseModel):
    x: float
    y: float


class TestCalibRequest(BaseModel):
    camera: str = Field(..., pattern="^(lateral|frontal|posterior)$")
    point1: PixelPoint
    point2: PixelPoint
    real_distance_cm: float = Field(..., gt=0, le=500,
                                    description="Known real-world distance between the two points (cm)")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        with open(_CONFIG_PATH, "r") as f:
            data = yaml.safe_load(f) or {}
        # Ensure expected structure
        data.setdefault("cameras", {})
        for cam in ("lateral", "frontal", "posterior"):
            data["cameras"].setdefault(cam, {})
        data.setdefault("treadmill", {})
        return data
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="calibration.yaml not found on server")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load calibration: {exc}")


def _save(data: dict) -> None:
    try:
        with open(_CONFIG_PATH, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save calibration: {exc}")


def _auto_pixel_per_cm(cam: dict) -> Optional[float]:
    """
    Estimate pixel_per_cm from camera geometry and a 640-px horizontal FOV.
    This is a rough approximation; use POST /test for measured accuracy.

    pixel_per_cm ≈ focal_length_px / distance_cm
    where focal_length_px ≈ image_width / (2 * tan(hfov/2))
    Brio 300 typical HFOV ≈ 78°
    """
    h   = cam.get("height_cm")
    d   = cam.get("distance_cm")
    if not h or not d:
        return None
    try:
        hfov_rad = math.radians(78.0)
        focal_px = 1280 / (2 * math.tan(hfov_rad / 2))
        return round(focal_px / d, 3)
    except Exception:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="Get current camera calibration")
def get_calibration():
    """Return the current calibration YAML as JSON, with auto-computed pixel_per_cm filled in."""
    data = _load()
    # Fill in auto-computed pixel_per_cm where not explicitly set
    for cam_name, cam_data in data.get("cameras", {}).items():
        if cam_data.get("pixel_per_cm") is None:
            auto = _auto_pixel_per_cm(cam_data)
            cam_data["pixel_per_cm_auto"] = auto  # separate key so user knows it's estimated
    return data


@router.put("", summary="Update camera calibration parameters")
def update_calibration(update: CalibUpdate):
    """
    Partially update calibration parameters.
    Only fields that are non-None in the request body are updated.
    """
    data = _load()

    for cam_name in ("lateral", "frontal", "posterior"):
        patch: Optional[CameraCalib] = getattr(update, cam_name)
        if patch is None:
            continue
        cam = data["cameras"].setdefault(cam_name, {})
        for field, val in patch.model_dump(exclude_none=True).items():
            cam[field] = val

    if update.treadmill:
        tm = data.setdefault("treadmill", {})
        for field, val in update.treadmill.model_dump(exclude_none=True).items():
            tm[field] = val

    _save(data)
    logger.info("Calibration updated: %s", update.model_dump(exclude_none=True))
    return {"status": "ok", "calibration": data}


@router.post("/test", summary="Compute pixel_per_cm from two reference points")
def test_calibration(req: TestCalibRequest):
    """
    Given two pixel coordinates of a known real-world distance (e.g. treadmill width),
    compute pixel_per_cm and optionally save it to the calibration file.

    Example: place two markers 50 cm apart on the treadmill belt,
    click their pixel coordinates, and POST here.
    """
    dx = req.point2.x - req.point1.x
    dy = req.point2.y - req.point1.y
    pixel_distance = math.sqrt(dx * dx + dy * dy)

    if pixel_distance < 10:
        raise HTTPException(
            status_code=400,
            detail="Pixel distance too small — ensure both points are far enough apart in the image"
        )

    pixel_per_cm = round(pixel_distance / req.real_distance_cm, 3)
    logger.info(
        "Calibration test — camera=%s px_dist=%.1f real_cm=%.1f px/cm=%.3f",
        req.camera, pixel_distance, req.real_distance_cm, pixel_per_cm
    )

    return {
        "camera":          req.camera,
        "pixel_distance":  round(pixel_distance, 1),
        "real_distance_cm": req.real_distance_cm,
        "pixel_per_cm":    pixel_per_cm,
        "hint":            f"Call PUT /api/calibration with {req.camera}.pixel_per_cm={pixel_per_cm} to save",
    }
