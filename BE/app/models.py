"""
SQLAlchemy ORM models — Code-First approach.
"""
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, Text, Enum as SAEnum, JSON
)
from sqlalchemy.orm import relationship
import enum

from app.database import Base
from app.utils import now_vn


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    admin = "admin"   # quản trị hệ thống: quản lý user, xem toàn bộ dữ liệu
    user = "user"     # người dùng thông thường: đo, xem, phân tích dữ liệu


class Sex(str, enum.Enum):
    male = "male"
    female = "female"


class AuthProvider(str, enum.Enum):
    local = "local"
    google = "google"


class SessionStatus(str, enum.Enum):
    idle = "idle"
    recording = "recording"
    paused = "paused"
    completed = "completed"


class GaitPhase(str, enum.Enum):
    stance = "stance"
    swing = "swing"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=False)
    full_name = Column(String(128), nullable=False)
    hashed_password = Column(String(256), nullable=True)
    role = Column(SAEnum(UserRole), default=UserRole.user, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    auth_provider = Column(SAEnum(AuthProvider), default=AuthProvider.local, nullable=False)
    google_id = Column(String(128), unique=True, nullable=True)
    avatar_url = Column(String(512), nullable=True)

    # Thông tin cá nhân — cần thiết cho phân tích dataset NTU/Yishun/Chinese
    age = Column(Integer, nullable=True)
    sex = Column(SAEnum(Sex), nullable=True)
    weight_kg = Column(Float, nullable=True)
    height_cm = Column(Float, nullable=True)

    created_at = Column(DateTime, default=now_vn)
    updated_at = Column(DateTime, default=now_vn, onupdate=now_vn)

    sessions = relationship("MeasurementSession", back_populates="user",
                            foreign_keys="MeasurementSession.user_id",
                            cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user",
                                  cascade="all, delete-orphan")
    camera_sessions = relationship("CameraSession", back_populates="user",
                                   cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# RefreshToken — server-side tracking để revoke khi logout
# ---------------------------------------------------------------------------

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=now_vn)

    user = relationship("User", back_populates="refresh_tokens")


# ---------------------------------------------------------------------------
# MeasurementSession  (one session = one walking trial by one user)
# ---------------------------------------------------------------------------

class MeasurementSession(Base):
    __tablename__ = "measurement_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_code = Column(String(32), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    status = Column(SAEnum(SessionStatus), default=SessionStatus.idle, nullable=False)
    com_port = Column(String(32), nullable=True)
    baud_rate = Column(Integer, default=115200)

    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)

    walk_distance_m = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now_vn)

    user = relationship("User", back_populates="sessions", foreign_keys=[user_id])
    readings = relationship("SensorReading", back_populates="session",
                            cascade="all, delete-orphan")
    analysis = relationship("GaitAnalysis", back_populates="session",
                            uselist=False, cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# SensorReading
# ---------------------------------------------------------------------------

class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("measurement_sessions.id",
                                            ondelete="CASCADE"), nullable=False, index=True)

    timestamp_ms = Column(Float, nullable=False)
    recorded_at = Column(DateTime, default=now_vn)

    # Joint angles (degrees, flexion +)
    left_hip = Column(Float, nullable=True)
    left_knee = Column(Float, nullable=True)
    right_hip = Column(Float, nullable=True)
    right_knee = Column(Float, nullable=True)

    # Foot pressure (raw ADC — A4/A5 trái, A6/A7 phải)
    # 2 FSR mỗi chân — phase auto-computed từ trung bình nếu phase_* không gửi
    left_force_1 = Column(Float, nullable=True)   # A4
    left_force_2 = Column(Float, nullable=True)   # A5
    right_force_1 = Column(Float, nullable=True)  # A6
    right_force_2 = Column(Float, nullable=True)  # A7

    # IMU (I2C sda_20, scl_21) — accelerometer (m/s² hoặc g)
    accel_x = Column(Float, nullable=True)
    accel_y = Column(Float, nullable=True)
    accel_z = Column(Float, nullable=True)

    # IMU — gyroscope (deg/s)
    gyro_x = Column(Float, nullable=True)
    gyro_y = Column(Float, nullable=True)
    gyro_z = Column(Float, nullable=True)

    # IMU — magnetometer (μT hoặc raw)
    magn_x = Column(Float, nullable=True)
    magn_y = Column(Float, nullable=True)
    magn_z = Column(Float, nullable=True)

    phase_left = Column(SAEnum(GaitPhase), default=GaitPhase.unknown)
    phase_right = Column(SAEnum(GaitPhase), default=GaitPhase.unknown)
    signal_quality = Column(Integer, nullable=True)

    session = relationship("MeasurementSession", back_populates="readings")


