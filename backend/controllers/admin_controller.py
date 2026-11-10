from typing import Any, Dict, List, Optional

from backend.models import User
from backend.services.locker_service import BusinessLogicError, LockerManagerService
from backend.services.mqtt_service import MQTTService


class AdminDashboardController:
    """
    Admin & Staff Dashboard Controller (Chapter 4.3 Class Diagram).

    Attributes (per Class Diagram):
        - lockerService: LockerManagerService
        - mqttService: MQTTService

    Methods (per Class Diagram):
        - getAllLockersRealtime(): list<Locker>
        - updateLockerStatus(LockerID: integer, status: string): boolean
        - forceOpenLocker(adminID: integer, LockerID: int): boolean
        - getActionLogs(filterCriteria: dict): list<ActionLog>
        - getAllStaff(): list<User>
        - createStaff(staffData: dict): boolean
        - updateStaff(userID: integer, staffData: dict): boolean
        - deleteStaff(userID: integer): boolean
    """

    def __init__(
        self,
        locker_service: LockerManagerService,
        mqtt_service: MQTTService,
    ):
        self.lockerService = locker_service
        self.mqttService = mqtt_service

    def _require_role(self, actor: Optional[User], required_role: str) -> User:
        if actor is None:
            raise BusinessLogicError(
                code="UNAUTHORIZED",
                message="Vui lòng đăng nhập để thực hiện chức năng quản trị.",
                status_code=401,
            )
        if not actor.hasPermission(required_role):
            raise BusinessLogicError(
                code="FORBIDDEN",
                message=(
                    f"Truy cập bị từ chối (TC-10): Tài khoản '{actor.username}' "
                    f"(vai trò {actor.role}) không đủ quyền '{required_role}'."
                ),
                status_code=403,
            )
        return actor

    def getAllLockersRealtime(self) -> List[Dict[str, Any]]:
        """Class Diagram method: + getAllLockersRealtime(): list<Locker>"""
        lockers = self.lockerService.lockerRepo.get_all()
        active_sessions = {
            s.LockerID: s for s in self.lockerService.sessionRepo.get_active_sessions()
        }
        result = []
        for lk in lockers:
            d = lk.to_dict()
            sess = active_sessions.get(lk.LockerID)
            d["activeSession"] = sess.to_dict() if sess else None
            result.append(d)
        return result

    def updateLockerStatus(
        self,
        LockerID: int,
        status: str,
        actor: Optional[User] = None,
        door_state: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Class Diagram method: + updateLockerStatus(LockerID: integer, status: string): boolean"""
        if actor is not None:
            self._require_role(actor, "STAFF")

        locker = self.lockerService.lockerRepo.get_by_id(LockerID)
        if locker is None:
            locker = self.lockerService.lockerRepo.get_by_number(LockerID)
        if locker is None:
            raise BusinessLogicError(
                code="LOCKER_NOT_FOUND",
                message=f"Không tìm thấy hộc tủ #{LockerID}.",
                status_code=404,
            )

        old_status = locker.status
        try:
            locker.updateStatus(status)
            if door_state is not None:
                locker.updateDoorState(door_state)
        except ValueError as exc:
            raise BusinessLogicError(
                code="INVALID_LOCKER_STATUS",
                message=str(exc),
                status_code=400,
            )

        # If changing locker to AVAILABLE or MAINTENANCE while an ACTIVE session exists, close the session
        if locker.status in ("AVAILABLE", "MAINTENANCE"):
            active_sess = self.lockerService.sessionRepo.get_active_session_by_locker(
                locker.LockerID
            )
            if active_sess is not None:
                active_sess.markForceOpened()

        self.lockerService.logRepo.record(
            action_type="LOCKER_STATUS_UPDATE",
            locker_id=locker.LockerID,
            user_id=actor.userID if actor else None,
            note=f"Cập nhật trạng thái Tủ #{locker.LockerNumber}: {old_status} -> {locker.status}",
        )
        self.lockerService.db.commit()
        self.lockerService.db.refresh(locker)
        return {"success": True, "locker": locker.to_dict()}

    def createLocker(
        self,
        actor: User,
        locker_number: int,
        status: str = "AVAILABLE",
    ) -> Dict[str, Any]:
        """Implements Use Case 'Create Locker' (Fig 4.1 - Admin only)."""
        self._require_role(actor, "ADMIN")
        existing = self.lockerService.lockerRepo.get_by_number(locker_number)
        if existing is not None:
            raise BusinessLogicError(
                code="DUPLICATE_LOCKER_NUMBER",
                message=f"Hộc tủ số #{locker_number} đã tồn tại.",
                status_code=409,
            )
        locker = self.lockerService.lockerRepo.create_locker(
            locker_number=locker_number,
            status=status,
        )
        self.lockerService.logRepo.record(
            action_type="LOCKER_STATUS_UPDATE",
            locker_id=locker.LockerID,
            user_id=actor.userID,
            note=f"[ADMIN: {actor.username}] Tạo mới Hộc tủ #{locker.LockerNumber} ({locker.status})",
        )
        self.lockerService.db.commit()
        self.lockerService.db.refresh(locker)
        return {"success": True, "locker": locker.to_dict()}

    def deleteLocker(self, actor: User, LockerID: int) -> Dict[str, Any]:
        """Implements Use Case 'Delete Locker' (Fig 4.1 - Admin only)."""
        self._require_role(actor, "ADMIN")
        locker = self.lockerService.lockerRepo.get_by_id(LockerID)
        if locker is None:
            locker = self.lockerService.lockerRepo.get_by_number(LockerID)
        if locker is None:
            raise BusinessLogicError(
                code="LOCKER_NOT_FOUND",
                message=f"Không tìm thấy hộc tủ #{LockerID}.",
                status_code=404,
            )
        if locker.status == "OCCUPIED":
            raise BusinessLogicError(
                code="LOCKER_OCCUPIED",
                message=f"Không thể xóa Hộc tủ #{locker.LockerNumber} khi đang có khách gửi đồ (OCCUPIED).",
                status_code=409,
            )
        num = locker.LockerNumber
        self.lockerService.lockerRepo.delete_locker(locker)
        self.lockerService.logRepo.record(
            action_type="LOCKER_STATUS_UPDATE",
            user_id=actor.userID,
            note=f"[ADMIN: {actor.username}] Xóa Hộc tủ #{num}",
        )
        self.lockerService.db.commit()
        return {"success": True, "deletedLockerNumber": num}

    def forceOpenLocker(
        self,
        adminID: int,
        LockerID: int,
        reason: str = "Mở khẩn cấp bởi nhân viên trực",
        release_session: bool = True,
    ) -> Dict[str, Any]:
        """Class Diagram method: + forceOpenLocker(adminID: integer, LockerID: int): boolean"""
        return self.lockerService.triggerEmergencyUnlock(
            adminID=adminID,
            LockerID=LockerID,
            reason=reason,
            release_session=release_session,
        )

    def getActionLogs(
        self, filterCriteria: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Class Diagram method: + getActionLogs(filterCriteria: dict): list<ActionLog>"""
        logs = self.lockerService.logRepo.query_logs(filterCriteria)
        return [lg.to_dict() for lg in logs]

    def getAllStaff(self, actor: Optional[User] = None) -> List[Dict[str, Any]]:
        """Class Diagram method: + getAllStaff(): list<User>"""
        if actor is not None:
            self._require_role(actor, "STAFF")
        users = self.lockerService.userRepo.get_all()
        return [u.to_dict() for u in users]

    def createStaff(
        self, staffData: Dict[str, Any], actor: Optional[User] = None
    ) -> Dict[str, Any]:
        """
        Class Diagram method: + createStaff(staffData: dict): boolean
        Implements FR-04 & TC-10 (Admin only).
        """
        if actor is not None:
            self._require_role(actor, "ADMIN")

        username = (staffData.get("username") or "").strip()
        password = (staffData.get("password") or "").strip()
        full_name = (staffData.get("fullName") or "").strip()
        role = (staffData.get("role") or "STAFF").upper().strip()

        if not username or not password or not full_name:
            raise BusinessLogicError(
                code="INVALID_STAFF_DATA",
                message="Vui lòng nhập đầy đủ username, password và fullName.",
                status_code=400,
            )
        if role not in ("ADMIN", "STAFF"):
            raise BusinessLogicError(
                code="INVALID_ROLE",
                message="Vai trò (role) chỉ nhận giá trị 'ADMIN' hoặc 'STAFF'.",
                status_code=400,
            )
        if self.lockerService.userRepo.get_by_username(username) is not None:
            raise BusinessLogicError(
                code="DUPLICATE_USERNAME",
                message=f"Tên đăng nhập '{username}' đã tồn tại.",
                status_code=409,
            )

        new_user = self.lockerService.userRepo.create_user(
            username=username,
            password=password,
            full_name=full_name,
            role=role,
        )
        self.lockerService.logRepo.record(
            action_type="STAFF_MANAGEMENT",
            user_id=actor.userID if actor else new_user.userID,
            note=f"Tạo tài khoản nhân sự '{new_user.username}' (role={new_user.role})",
        )
        self.lockerService.db.commit()
        self.lockerService.db.refresh(new_user)
        return {"success": True, "user": new_user.to_dict()}

    def updateStaff(
        self,
        userID: int,
        staffData: Dict[str, Any],
        actor: Optional[User] = None,
    ) -> Dict[str, Any]:
        """
        Class Diagram method: + updateStaff(userID: integer, staffData: dict): boolean
        Implements FR-04 & TC-10 (Admin only).
        """
        if actor is not None:
            self._require_role(actor, "ADMIN")

        target = self.lockerService.userRepo.get_by_id(userID)
        if target is None:
            raise BusinessLogicError(
                code="USER_NOT_FOUND",
                message=f"Không tìm thấy tài khoản userID={userID}.",
                status_code=404,
            )

        updated = self.lockerService.userRepo.update_user(
            user=target,
            full_name=staffData.get("fullName"),
            role=staffData.get("role"),
            password=staffData.get("password"),
        )
        self.lockerService.logRepo.record(
            action_type="STAFF_MANAGEMENT",
            user_id=actor.userID if actor else target.userID,
            note=f"Cập nhật tài khoản '{updated.username}' (role={updated.role})",
        )
        self.lockerService.db.commit()
        self.lockerService.db.refresh(updated)
        return {"success": True, "user": updated.to_dict()}

    def deleteStaff(
        self, userID: int, actor: Optional[User] = None
    ) -> Dict[str, Any]:
        """
        Class Diagram method: + deleteStaff(userID: integer): boolean
        Implements FR-04 & TC-10 (Admin only).
        """
        if actor is not None:
            self._require_role(actor, "ADMIN")
            if actor.userID == userID:
                raise BusinessLogicError(
                    code="CANNOT_DELETE_SELF",
                    message="Quản trị viên không thể tự xóa tài khoản đang đăng nhập.",
                    status_code=400,
                )

        target = self.lockerService.userRepo.get_by_id(userID)
        if target is None:
            raise BusinessLogicError(
                code="USER_NOT_FOUND",
                message=f"Không tìm thấy tài khoản userID={userID}.",
                status_code=404,
            )

        uname = target.username
        self.lockerService.userRepo.delete_user(target)
        self.lockerService.logRepo.record(
            action_type="STAFF_MANAGEMENT",
            user_id=actor.userID if actor else None,
            note=f"Xóa tài khoản nhân sự '{uname}' (userID={userID})",
        )
        self.lockerService.db.commit()
        return {"success": True, "deletedUsername": uname}

