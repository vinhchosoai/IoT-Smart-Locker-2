from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.models import ActionLog, Locker, StorageSession, User, hash_password


class LockerRepository:
    """Repository for Locker entity (Class Diagram: lockerRepo: LockerRepository)."""

    def __init__(self, db: Session):
        self.db = db

    def get_all(self) -> List[Locker]:
        return self.db.query(Locker).order_by(Locker.LockerNumber.asc()).all()

    def get_by_id(self, locker_id: int) -> Optional[Locker]:
        return self.db.query(Locker).filter(Locker.LockerID == locker_id).first()

    def get_by_number(self, locker_number: int) -> Optional[Locker]:
        return (
            self.db.query(Locker)
            .filter(Locker.LockerNumber == locker_number)
            .first()
        )

    def find_first_available(self) -> Optional[Locker]:
        return (
            self.db.query(Locker)
            .filter(Locker.status == "AVAILABLE")
            .order_by(Locker.LockerNumber.asc())
            .first()
        )

    def create_locker(
        self,
        locker_number: int,
        status: str = "AVAILABLE",
        door_state: str = "CLOSED",
    ) -> Locker:
        locker = Locker(
            LockerNumber=locker_number,
            status=status.upper(),
            doorState=door_state.upper(),
            lockState="LOCKED",
            alertState="NONE",
        )
        self.db.add(locker)
        self.db.flush()
        return locker

    def delete_locker(self, locker: Locker) -> None:
        self.db.delete(locker)
        self.db.flush()


class SessionRepository:
    """Repository for StorageSession entity (Class Diagram: sessionRepo: SessionRepository)."""

    def __init__(self, db: Session):
        self.db = db

    def get_active_sessions(self) -> List[StorageSession]:
        return (
            self.db.query(StorageSession)
            .filter(StorageSession.status == "ACTIVE")
            .order_by(StorageSession.checkInAt.asc())
            .all()
        )

    def get_active_session_by_locker(self, locker_id: int) -> Optional[StorageSession]:
        return (
            self.db.query(StorageSession)
            .filter(
                StorageSession.LockerID == locker_id,
                StorageSession.status == "ACTIVE",
            )
            .first()
        )

    def get_by_id(self, session_id: int) -> Optional[StorageSession]:
        return (
            self.db.query(StorageSession)
            .filter(StorageSession.sessionID == session_id)
            .first()
        )

    def get_all(self, limit: int = 100) -> List[StorageSession]:
        return (
            self.db.query(StorageSession)
            .order_by(StorageSession.checkInAt.desc())
            .limit(limit)
            .all()
        )

    def create_session(
        self,
        locker_id: int,
        face_image_url: str,
        face_embedding: List[float],
        backup_pin: Optional[str] = None,
        customer_label: Optional[str] = None,
    ) -> StorageSession:
        sess = StorageSession(
            LockerID=locker_id,
            faceImageURL=face_image_url,
            faceEmbedding=face_embedding,
            backupPin=backup_pin,
            customerLabel=customer_label,
            status="ACTIVE",
        )
        self.db.add(sess)
        self.db.flush()
        return sess


class LogRepository:
    """Repository for ActionLog entity (Class Diagram: logRepo: LogRepository)."""

    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        action_type: str,
        locker_id: Optional[int] = None,
        user_id: Optional[int] = None,
        session_id: Optional[int] = None,
        note: Optional[str] = None,
    ) -> ActionLog:
        log_entry = ActionLog(
            LockerID=locker_id,
            userID=user_id,
            sessionID=session_id,
            actionType=action_type,
            note=note,
        )
        log_entry.createLog()
        self.db.add(log_entry)
        self.db.flush()
        return log_entry

    def query_logs(self, filter_criteria: Optional[Dict[str, Any]] = None) -> List[ActionLog]:
        q = self.db.query(ActionLog)
        if filter_criteria:
            if filter_criteria.get("actionType"):
                q = q.filter(ActionLog.actionType == filter_criteria["actionType"])
            if filter_criteria.get("LockerID"):
                q = q.filter(ActionLog.LockerID == int(filter_criteria["LockerID"]))
            if filter_criteria.get("userID"):
                q = q.filter(ActionLog.userID == int(filter_criteria["userID"]))
            if filter_criteria.get("sessionID"):
                q = q.filter(ActionLog.sessionID == int(filter_criteria["sessionID"]))
        limit = int((filter_criteria or {}).get("limit", 200))
        return q.order_by(ActionLog.timestamp.desc(), ActionLog.logID.desc()).limit(limit).all()


class UserRepository:
    """Repository for User entity (Staff & Admin management)."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.userID == user_id).first()

    def get_by_username(self, username: str) -> Optional[User]:
        return self.db.query(User).filter(User.username == username).first()

    def get_all(self) -> List[User]:
        return self.db.query(User).order_by(User.userID.asc()).all()

    def create_user(
        self,
        username: str,
        password: str,
        full_name: str,
        role: str = "STAFF",
    ) -> User:
        user = User(
            username=username.strip(),
            passwordHash=hash_password(password),
            fullName=full_name.strip(),
            role=role.upper().strip(),
        )
        self.db.add(user)
        self.db.flush()
        return user

    def update_user(
        self,
        user: User,
        full_name: Optional[str] = None,
        role: Optional[str] = None,
        password: Optional[str] = None,
    ) -> User:
        if full_name is not None and full_name.strip():
            user.fullName = full_name.strip()
        if role is not None and role.strip():
            user.role = role.upper().strip()
        if password is not None and password.strip():
            user.passwordHash = hash_password(password.strip())
        self.db.flush()
        return user

    def delete_user(self, user: User) -> None:
        self.db.delete(user)
        self.db.flush()

