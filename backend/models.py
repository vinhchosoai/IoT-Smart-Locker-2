import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import bcrypt
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


class User(Base):
    """
    Entity: User (Chapter 4.3 Class Diagram & Chapter 5.1 ERD).
    Stores Admin and Staff accounts.
    """

    __tablename__ = "users"

    userID = Column(Integer, primary_key=True, autoincrement=True)
    userUUID = Column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
    )
    username = Column(String(50), unique=True, nullable=False, index=True)
    passwordHash = Column(String(255), nullable=False)
    fullName = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="STAFF")  # 'ADMIN' | 'STAFF'
    createdAt = Column(DateTime, nullable=False, default=utc_now)

    action_logs = relationship("ActionLog", back_populates="user")

    @property
    def passwordHashed(self) -> str:
        """ERD compatibility alias for passwordHash."""
        return self.passwordHash

    @passwordHashed.setter
    def passwordHashed(self, value: str) -> None:
        self.passwordHash = value

    def authenticate(self, password: str) -> bool:
        """Class Diagram method: + authenticate(password: string): boolean"""
        return verify_password(password, self.passwordHash)

    def hasPermission(self, requiredRole: str) -> bool:
        """
        Class Diagram method: + hasPermission(requiredRole: string): boolean
        In Use Case Diagram (Fig 4.1), Admin inherits Staff privileges.
        """
        req = (requiredRole or "").upper()
        user_role = (self.role or "").upper()
        if user_role == "ADMIN":
            return True
        if req == "STAFF" and user_role in ("STAFF", "ADMIN"):
            return True
        return user_role == req

    def to_dict(self) -> Dict[str, Any]:
        return {
            "userID": self.userID,
            "userUUID": self.userUUID,
            "username": self.username,
            "fullName": self.fullName,
            "role": self.role,
            "createdAt": self.createdAt.isoformat() if self.createdAt else None,
        }


class Locker(Base):
    """
    Entity: Locker (Chapter 4.3 Class Diagram & Chapter 5.1 ERD).
    Stores locker compartment status, door state, lock state, and timeout alert state.
    """

    __tablename__ = "lockers"

    LockerID = Column(Integer, primary_key=True, autoincrement=True)
    lockerUUID = Column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
    )
    LockerNumber = Column(Integer, unique=True, nullable=False, index=True)
    status = Column(
        String(20), nullable=False, default="AVAILABLE"
    )  # AVAILABLE | OCCUPIED | MAINTENANCE
    doorState = Column(
        String(20), nullable=False, default="CLOSED"
    )  # OPEN | CLOSED
    lockState = Column(
        String(20), nullable=False, default="LOCKED"
    )  # LOCKED | UNLOCKED
    alertState = Column(
        String(30), nullable=False, default="NONE"
    )  # NONE | DOOR_OPEN_TIMEOUT
    updatedAt = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    sessions = relationship("StorageSession", back_populates="locker")
    action_logs = relationship("ActionLog", back_populates="locker")

    @property
    def updateAt(self) -> Optional[datetime]:
        """ERD compatibility alias for updatedAt."""
        return self.updatedAt

    def isAvailable(self) -> bool:
        """Class Diagram method: + isAvailable(): boolean"""
        return (
            self.status == "AVAILABLE"
            and self.alertState == "NONE"
        )

    def updateStatus(self, newStatus: str) -> None:
        """Class Diagram method: + updateStatus(newStatus: string): void"""
        normalized = (newStatus or "").upper().strip()
        if normalized == "AVAIBLE":  # Handle typo in ERD diagram if passed
            normalized = "AVAILABLE"
        if normalized not in ("AVAILABLE", "OCCUPIED", "MAINTENANCE"):
            raise ValueError(f"Invalid locker status: {newStatus}")
        self.status = normalized
        self.updatedAt = utc_now()

    def updateDoorState(self, newState: str) -> None:
        """Class Diagram method: + updateDoorState(newState: string): void"""
        normalized = (newState or "").upper().strip()
        if normalized == "CLOSE":  # Handle 'CLOSE' from ERD diagram
            normalized = "CLOSED"
        if normalized not in ("OPEN", "CLOSED"):
            raise ValueError(f"Invalid doorState: {newState}")
        self.doorState = normalized
        if normalized == "CLOSED":
            self.alertState = "NONE"
        self.updatedAt = utc_now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "LockerID": self.LockerID,
            "lockerUUID": self.lockerUUID,
            "LockerNumber": self.LockerNumber,
            "status": self.status,
            "doorState": self.doorState,
            "lockState": self.lockState,
            "alertState": self.alertState,
            "updatedAt": self.updatedAt.isoformat() if self.updatedAt else None,
        }


