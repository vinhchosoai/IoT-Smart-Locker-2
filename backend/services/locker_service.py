import random
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from backend.models import ActionLog, Locker, StorageSession, User
from backend.repositories import (
    LockerRepository,
    LogRepository,
    SessionRepository,
    UserRepository,
)
from backend.services.face_service import FaceRecognitionService
from backend.services.mqtt_service import MQTTService


class BusinessLogicError(Exception):
    """Structured domain exception for Smart Locker business rules."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class LockerManagerService:
    """
    Core Business Logic Service (Chapter 2, Chapter 4.3 Class Diagram & Chapter 5.3).

    Attributes (per Class Diagram):
        - lockerRepo: LockerRepository
        - sessionRepo: SessionRepository
        - logRepo: LogRepository
        - faceService: FaceRecognitionService
        - mqttService: MQTTService

    Methods (per Class Diagram):
        - allocateAvailableLocker(): Locker
        - storeItem(embedding: list, imageUrl: string): StorageSession
        - retrieveItem(embedding: list): Locker
        - triggerEmergencyUnlock(adminID: integer, LockerID: integer, reason: string): boolean
        - handleDoorStateChange(LockerID: integer, doorState: string): void
    """

    def __init__(
        self,
        db: Session,
        face_service: FaceRecognitionService,
        mqtt_service: MQTTService,
    ):
        self.db = db
        self.lockerRepo = LockerRepository(db)
        self.sessionRepo = SessionRepository(db)
        self.logRepo = LogRepository(db)
        self.userRepo = UserRepository(db)
        self.faceService = face_service
        self.mqttService = mqtt_service

    def allocateAvailableLocker(self) -> Optional[Locker]:
        """
        Class Diagram method: + allocateAvailableLocker(): Locker
        Finds the first locker compartment with status == 'AVAILABLE' and alertState == 'NONE'.
        """
        return self.lockerRepo.find_first_available()

    def storeItem(
        self,
        embedding: List[float],
        imageUrl: str,
        customer_label: Optional[str] = None,
    ) -> Tuple[StorageSession, Locker, float]:
        """
        Class Diagram method: + storeItem(embedding: list, imageUrl: string): StorageSession
        Implements FR-01 & Section 2.3 & Section 2.5:
          1. Anti-duplicate check against all ACTIVE sessions (distance <= threshold 0.45).
          2. Allocate available locker (status == AVAILABLE).
          3. Send MQTT OPEN command to ESP32 (abort transaction if MQTT fails - TC-09).
          4. Create ACTIVE StorageSession & update Locker to OCCUPIED.
          5. Write CLIENT_STORE ActionLog.
        """
        active_sessions = self.sessionRepo.get_active_sessions()

        # Step 3 (Section 2.3) & Section 2.5: Check duplicate active session (TC-02)
        dup_session, min_dist = self.faceService.findMatchWithDistance(
            embedding, active_sessions
        )
        if dup_session is not None:
            dup_locker = self.lockerRepo.get_by_id(dup_session.LockerID)
            locker_num = dup_locker.LockerNumber if dup_locker else dup_session.LockerID
            raise BusinessLogicError(
                code="DUPLICATE_ACTIVE_SESSION",
                message=(
                    f"Khuôn mặt này đã có phiên gửi đồ đang hoạt động (ACTIVE) tại hộc tủ số #{locker_num} "
                    f"(khoảng cách đặc trưng = {min_dist:.4f} <= {self.faceService.distanceThreshold}). "
                    "Mỗi khách hàng chỉ được sử dụng 1 hộc tủ cùng lúc."
                ),
                status_code=409,
                details={
                    "existingSessionID": dup_session.sessionID,
                    "LockerID": dup_session.LockerID,
                    "LockerNumber": locker_num,
                    "distance": min_dist,
                },
            )

        # Step 4 (Section 2.3): Find AVAILABLE locker (TC-05)
        locker = self.allocateAvailableLocker()
        if locker is None:
            raise BusinessLogicError(
                code="NO_AVAILABLE_LOCKER",
                message="Hiện tại không còn hộc tủ trống khả dụng (AVAILABLE). Vui lòng thử lại sau.",
                status_code=409,
            )

        # Step 6 (Section 2.3): Publish MQTT OPEN command (TC-09 check)
        mqtt_ok = self.mqttService.publishOpenCommand(
            LockerID=locker.LockerNumber,
            action="OPEN",
            user_type="CUSTOMER",
        )
        if not mqtt_ok:
            raise BusinessLogicError(
                code="MQTT_COMMUNICATION_ERROR",
                message=(
                    "Lỗi giao tiếp MQTT: Không thể gửi lệnh mở khóa đến thiết bị ESP32. "
                    "Hệ thống hủy tạo phiên gửi đồ để đảm bảo toàn vẹn dữ liệu."
                ),
                status_code=503,
            )

        # Step 5 (Section 2.3): Create session & mark locker OCCUPIED
        backup_pin = f"{random.randint(100000, 999999)}"
        session = self.sessionRepo.create_session(
            locker_id=locker.LockerID,
            face_image_url=imageUrl,
            face_embedding=embedding,
            backup_pin=backup_pin,
            customer_label=customer_label,
        )
        locker.updateStatus("OCCUPIED")
        locker.lockState = "UNLOCKED"

        # Step 7 (Section 2.3): Record ActionLog
        dist_note = f"min_dist={min_dist:.4f}" if min_dist is not None else "no_prior_active"
        self.logRepo.record(
            action_type="CLIENT_STORE",
            locker_id=locker.LockerID,
            session_id=session.sessionID,
            note=f"Khách hàng gửi đồ thành công vào Tủ #{locker.LockerNumber} ({dist_note}, PIN={backup_pin})",
        )
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(locker)
        return session, locker, (min_dist if min_dist is not None else -1.0)

    def retrieveItem(
        self,
        embedding: List[float],
    ) -> Tuple[Locker, StorageSession, float]:
        """
        Class Diagram method: + retrieveItem(embedding: list): Locker
        Implements FR-02 & Section 2.4:
          8-9. Match face embedding against all ACTIVE sessions (distance <= 0.45).
          10. If no match found, reject and do NOT send MQTT open command (TC-04).
          11-12. If matched, send MQTT OPEN command for the linked locker (TC-03, TC-09).
          13. Update session to COMPLETED and locker to AVAILABLE.
          14. Write CLIENT_RETRIEVE ActionLog.
        """
        active_sessions = self.sessionRepo.get_active_sessions()
        if not active_sessions:
            raise BusinessLogicError(
                code="NO_ACTIVE_SESSIONS",
                message="Không tìm thấy phiên gửi đồ nào đang hoạt động trong hệ thống.",
                status_code=404,
            )

        matched_session, best_dist = self.faceService.findMatchWithDistance(
            embedding, active_sessions
        )
        if matched_session is None:
            raise BusinessLogicError(
                code="FACE_NOT_MATCHED",
                message=(
                    "Xác thực khuôn mặt thất bại: Không tìm thấy phiên gửi đồ hợp lệ khớp với khuôn mặt này "
                    f"(khoảng cách gần nhất = {best_dist:.4f} > ngưỡng {self.faceService.distanceThreshold}). "
                    "Hệ thống không mở khóa."
                ),
                status_code=401,
                details={
                    "closestDistance": best_dist,
                    "threshold": self.faceService.distanceThreshold,
                },
            )

        locker = self.lockerRepo.get_by_id(matched_session.LockerID)
        if locker is None:
            raise BusinessLogicError(
                code="LOCKER_NOT_FOUND",
                message=f"Không tìm thấy hộc tủ liên kết (LockerID={matched_session.LockerID}).",
                status_code=404,
            )

        # Step 12 (Section 2.4): Send MQTT OPEN command (TC-09 check)
        mqtt_ok = self.mqttService.publishOpenCommand(
            LockerID=locker.LockerNumber,
            action="OPEN",
            user_type="CUSTOMER",
        )
        if not mqtt_ok:
            raise BusinessLogicError(
                code="MQTT_COMMUNICATION_ERROR",
                message=(
                    "Lỗi giao tiếp MQTT: Không thể gửi lệnh mở khóa đến thiết bị ESP32. "
                    "Phiên gửi đồ vẫn được giữ nguyên trạng thái ACTIVE."
                ),
                status_code=503,
            )

        # Step 13 (Section 2.4): Complete session & release locker to AVAILABLE
        matched_session.completeSession()
        locker.updateStatus("AVAILABLE")
        locker.lockState = "UNLOCKED"

        # Step 14 (Section 2.4): Record ActionLog
        self.logRepo.record(
            action_type="CLIENT_RETRIEVE",
            locker_id=locker.LockerID,
            session_id=matched_session.sessionID,
            note=(
                f"Khách hàng nhận đồ thành công tại Tủ #{locker.LockerNumber} "
                f"(distance={best_dist:.4f} <= {self.faceService.distanceThreshold}). "
                "Phiên chuyển sang COMPLETED, tủ giải phóng về AVAILABLE."
            ),
        )
        self.db.commit()
        self.db.refresh(matched_session)
        self.db.refresh(locker)
        return locker, matched_session, float(best_dist or 0.0)

    def retrieveItemByBackupPin(
        self, locker_number: int, backup_pin: str
    ) -> Tuple[Locker, StorageSession]:
        """Fallback retrieval using the backupPin from StorageSession (Class Diagram)."""
        locker = self.lockerRepo.get_by_number(locker_number)
        if locker is None:
            raise BusinessLogicError(
                code="LOCKER_NOT_FOUND",
                message=f"Không tìm thấy hộc tủ số #{locker_number}.",
                status_code=404,
            )
        active_sess = self.sessionRepo.get_active_session_by_locker(locker.LockerID)
        if active_sess is None:
            raise BusinessLogicError(
                code="NO_ACTIVE_SESSION_FOR_LOCKER",
                message=f"Hộc tủ số #{locker_number} hiện không có phiên gửi đồ ACTIVE.",
                status_code=404,
            )
        if not active_sess.backupPin or active_sess.backupPin.strip() != backup_pin.strip():
            raise BusinessLogicError(
                code="INVALID_BACKUP_PIN",
                message="Mã PIN dự phòng không chính xác.",
                status_code=401,
            )

        mqtt_ok = self.mqttService.publishOpenCommand(
            LockerID=locker.LockerNumber,
            action="OPEN",
            user_type="CUSTOMER",
        )
        if not mqtt_ok:
            raise BusinessLogicError(
                code="MQTT_COMMUNICATION_ERROR",
                message="Mất kết nối MQTT. Không thể mở khóa hộc tủ.",
                status_code=503,
            )

        active_sess.completeSession()
        locker.updateStatus("AVAILABLE")
        locker.lockState = "UNLOCKED"
        self.logRepo.record(
            action_type="CLIENT_RETRIEVE",
            locker_id=locker.LockerID,
            session_id=active_sess.sessionID,
            note=f"Khách hàng nhận đồ bằng mã Backup PIN tại Tủ #{locker.LockerNumber}.",
        )
        self.db.commit()
        self.db.refresh(active_sess)
        self.db.refresh(locker)
        return locker, active_sess

    def triggerEmergencyUnlock(
        self,
        adminID: int,
        LockerID: int,
        reason: str = "Mở khóa khẩn cấp theo yêu cầu hỗ trợ",
        release_session: bool = True,
    ) -> Dict[str, Any]:
        """
        Class Diagram method:
        + triggerEmergencyUnlock(adminID: integer, LockerID: integer, reason: string): boolean
        Implements FR-08 & Section 5.3 & TC-08:
        Allows authenticated STAFF or ADMIN to force-open a locker, dispatches MQTT command,
        updates session/locker state per business policy, and writes audit trail to ActionLog.
        """
        user = self.userRepo.get_by_id(adminID)
        if user is None or not user.hasPermission("STAFF"):
            raise BusinessLogicError(
                code="FORBIDDEN",
                message="Tài khoản không có quyền thực hiện mở khóa khẩn cấp.",
                status_code=403,
            )

        locker = self.lockerRepo.get_by_id(LockerID)
        if locker is None:
            locker = self.lockerRepo.get_by_number(LockerID)
        if locker is None:
            raise BusinessLogicError(
                code="LOCKER_NOT_FOUND",
                message=f"Không tìm thấy hộc tủ #{LockerID}.",
                status_code=404,
            )

        mqtt_ok = self.mqttService.publishOpenCommand(
            LockerID=locker.LockerNumber,
            action="OPEN",
            user_type=user.role,
        )
        if not mqtt_ok:
            raise BusinessLogicError(
                code="MQTT_COMMUNICATION_ERROR",
                message="Mất kết nối MQTT: Không thể gửi lệnh mở khóa khẩn cấp tới ESP32.",
                status_code=503,
            )

        active_sess = self.sessionRepo.get_active_session_by_locker(locker.LockerID)
        session_id = active_sess.sessionID if active_sess else None

        if active_sess is not None and release_session:
            active_sess.markForceOpened()
            locker.updateStatus("AVAILABLE")

        locker.lockState = "UNLOCKED"

        log_entry = self.logRepo.record(
            action_type="STAFF_FORCE_OPEN",
            locker_id=locker.LockerID,
            user_id=user.userID,
            session_id=session_id,
            note=f"[{user.role}: {user.username}] Mở khẩn cấp Tủ #{locker.LockerNumber}. Lý do: {reason}",
        )
        self.db.commit()
        self.db.refresh(locker)
        return {
            "success": True,
            "locker": locker.to_dict(),
            "releasedSessionID": session_id if release_session else None,
            "log": log_entry.to_dict(),
        }

    def handleDoorStateChange(
        self,
        LockerID: int,
        doorState: str,
        lockState: Optional[str] = None,
        alert: str = "NONE",
    ) -> Optional[Locker]:
        """
        Class Diagram method:
        + handleDoorStateChange(LockerID: integer, doorState: string): void
        Implements FR-06, FR-07, Section 5.3, TC-06, TC-07:
        Processes status feedback from ESP32 over MQTT topic 'iot_smartlocker_2026/status'.
        """
        locker = self.lockerRepo.get_by_number(LockerID)
        if locker is None:
            locker = self.lockerRepo.get_by_id(LockerID)
        if locker is None:
            return None

        prev_alert = locker.alertState
        locker.updateDoorState(doorState)
        if lockState:
            locker.lockState = lockState.upper().strip()

        norm_alert = (alert or "NONE").upper().strip()
        if locker.doorState == "CLOSED":
            locker.alertState = "NONE"
        else:
            locker.alertState = norm_alert

        if norm_alert == "DOOR_OPEN_TIMEOUT" and prev_alert != "DOOR_OPEN_TIMEOUT":
            active_sess = self.sessionRepo.get_active_session_by_locker(locker.LockerID)
            self.logRepo.record(
                action_type="DOOR_ALERT",
                locker_id=locker.LockerID,
                session_id=active_sess.sessionID if active_sess else None,
                note=(
                    f"Cảnh báo IoT (DOOR_OPEN_TIMEOUT): Cửa hộc tủ #{locker.LockerNumber} "
                    "mở quá thời gian quy định (30 giây). Buzzer trên ESP32 đã kích hoạt!"
                ),
            )

        self.db.commit()
        self.db.refresh(locker)
        return locker

