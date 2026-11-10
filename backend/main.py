import base64
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from backend.config import (
    BASE_DIR,
    JWT_ALGORITHM,
    JWT_EXPIRE_HOURS,
    JWT_SECRET,
    SAMPLE_FACES_DIR,
)
from backend.controllers.admin_controller import AdminDashboardController
from backend.controllers.kiosk_controller import KioskController
from backend.database import (
    ACTIVE_DB_ENGINE_TYPE,
    ACTIVE_DB_URL,
    db_session_scope,
    get_db,
    init_db,
)
from backend.models import ActionLog, Locker, StorageSession, User
from backend.schemas import (
    BackupPinRetrieveRequest,
    CallStaffRequest,
    CreateLockerRequest,
    CreateStaffRequest,
    ForceOpenLockerRequest,
    IoTStatusPayload,
    LoginRequest,
    ThresholdUpdateRequest,
    UpdateLockerStatusRequest,
    UpdateStaffRequest,
)
from backend.services.face_service import FaceRecognitionService
from backend.services.locker_service import BusinessLogicError, LockerManagerService
from backend.services.mqtt_service import MQTTService
from iot_esp32.esp32_simulator import VirtualESP32Twin
from scripts.generate_sample_faces import generate_all_sample_faces

# --- Global Service Singletons ---
face_service = FaceRecognitionService()
mqtt_service = MQTTService()
esp32_twin = VirtualESP32Twin(
    publish_status_fn=lambda topic, payload: mqtt_service.onMessageReceived(
        topic, payload
    )
)
mqtt_service.register_virtual_esp32_listener(esp32_twin.on_command_received)

# API Latency tracking (Section 7.4)
api_latencies_ms: List[float] = []


def _handle_mqtt_status_update(validated_payload: Dict[str, Any]) -> None:
    """Callback invoked whenever MQTTService receives a valid status message from ESP32."""
    with db_session_scope() as db:
        locker_svc = LockerManagerService(db, face_service, mqtt_service)
        locker_svc.handleDoorStateChange(
            LockerID=validated_payload["locker_id"],
            doorState=validated_payload["door"],
            lockState=validated_payload.get("lock_state", "LOCKED"),
            alert=validated_payload.get("alert", "NONE"),
        )


mqtt_service.set_status_callback(_handle_mqtt_status_update)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    generate_all_sample_faces(SAMPLE_FACES_DIR)
    mqtt_service.connect(timeout_sec=1.5)
    esp32_twin.start_background_loop(interval_sec=0.25)
    yield
    esp32_twin.stop_background_loop()
    mqtt_service.disconnect()


