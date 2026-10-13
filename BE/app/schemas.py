"""
Pydantic schemas — request/response contracts for the API.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models import UserRole, SessionStatus, GaitPhase, AuthProvider, Sex


# ===========================================================================
# Token / Auth
# ===========================================================================

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenData(BaseModel):
    username: Optional[str] = None


# ===========================================================================
# User
# ===========================================================================

class UserSignup(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=6)


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=6)
    role: UserRole = UserRole.user


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    role: Optional[UserRole] = None


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=128)
    age: Optional[int] = Field(None, ge=18, le=90)
    sex: Optional[Sex] = None
    weight_kg: Optional[float] = Field(None, ge=20.0, le=100.0)
    height_cm: Optional[float] = Field(None, ge=50.0, le=200.0)


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    auth_provider: AuthProvider
    avatar_url: Optional[str]
    age: Optional[int]
    sex: Optional[Sex]
    weight_kg: Optional[float]
    height_cm: Optional[float]
    profile_complete: bool = False
    created_at: datetime

    @model_validator(mode='after')
    def compute_profile_complete(self):
        self.profile_complete = all([
            self.age is not None,
            self.sex is not None,
            self.weight_kg is not None,
            self.height_cm is not None,
        ])
        return self

    class Config:
        from_attributes = True


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)


# ===========================================================================
# Measurement Session
# ===========================================================================

class SessionCreate(BaseModel):
    com_port: Optional[str] = None
    baud_rate: int = 115200
    walk_distance_m: Optional[float] = None
    notes: Optional[str] = None


class QuickStartRequest(BaseModel):
    com_port: str = Field(..., min_length=1)
    baud_rate: int = Field(115200, ge=9600)
    notes: Optional[str] = None


class PrepareRequest(BaseModel):
    com_port: str = Field(..., min_length=1)
    baud_rate: int = Field(115200, ge=9600)
    notes: Optional[str] = None


class SessionUpdate(BaseModel):
    com_port: Optional[str] = None
    baud_rate: Optional[int] = None
    walk_distance_m: Optional[float] = None
    notes: Optional[str] = None


class SessionOut(BaseModel):
    id: int
    session_code: str
    user_id: int
    status: SessionStatus
    com_port: Optional[str]
    baud_rate: int
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    walk_distance_m: Optional[float]
    notes: Optional[str]
    created_at: datetime
    reading_count: Optional[int] = None

    class Config:
        from_attributes = True


class SessionDetail(SessionOut):
    user: Optional[UserOut]
    analysis: Optional["GaitAnalysisOut"] = None

    class Config:
        from_attributes = True


# ===========================================================================
# Sensor Reading
# ===========================================================================

class SensorReadingIn(BaseModel):
    timestamp_ms: float
    # 4 góc khớp (deg, flexion dương)
    left_hip: Optional[float] = None
    left_knee: Optional[float] = None
    right_hip: Optional[float] = None
    right_knee: Optional[float] = None
    # FSR — 2 cảm biến/chân (raw ADC, A4-A7)
    left_force_1: Optional[float] = None
    left_force_2: Optional[float] = None
    right_force_1: Optional[float] = None
    right_force_2: Optional[float] = None
    # IMU accelerometer (m/s² hoặc g)
    accel_x: Optional[float] = None
    accel_y: Optional[float] = None
    accel_z: Optional[float] = None
    # IMU gyroscope (deg/s)
    gyro_x: Optional[float] = None
    gyro_y: Optional[float] = None
    gyro_z: Optional[float] = None
    # IMU magnetometer (μT hoặc raw)
    magn_x: Optional[float] = None
    magn_y: Optional[float] = None
    magn_z: Optional[float] = None
    # Gait phase — Arduino có thể tự tính, hoặc để BE compute từ force
    phase_left: GaitPhase = GaitPhase.unknown
    phase_right: GaitPhase = GaitPhase.unknown
    signal_quality: Optional[int] = None


class SensorReadingOut(SensorReadingIn):
    id: int
    session_id: int
    recorded_at: datetime

    class Config:
        from_attributes = True


# ===========================================================================
# Real-time WebSocket message
# ===========================================================================

class RealtimeMessage(BaseModel):
    type: str
    session_id: int
    data: Dict[str, Any]


# ===========================================================================
# Gait Analysis
# ===========================================================================

class JointStats(BaseModel):
    mean: float
    std: float
    min: float
    max: float
    rom: float


class GaitCycleMetrics(BaseModel):
    count: int
    avg_duration_s: float
    cadence_steps_per_min: float
    stance_ratio: float


class GaitAnalysisOut(BaseModel):
    id: int
    session_id: int
    analyzed_at: datetime
    left_hip_stats: Optional[JointStats]
    left_knee_stats: Optional[JointStats]
    right_hip_stats: Optional[JointStats]
    right_knee_stats: Optional[JointStats]
    left_gait_cycle: Optional[GaitCycleMetrics]
    right_gait_cycle: Optional[GaitCycleMetrics]
    symmetry_index_hip: Optional[float]
    symmetry_index_knee: Optional[float]
    pelvis_sway_stats: Optional[Dict[str, Any]] = None
    pelvis_gyro_stats: Optional[Dict[str, Any]] = None
    magn_stats: Optional[Dict[str, Any]] = None
    fsr_stats: Optional[Dict[str, Any]] = None
    double_support: Optional[Dict[str, Any]] = None
    gait_score: Optional[float]
    score_breakdown: Optional[Dict[str, Any]] = None
    remarks: Optional[str]
    reference_evaluations: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


# ===========================================================================
# Chart data
# ===========================================================================

class ChartSeries(BaseModel):
    name: str
    data: List[float]


class TimeSeriesChart(BaseModel):
    session_id: int
    timestamps_ms: List[float]
    series: List[ChartSeries]


class BarChartItem(BaseModel):
    label: str
    value: float
    unit: str = "deg"


class SummaryChart(BaseModel):
    session_id: int
    items: List[BarChartItem]


# ===========================================================================
# Serial port info
# ===========================================================================

class SerialPortInfo(BaseModel):
    port: str
    description: str
    hwid: str


class CH340DetectResponse(BaseModel):
    port: str
    description: str
    hwid: str
    detected_by: str  # 'vid_pid' | 'description'


class SerialConnectRequest(BaseModel):
    session_id: int
    com_port: str
    baud_rate: int = 115200


class SerialStatusResponse(BaseModel):
    session_id: int
    connected: bool
    com_port: Optional[str]
    baud_rate: Optional[int]
    samples_received: int


# ===========================================================================
# Reference-norms comparison (Z-score vs NTU / Yishun / Chinese)
# ===========================================================================

class ReferenceEvaluation(BaseModel):
    parameter: str
    measured: Optional[float]
    unit: str
    dataset: str                  # 'ntu' | 'yishun' | 'chinese' | 'none'
    mean: Optional[float]
    sd: Optional[float]
    z: Optional[float]
    band: str                     # 'normal' | 'borderline' | 'abnormal' | 'unavailable'
    age_group: Optional[str] = None
    n: Optional[int] = None
    note: Optional[str] = None


class ReferenceComparison(BaseModel):
    session_id: int
    age: int
    sex: str
    walk_distance_m: Optional[float]
    kinematic: List[ReferenceEvaluation]
    spatiotemporal: List[ReferenceEvaluation]
    summary: Dict[str, int]       # counts per band: normal / borderline / abnormal / unavailable


# ===========================================================================
# CameraSession
# ===========================================================================

class CameraSessionCreate(BaseModel):
    recorded_at: datetime
    duration_s: Optional[float] = None
    frames: Optional[int] = None
    cameras_used: int = 1
    analysis: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class CameraSessionOut(BaseModel):
    id: int
    user_id: int
    recorded_at: datetime
    duration_s: Optional[float]
    frames: Optional[int]
    cameras_used: int
    analysis: Optional[Dict[str, Any]]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ===========================================================================
# Pagination
# ===========================================================================

class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[Any]


# Update forward refs
TokenResponse.model_rebuild()
SessionDetail.model_rebuild()