class StorageSession(Base):
    """
    Entity: StorageSession / Session (Chapter 4.3 Class Diagram & Chapter 5.1 ERD).
    Stores a single customer item-storage session and its 128D face embedding.
    """

    __tablename__ = "storage_sessions"

    sessionID = Column(Integer, primary_key=True, autoincrement=True)
    sessionUUID = Column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
    )
    LockerID = Column(Integer, ForeignKey("lockers.LockerID"), nullable=False, index=True)
    faceImageURL = Column(String(255), nullable=False)
    faceEmbedding = Column(JSON, nullable=False)  # 128D list<float>
    backupPin = Column(String(20), nullable=True)
    customerLabel = Column(String(100), nullable=True)
    checkInAt = Column(DateTime, nullable=False, default=utc_now)
    checkOutAt = Column(DateTime, nullable=True)
    status = Column(
        String(20), nullable=False, default="ACTIVE", index=True
    )  # ACTIVE | COMPLETED | FORCE_OPENED

    locker = relationship("Locker", back_populates="sessions")
    action_logs = relationship("ActionLog", back_populates="session")

    # Compatibility properties between Class Diagram and ERD
    @property
    def faceImageUrl(self) -> str:
        return self.faceImageURL

    @faceImageUrl.setter
    def faceImageUrl(self, val: str) -> None:
        self.faceImageURL = val

    @property
    def faceEmbedded(self) -> List[float]:
        return self.faceEmbedding

    @faceEmbedded.setter
    def faceEmbedded(self, val: List[float]) -> None:
        self.faceEmbedding = val

    @property
    def checkInTime(self) -> datetime:
        return self.checkInAt

    @property
    def checkOutTime(self) -> Optional[datetime]:
        return self.checkOutAt

    def completeSession(self) -> None:
        """Class Diagram method: + completeSession(): void"""
        self.status = "COMPLETED"
        self.checkOutAt = utc_now()

    def markForceOpened(self) -> None:
        """Class Diagram method: + markForceOpened(): void"""
        self.status = "FORCE_OPENED"
        self.checkOutAt = utc_now()

    def isExpired(self, timeoutMinutes: int = 1440) -> bool:
        """Class Diagram method: + isExpired(timeoutMinutes: integer): boolean"""
        if self.status != "ACTIVE" or not self.checkInAt:
            return False
        return utc_now() > (self.checkInAt + timedelta(minutes=timeoutMinutes))

    def to_dict(self, include_embedding: bool = False) -> Dict[str, Any]:
        data = {
            "sessionID": self.sessionID,
            "sessionUUID": self.sessionUUID,
            "LockerID": self.LockerID,
            "LockerNumber": self.locker.LockerNumber if self.locker else None,
            "faceImageURL": self.faceImageURL,
            "backupPin": self.backupPin,
            "customerLabel": self.customerLabel,
            "checkInAt": self.checkInAt.isoformat() if self.checkInAt else None,
            "checkOutAt": self.checkOutAt.isoformat() if self.checkOutAt else None,
            "status": self.status,
        }
        if include_embedding:
            data["faceEmbedding"] = self.faceEmbedding
        return data


# ERD alias
SessionEntity = StorageSession


class ActionLog(Base):
    """
    Entity: ActionLog (Chapter 4.3 Class Diagram & Chapter 5.1 ERD).
    Stores audit trail of Kiosk actions, Staff/Admin actions, and IoT door alerts.
    """

    __tablename__ = "action_logs"

    logID = Column(Integer, primary_key=True, autoincrement=True)
    actionLogUUID = Column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
    )
    LockerID = Column(Integer, ForeignKey("lockers.LockerID"), nullable=True, index=True)
    userID = Column(Integer, ForeignKey("users.userID"), nullable=True, index=True)
    sessionID = Column(
        Integer, ForeignKey("storage_sessions.sessionID"), nullable=True, index=True
    )
    actionType = Column(
        String(50), nullable=False, index=True
    )  # CLIENT_STORE | CLIENT_RETRIEVE | TEMP_OPEN | STAFF_FORCE_OPEN | DOOR_ALERT | CALL_STAFF | LOCKER_STATUS_UPDATE | STAFF_MANAGEMENT
    timestamp = Column(DateTime, nullable=False, default=utc_now, index=True)
    note = Column(String(500), nullable=True)

    locker = relationship("Locker", back_populates="action_logs")
    user = relationship("User", back_populates="action_logs")
    session = relationship("StorageSession", back_populates="action_logs")

    @property
    def actionLogID(self) -> int:
        """ERD compatibility alias."""
        return self.logID

    @property
    def status(self) -> str:
        """ERD compatibility alias for actionType."""
        return self.actionType

    @status.setter
    def status(self, value: str) -> None:
        self.actionType = value

    def createLog(self) -> Dict[str, Any]:
        """Class Diagram method: + createLog(): void/dict"""
        if not self.timestamp:
            self.timestamp = utc_now()
        if not self.actionLogUUID:
            self.actionLogUUID = str(uuid.uuid4())
        return self.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "logID": self.logID,
            "actionLogID": self.logID,
            "actionLogUUID": self.actionLogUUID,
            "LockerID": self.LockerID,
            "LockerNumber": self.locker.LockerNumber if self.locker else None,
            "userID": self.userID,
            "username": self.user.username if self.user else None,
            "sessionID": self.sessionID,
            "actionType": self.actionType,
            "status": self.actionType,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "note": self.note,
        }