app = FastAPI(
    title="IoT Smart Locker with AI Face Recognition API",
    description=(
        "Backend FastAPI cho Hệ thống Tủ đồ Thông minh tích hợp Nhận diện Khuôn mặt "
        "(YOLOv5 + 128D Face Embedding, MySQL, MQTT, ESP32 Wokwi)"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def record_api_latency(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    api_latencies_ms.append(elapsed_ms)
    if len(api_latencies_ms) > 500:
        del api_latencies_ms[:-500]
    response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    return response


@app.exception_handler(BusinessLogicError)
async def business_error_handler(request: Request, exc: BusinessLogicError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "errorCode": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )


# --- Authentication Helpers ---
def create_jwt_token(user: User) -> str:
    payload = {
        "sub": str(user.userID),
        "username": user.username,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(decoded["sub"])
        return db.query(User).filter(User.userID == user_id).first()
    except Exception:
        return None


# ============================================================================
# 1. AUTHENTICATION ENDPOINTS (FR-04, Section 2.2)
# ============================================================================
@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username.strip()).first()
    if user is None or not user.authenticate(req.password):
        raise BusinessLogicError(
            code="INVALID_CREDENTIALS",
            message="Tên đăng nhập hoặc mật khẩu không chính xác.",
            status_code=401,
        )
    token = create_jwt_token(user)
    return {
        "success": True,
        "token": token,
        "user": user.to_dict(),
    }


@app.get("/api/auth/me")
def get_me(current_user: Optional[User] = Depends(get_current_user)):
    if current_user is None:
        raise BusinessLogicError(
            code="UNAUTHORIZED",
            message="Phiên đăng nhập không hợp lệ hoặc đã hết hạn.",
            status_code=401,
        )
    return {"success": True, "user": current_user.to_dict()}


# ============================================================================
# 2. KIOSK ENDPOINTS (FR-01 Store, FR-02 Retrieve, Call Staff)
# ============================================================================
@app.get("/api/kiosk/sample-faces")
def list_sample_faces():
    generate_all_sample_faces(SAMPLE_FACES_DIR)
    catalog = [
        {
            "filename": "customer_01_checkin.jpg",
            "label": "Khách hàng 1 (Nguyễn Văn An) - Ảnh Gửi đồ",
            "person": "Customer 01",
        },
        {
            "filename": "customer_01_checkout.jpg",
            "label": "Khách hàng 1 (Nguyễn Văn An) - Ảnh Nhận đồ (Khớp <= 0.45)",
            "person": "Customer 01",
        },
        {
            "filename": "customer_02_checkin.jpg",
            "label": "Khách hàng 2 (Trần Thị Bình) - Ảnh Gửi đồ",
            "person": "Customer 02",
        },
        {
            "filename": "customer_02_checkout.jpg",
            "label": "Khách hàng 2 (Trần Thị Bình) - Ảnh Nhận đồ (Khớp <= 0.45)",
            "person": "Customer 02",
        },
        {
            "filename": "customer_03_checkin.jpg",
            "label": "Khách hàng 3 (Lê Hoàng Cường) - Ảnh Gửi đồ",
            "person": "Customer 03",
        },
        {
            "filename": "customer_03_checkout.jpg",
            "label": "Khách hàng 3 (Lê Hoàng Cường) - Ảnh Nhận đồ (Khớp <= 0.45)",
            "person": "Customer 03",
        },
        {
            "filename": "customer_04_stranger.jpg",
            "label": "Khách hàng 4 (Phạm Minh Dũng) - Người lạ chưa gửi đồ (TC-04)",
            "person": "Customer 04 (Stranger)",
        },
        {
            "filename": "invalid_no_face.jpg",
            "label": "Ảnh lỗi / Không có khuôn mặt (Kiểm thử Liveness)",
            "person": "Invalid",
        },
    ]
    return {"success": True, "samples": catalog}


@app.get("/api/kiosk/sample-faces/{filename}")
def get_sample_face_image(filename: str):
    fpath = SAMPLE_FACES_DIR / filename
    if not fpath.exists():
        generate_all_sample_faces(SAMPLE_FACES_DIR)
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="Sample face not found")
    return FileResponse(str(fpath), media_type="image/jpeg")


@app.post("/api/kiosk/store")
async def kiosk_store_item(
    file: Optional[UploadFile] = File(default=None),
    sample_name: Optional[str] = Form(default=None),
    customer_label: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    if file is not None:
        img_bytes = await file.read()
        label = customer_label or file.filename
    elif sample_name:
        fpath = SAMPLE_FACES_DIR / sample_name
        if not fpath.exists():
            generate_all_sample_faces(SAMPLE_FACES_DIR)
        if not fpath.exists():
            raise BusinessLogicError(
                code="SAMPLE_NOT_FOUND",
                message=f"Không tìm thấy ảnh mẫu: {sample_name}",
                status_code=404,
            )
        img_bytes = fpath.read_bytes()
        label = customer_label or sample_name
    else:
        raise BusinessLogicError(
            code="MISSING_IMAGE",
            message="Vui lòng chụp ảnh khuôn mặt hoặc chọn ảnh mẫu để gửi đồ.",
            status_code=400,
        )

    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    kiosk_ctrl = KioskController(face_service, locker_svc)
    return kiosk_ctrl.handleStoreRequest(img_bytes, customer_label=label)


@app.post("/api/kiosk/retrieve")
async def kiosk_retrieve_item(
    file: Optional[UploadFile] = File(default=None),
    sample_name: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    if file is not None:
        img_bytes = await file.read()
    elif sample_name:
        fpath = SAMPLE_FACES_DIR / sample_name
        if not fpath.exists():
            generate_all_sample_faces(SAMPLE_FACES_DIR)
        if not fpath.exists():
            raise BusinessLogicError(
                code="SAMPLE_NOT_FOUND",
                message=f"Không tìm thấy ảnh mẫu: {sample_name}",
                status_code=404,
            )
        img_bytes = fpath.read_bytes()
    else:
        raise BusinessLogicError(
            code="MISSING_IMAGE",
            message="Vui lòng chụp ảnh khuôn mặt hoặc chọn ảnh mẫu để nhận đồ.",
            status_code=400,
        )

    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    kiosk_ctrl = KioskController(face_service, locker_svc)
    return kiosk_ctrl.handleRetrieveRequest(img_bytes)


@app.post("/api/kiosk/retrieve-pin")
def kiosk_retrieve_by_pin(
    req: BackupPinRetrieveRequest,
    db: Session = Depends(get_db),
):
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    locker, session = locker_svc.retrieveItemByBackupPin(
        locker_number=req.lockerNumber,
        backup_pin=req.backupPin,
    )
    return {
        "success": True,
        "action": "RETRIEVE_PIN",
        "message": f"Xác thực mã PIN dự phòng thành công! Đã mở Hộc tủ #{locker.LockerNumber}.",
        "locker": locker.to_dict(),
        "session": session.to_dict(),
    }


@app.post("/api/kiosk/call-staff")
def kiosk_call_staff(
    req: CallStaffRequest,
    db: Session = Depends(get_db),
):
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    kiosk_ctrl = KioskController(face_service, locker_svc)
    return kiosk_ctrl.handleCallStaff(
        locker_number=req.lockerNumber,
        reason=req.reason,
    )


# ============================================================================
# 3. LOCKER & SESSION MANAGEMENT ENDPOINTS (FR-03, FR-08)
# ============================================================================
@app.get("/api/lockers")
def get_all_lockers(db: Session = Depends(get_db)):
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    return {
        "success": True,
        "lockers": admin_ctrl.getAllLockersRealtime(),
    }


@app.post("/api/lockers")
def create_locker(
    req: CreateLockerRequest,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    return admin_ctrl.createLocker(
        actor=current_user,
        locker_number=req.LockerNumber,
        status=req.status,
    )


@app.put("/api/lockers/{locker_id}/status")
def update_locker_status(
    locker_id: int,
    req: UpdateLockerStatusRequest,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    return admin_ctrl.updateLockerStatus(
        LockerID=locker_id,
        status=req.status,
        actor=current_user,
        door_state=req.doorState,
    )


@app.delete("/api/lockers/{locker_id}")
def delete_locker(
    locker_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    return admin_ctrl.deleteLocker(actor=current_user, LockerID=locker_id)


@app.post("/api/lockers/{locker_id}/force-open")
def force_open_locker(
    locker_id: int,
    req: ForceOpenLockerRequest,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        raise BusinessLogicError(
            code="UNAUTHORIZED",
            message="Vui lòng đăng nhập tài khoản Nhân viên hoặc Quản trị viên để mở khóa khẩn cấp.",
            status_code=401,
        )
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    return admin_ctrl.forceOpenLocker(
        adminID=current_user.userID,
        LockerID=locker_id,
        reason=req.reason,
        release_session=req.releaseSession,
    )


@app.get("/api/sessions")
def list_sessions(
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(StorageSession)
    if status:
        q = q.filter(StorageSession.status == status.upper())
    sessions = q.order_by(StorageSession.checkInAt.desc()).limit(100).all()
    return {
        "success": True,
        "sessions": [s.to_dict() for s in sessions],
    }


# ============================================================================
# 4. STAFF MANAGEMENT & LOG ENDPOINTS (FR-04, FR-05, TC-10)
# ============================================================================
@app.get("/api/logs")
def get_action_logs(
    actionType: Optional[str] = Query(default=None),
    LockerID: Optional[int] = Query(default=None),
    userID: Optional[int] = Query(default=None),
    sessionID: Optional[int] = Query(default=None),
    limit: int = Query(default=200),
    db: Session = Depends(get_db),
):
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    criteria = {
        "actionType": actionType,
        "LockerID": LockerID,
        "userID": userID,
        "sessionID": sessionID,
        "limit": limit,
    }
    return {
        "success": True,
        "logs": admin_ctrl.getActionLogs(criteria),
    }


@app.get("/api/staff")
def list_staff(
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    return {
        "success": True,
        "staff": admin_ctrl.getAllStaff(actor=current_user),
    }


@app.post("/api/staff")
def create_staff(
    req: CreateStaffRequest,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        raise BusinessLogicError(
            code="UNAUTHORIZED",
            message="Vui lòng đăng nhập quyền ADMIN.",
            status_code=401,
        )
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    return admin_ctrl.createStaff(req.model_dump(), actor=current_user)


@app.put("/api/staff/{user_id}")
def update_staff(
    user_id: int,
    req: UpdateStaffRequest,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        raise BusinessLogicError(
            code="UNAUTHORIZED",
            message="Vui lòng đăng nhập quyền ADMIN.",
            status_code=401,
        )
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    return admin_ctrl.updateStaff(
        userID=user_id,
        staffData=req.model_dump(exclude_none=True),
        actor=current_user,
    )


@app.delete("/api/staff/{user_id}")
def delete_staff(
    user_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        raise BusinessLogicError(
            code="UNAUTHORIZED",
            message="Vui lòng đăng nhập quyền ADMIN.",
            status_code=401,
        )
    locker_svc = LockerManagerService(db, face_service, mqtt_service)
    admin_ctrl = AdminDashboardController(locker_svc, mqtt_service)
    return admin_ctrl.deleteStaff(userID=user_id, actor=current_user)


# ============================================================================
# 5. IoT ESP32 WOKWI SIMULATION & MQTT ENDPOINTS (FR-06, FR-07, TC-06, TC-07, TC-09)
# ============================================================================
@app.get("/api/iot/esp32")
def get_esp32_snapshot():
    esp32_twin.tick()
    return {
        "success": True,
        "esp32": esp32_twin.get_snapshot(),
        "mqtt": {
            **mqtt_service.get_metrics_summary(),
            "recentPublished": mqtt_service.published_messages[-15:],
            "recentReceived": mqtt_service.received_messages[-15:],
        },
    }


@app.post("/api/iot/esp32/door")
def toggle_esp32_door_switch(
    locker_id: int = Query(..., ge=1),
    open_state: bool = Query(..., description="True = OPEN, False = CLOSED"),
):
    pin_state = esp32_twin.set_door_switch(locker_id=locker_id, is_open=open_state)
    return {
        "success": True,
        "message": f"Cảm biến cửa Hộc tủ #{locker_id} chuyển sang {'OPEN' if open_state else 'CLOSED'}.",
        "pinState": pin_state,
        "esp32": esp32_twin.get_snapshot(),
    }


@app.post("/api/iot/esp32/advance-time")
def advance_esp32_millis(
    milliseconds: int = Query(..., ge=100, le=120000),
):
    esp32_twin.advance_millis(milliseconds)
    return {
        "success": True,
        "message": f"Đã tua nhanh bộ đếm millis() trên ESP32 thêm +{milliseconds} ms.",
        "esp32": esp32_twin.get_snapshot(),
    }


@app.post("/api/iot/mqtt/status")
def ingest_mqtt_status(payload: IoTStatusPayload):
    validated = mqtt_service.onMessageReceived(
        mqtt_service.statusTopic,
        payload.model_dump_json(),
    )
    return {"success": True, "validated": validated}


@app.post("/api/iot/mqtt/simulate-offline")
def set_mqtt_offline_mode(offline: bool = Query(...)):
    mqtt_service.set_simulate_offline(offline)
    return {
        "success": True,
        "simulateOffline": mqtt_service.simulate_offline,
        "brokerMode": mqtt_service.broker_mode,
    }


# ============================================================================
# 6. SYSTEM METRICS, THRESHOLD & DEMO RESET (Section 7.4)
# ============================================================================
@app.get("/api/metrics")
def get_system_metrics(db: Session = Depends(get_db)):
    total_lockers = db.query(Locker).count()
    available_lockers = db.query(Locker).filter(Locker.status == "AVAILABLE").count()
    occupied_lockers = db.query(Locker).filter(Locker.status == "OCCUPIED").count()
    maintenance_lockers = db.query(Locker).filter(Locker.status == "MAINTENANCE").count()
    open_doors = db.query(Locker).filter(Locker.doorState == "OPEN").count()
    active_alerts = (
        db.query(Locker).filter(Locker.alertState == "DOOR_OPEN_TIMEOUT").count()
    )

    active_sessions = (
        db.query(StorageSession).filter(StorageSession.status == "ACTIVE").count()
    )
    completed_sessions = (
        db.query(StorageSession).filter(StorageSession.status == "COMPLETED").count()
    )
    force_opened_sessions = (
        db.query(StorageSession).filter(StorageSession.status == "FORCE_OPENED").count()
    )
    total_logs = db.query(ActionLog).count()
    door_alert_logs = (
        db.query(ActionLog).filter(ActionLog.actionType == "DOOR_ALERT").count()
    )

    avg_api_ms = (
        round(sum(api_latencies_ms) / len(api_latencies_ms), 2)
        if api_latencies_ms
        else 0.0
    )

    return {
        "success": True,
        "database": {
            "engineType": ACTIVE_DB_ENGINE_TYPE,
            "url": ACTIVE_DB_URL.split("@")[-1] if "@" in ACTIVE_DB_URL else ACTIVE_DB_URL,
        },
        "lockers": {
            "total": total_lockers,
            "available": available_lockers,
            "occupied": occupied_lockers,
            "maintenance": maintenance_lockers,
            "openDoors": open_doors,
            "activeAlerts": active_alerts,
        },
        "sessions": {
            "active": active_sessions,
            "completed": completed_sessions,
            "forceOpened": force_opened_sessions,
        },
        "logs": {
            "total": total_logs,
            "doorAlerts": door_alert_logs,
        },
        "ai": face_service.get_metrics_summary(),
        "mqtt": mqtt_service.get_metrics_summary(),
        "api": {
            "totalRequests": len(api_latencies_ms),
            "avgLatencyMs": avg_api_ms,
        },
    }


@app.put("/api/settings/threshold")
def update_face_threshold(
    req: ThresholdUpdateRequest,
    current_user: Optional[User] = Depends(get_current_user),
):
    if current_user is not None and not current_user.hasPermission("ADMIN"):
        raise BusinessLogicError(
            code="FORBIDDEN",
            message="Chỉ Quản trị viên (ADMIN) mới được điều chỉnh ngưỡng AI.",
            status_code=403,
        )
    face_service.distanceThreshold = round(float(req.distanceThreshold), 3)
    return {
        "success": True,
        "distanceThreshold": face_service.distanceThreshold,
    }


@app.post("/api/system/reset-demo")
def reset_demo_state(db: Session = Depends(get_db)):
    """Resets all sessions and returns lockers 1..5 to AVAILABLE and locker 6 to MAINTENANCE."""
    mqtt_service.set_simulate_offline(False)
    for sess in db.query(StorageSession).filter(StorageSession.status == "ACTIVE").all():
        sess.completeSession()

    for lk in db.query(Locker).all():
        lk.status = "MAINTENANCE" if lk.LockerNumber == 6 else "AVAILABLE"
        lk.doorState = "CLOSED"
        lk.lockState = "LOCKED"
        lk.alertState = "NONE"

    for lid in list(esp32_twin.lockers.keys()):
        esp32_twin.lockers[lid].relay_high = False
        esp32_twin.lockers[lid].door_open = False
        esp32_twin.lockers[lid].timeout_alert_active = False
    esp32_twin.buzzer_active = False
    esp32_twin._update_lcd("SMART LOCKER RDY", "L1:CLSD  L2:CLSD")

    db.commit()
    return {
        "success": True,
        "message": "Đã đặt lại trạng thái hệ thống về mặc định sẵn sàng kiểm thử.",
    }