# ---------------------------------------------------------------------------
# GaitAnalysis
# ---------------------------------------------------------------------------

class GaitAnalysis(Base):
    __tablename__ = "gait_analyses"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("measurement_sessions.id",
                                            ondelete="CASCADE"), unique=True, nullable=False)
    analyzed_at = Column(DateTime, default=now_vn)

    left_hip_stats = Column(JSON, nullable=True)
    left_knee_stats = Column(JSON, nullable=True)
    right_hip_stats = Column(JSON, nullable=True)
    right_knee_stats = Column(JSON, nullable=True)

    left_gait_cycle = Column(JSON, nullable=True)
    right_gait_cycle = Column(JSON, nullable=True)

    symmetry_index_hip = Column(Float, nullable=True)
    symmetry_index_knee = Column(Float, nullable=True)

    # Pelvic sway từ accelerometer cột sống
    # JSON: { x_mediolateral: {mean,std,rms,range_p2p},
    #         y_anteroposterior: {...},
    #         z_vertical: {...} }   ← z là chỉ số chính
    pelvis_sway_stats = Column(JSON, nullable=True)

    # Pelvic gyroscope statistics
    # JSON: { x_roll: {mean,std,rms,range_p2p},
    #         y_pitch: {...},
    #         z_yaw: {...} }
    pelvis_gyro_stats = Column(JSON, nullable=True)

    # Magnetometer statistics
    # JSON: { x: {...}, y: {...}, z: {...}, heading: {mean_deg, std_deg, ...} }
    magn_stats = Column(JSON, nullable=True)

    # FSR force analysis: { left: {heel, toe, loading_rate}, right: {...}, symmetry: {...} }
    fsr_stats = Column(JSON, nullable=True)

    # Double support: { ratio, ratio_pct, n_bouts, avg_duration_ms }
    double_support = Column(JSON, nullable=True)

    gait_score = Column(Float, nullable=True)
    # Chi tiết cách tính gait_score: { base_score, total_penalty, final_score,
    # items: [{ label, penalty, max_penalty, value, norm, unit, formula }] }
    score_breakdown = Column(JSON, nullable=True)
    remarks = Column(Text, nullable=True)

    # Z-score so với 3 dataset chuẩn (NTU / Yishun / Chinese)
    # JSON: {"kinematic": [...], "spatiotemporal": [...], "summary": {...}}
    reference_evaluations = Column(JSON, nullable=True)

    session = relationship("MeasurementSession", back_populates="analysis")


# ---------------------------------------------------------------------------
# CameraSession — kết quả phân tích từ camera, gắn với IMU session
# ---------------------------------------------------------------------------

class CameraSession(Base):
    __tablename__ = "camera_sessions"

    id                     = Column(Integer, primary_key=True, index=True)
    user_id                = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                    nullable=False, index=True)
    recorded_at            = Column(DateTime, nullable=False)
    duration_s             = Column(Float, nullable=True)
    frames                 = Column(Integer, nullable=True)
    cameras_used           = Column(Integer, default=1)
    analysis               = Column(JSON, nullable=True)
    notes                  = Column(Text, nullable=True)
    created_at             = Column(DateTime, default=now_vn)

    user                = relationship("User", back_populates="camera_sessions")
