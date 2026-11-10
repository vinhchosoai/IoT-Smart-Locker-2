from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateLockerRequest(BaseModel):
    LockerNumber: int = Field(..., ge=1)
    status: str = Field(default="AVAILABLE")


class UpdateLockerStatusRequest(BaseModel):
    status: str = Field(..., description="AVAILABLE, OCCUPIED, or MAINTENANCE")
    doorState: Optional[str] = Field(default=None, description="OPEN or CLOSED")


class ForceOpenLockerRequest(BaseModel):
    reason: str = Field(default="Khách hàng yêu cầu hỗ trợ mở khẩn cấp")
    releaseSession: bool = Field(
        default=True,
        description="Whether to complete/force-close active session and release locker to AVAILABLE",
    )


class CreateStaffRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)
    fullName: str = Field(..., min_length=2, max_length=100)
    role: str = Field(default="STAFF", description="STAFF or ADMIN")


class UpdateStaffRequest(BaseModel):
    fullName: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


class CallStaffRequest(BaseModel):
    lockerNumber: Optional[int] = None
    reason: str = Field(default="Khách hàng tại Kiosk không thể xác thực khuôn mặt, cần nhân viên hỗ trợ.")


class BackupPinRetrieveRequest(BaseModel):
    lockerNumber: int
    backupPin: str


class IoTStatusPayload(BaseModel):
    locker_id: int
    door: str = Field(..., description="OPEN or CLOSED")
    lock_state: str = Field(default="LOCKED", description="LOCKED or UNLOCKED")
    alert: str = Field(default="NONE", description="NONE or DOOR_OPEN_TIMEOUT")


class ThresholdUpdateRequest(BaseModel):
    distanceThreshold: float = Field(..., ge=0.1, le=1.2)

