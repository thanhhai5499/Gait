"""
Gait Analysis API — entry point
================================
Run with:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Swagger UI: http://localhost:8000/docs
ReDoc:      http://localhost:8000/redoc
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app import models
from app.auth.router import router as auth_router, limiter as auth_limiter
from app.routers.sessions import router as sessions_router
from app.routers.measurements import router as measurements_router
from app.routers.analysis import router as analysis_router
from app.routers.serial import router as serial_router
from app.routers.oauth import router as oauth_router
from app.routers.camera_pose import router as camera_pose_router
from app.routers.camera_sessions import router as camera_sessions_router
from app.routers.calibration import router as calibration_router
from app.routers.group_analysis import router as group_analysis_router
from app.services.serial_reader import ws_manager, serial_registry
from app.auth.utils import hash_password

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Gait Analysis API (%s)...", settings.APP_VERSION)
    # Schema được quản lý bởi Alembic — chạy `alembic upgrade head` trước khi start
    _seed_admin_user()
    yield
    logger.info("Shutting down — stopping all serial readers...")
    serial_registry.stop_all()


def _seed_admin_user():
    """Create default admin account on first run if no users exist."""
    from app.database import SessionLocal
    from sqlalchemy.exc import IntegrityError
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            admin = models.User(
                username="admin",
                email="admin@gait.local",
                full_name="Administrator",
                hashed_password=hash_password("admin1234"),
                role=models.UserRole.admin,
            )
            db.add(admin)
            db.commit()
            logger.info("Default admin created — change the password immediately!")
            logger.warning("Doi mat khau admin truoc khi deploy!")
    except IntegrityError:
        db.rollback()
        logger.info("Admin user already exists, skipping seed.")
    except Exception as e:
        db.rollback()
        logger.error("Failed to seed admin user: %s", e)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## Gait Analysis Backend API

Hệ thống đo và phân tích các góc khớp chân trong quá trình đi lại.

### Tính năng
- **Quản lý bệnh nhân** và phiên đo
- **Thu thập dữ liệu real-time** qua cổng COM (serial)
- **Phân tích dáng đi**: ROM, chu trình, chỉ số cân xứng
- **Biểu đồ**: time-series, ROM, symmetry, phase distribution
- **So sánh** hai phiên đo (theo dõi tiến trình)
- **Xuất CSV** dữ liệu thô

### Định dạng dữ liệu cảm biến (serial — 18 fields cố định)
```
timestamp_ms,
left_hip,left_knee,right_hip,right_knee,         # 4 góc (deg) — A0-A3
left_force_1,left_force_2,                       # FSR trái (ADC) — A4,A5
right_force_1,right_force_2,                     # FSR phải (ADC) — A6,A7
accel_x,accel_y,accel_z,                         # Gia tốc IMU (I2C sda_20,scl_21)
gyro_x,gyro_y,gyro_z,                            # Con quay hồi chuyển (deg/s)
magn_x,magn_y,magn_z                             # Từ trường (μT)
```
- Phase tự tính trên BE từ trung bình 2 FSR/chân (ngưỡng stance/swing)
- Ví dụ: `1234,12.3,-5.6,11.1,-4.5,512,498,510,505,0.02,-0.04,9.81,0.5,-0.3,0.1,230,120,45`
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = auth_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(measurements_router)
app.include_router(analysis_router)
app.include_router(serial_router)
app.include_router(oauth_router)
app.include_router(camera_pose_router)
app.include_router(camera_sessions_router)
app.include_router(calibration_router)
app.include_router(group_analysis_router)


# ---------------------------------------------------------------------------
# WebSocket — real-time sensor streaming
# ---------------------------------------------------------------------------

@app.websocket("/ws/realtime/{session_id}")
async def websocket_realtime(
    websocket: WebSocket,
    session_id: int,
    token: str = Query(..., description="JWT access token"),
    db: Session = Depends(get_db),
):
    """
    Connect to receive real-time sensor readings for a session.

    Send a valid JWT as query param: ws://host/ws/realtime/1?token=<jwt>

    Message types received:
      - {"type": "reading", "session_id": N, "data": {SensorReadingIn fields}}
      - {"type": "status",  "session_id": N, "data": {"message": "..."}}
      - {"type": "error",   "session_id": N, "data": {"message": "..."}}
    """
    # Authenticate the WebSocket connection via query token
    from app.auth.utils import decode_token
    try:
        token_data = decode_token(token)
        user = db.query(models.User).filter(
            models.User.username == token_data.username
        ).first()
        if not user or not user.is_active:
            await websocket.close(code=4001)
            return
    except Exception:
        await websocket.close(code=4001)
        return

    # Verify session exists
    session = db.query(models.MeasurementSession).filter(
        models.MeasurementSession.id == session_id
    ).first()
    if not session:
        await websocket.close(code=4004)
        return

    await ws_manager.connect(session_id, websocket)

    # Send welcome message
    await websocket.send_json({
        "type": "status",
        "session_id": session_id,
        "data": {
            "message": f"Connected to session {session_id} ({session.session_code})",
            "status": session.status.value,
        },
    })

    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data.strip() == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id, websocket)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/", tags=["System"])
def root():
    return {
        "message": "Gait Analysis API is running",
        "docs": "/docs",
        "health": "/health",
    }
