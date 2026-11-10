import base64
import time
from typing import Any, Dict, Optional

from backend.services.face_service import FaceDetectionError, FaceRecognitionService
from backend.services.locker_service import BusinessLogicError, LockerManagerService


class KioskController:
    """
    Kiosk Controller (Chapter 4.3 Class Diagram).

    Attributes (per Class Diagram):
        - faceService: FaceRecognitionService
        - lockerService: LockerManagerService

    Methods (per Class Diagram):
        - handleStoreRequest(imagePayload: bytes): dict/boolean
        - handleRetrieveRequest(imagePayload: bytes): dict/boolean
    """

    def __init__(
        self,
        face_service: FaceRecognitionService,
        locker_service: LockerManagerService,
    ):
        self.faceService = face_service
        self.lockerService = locker_service

    def handleStoreRequest(
        self,
        imagePayload: bytes,
        customer_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Class Diagram method: + handleStoreRequest(imagePayload: bytes): boolean/dict
        Executes full FR-01 store item flow:
          1. Detect face, check liveness, save annotated frame.
          2. Extract 128D face embedding.
          3. Delegate to LockerManagerService.storeItem().
        """
        t0 = time.perf_counter()
        try:
            frame_meta = self.faceService.annotate_and_save_frame(
                imagePayload, prefix="store"
            )
            embedding = self.faceService.extractEmbedding(imagePayload)
        except FaceDetectionError as exc:
            raise BusinessLogicError(
                code="FACE_DETECTION_FAILED",
                message=str(exc),
                status_code=422,
            )

        session, locker, min_dist = self.lockerService.storeItem(
            embedding=embedding,
            imageUrl=frame_meta["faceImageURL"],
            customer_label=customer_label,
        )
        total_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        return {
            "success": True,
            "action": "STORE",
            "message": f"Gửi đồ thành công! Hệ thống đã mở Hộc tủ số #{locker.LockerNumber}.",
            "locker": locker.to_dict(),
            "session": session.to_dict(),
            "ai": {
                "confidence": frame_meta["confidence"],
                "liveness": frame_meta["liveness"],
                "bbox": frame_meta["bbox"],
                "closestActiveDistance": min_dist if min_dist >= 0 else None,
                "threshold": self.faceService.distanceThreshold,
                "embeddingDim": len(embedding),
                "annotatedImageB64": base64.b64encode(
                    frame_meta["annotatedBytes"]
                ).decode("ascii"),
            },
            "latencyMs": total_ms,
        }

    def handleRetrieveRequest(
        self,
        imagePayload: bytes,
    ) -> Dict[str, Any]:
        """
        Class Diagram method: + handleRetrieveRequest(imagePayload: bytes): boolean/dict
        Executes full FR-02 retrieve item flow:
          1. Detect face, check liveness, save annotated frame.
          2. Extract 128D face embedding.
          3. Delegate to LockerManagerService.retrieveItem().
        """
        t0 = time.perf_counter()
        try:
            frame_meta = self.faceService.annotate_and_save_frame(
                imagePayload, prefix="retrieve"
            )
            embedding = self.faceService.extractEmbedding(imagePayload)
        except FaceDetectionError as exc:
            raise BusinessLogicError(
                code="FACE_DETECTION_FAILED",
                message=str(exc),
                status_code=422,
            )

        locker, session, matched_dist = self.lockerService.retrieveItem(
            embedding=embedding
        )
        total_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        return {
            "success": True,
            "action": "RETRIEVE",
            "message": (
                f"Xác thực khuôn mặt thành công (khoảng cách = {matched_dist:.4f})! "
                f"Hệ thống đã mở Hộc tủ số #{locker.LockerNumber} và hoàn tất phiên gửi đồ."
            ),
            "locker": locker.to_dict(),
            "session": session.to_dict(),
            "ai": {
                "confidence": frame_meta["confidence"],
                "liveness": frame_meta["liveness"],
                "bbox": frame_meta["bbox"],
                "matchedDistance": matched_dist,
                "threshold": self.faceService.distanceThreshold,
                "embeddingDim": len(embedding),
                "annotatedImageB64": base64.b64encode(
                    frame_meta["annotatedBytes"]
                ).decode("ascii"),
            },
            "latencyMs": total_ms,
        }

    def handleCallStaff(
        self,
        locker_number: Optional[int] = None,
        reason: str = "Khách hàng yêu cầu nhân viên hỗ trợ tại Kiosk.",
    ) -> Dict[str, Any]:
        """Implements Use Case 'Call Staff' (Fig 4.1)."""
        locker_id = None
        if locker_number is not None:
            locker = self.lockerService.lockerRepo.get_by_number(locker_number)
            if locker:
                locker_id = locker.LockerID

        log_entry = self.lockerService.logRepo.record(
            action_type="CALL_STAFF",
            locker_id=locker_id,
            note=f"[KIOSK SUPPORT REQUEST] {reason}",
        )
        self.lockerService.db.commit()
        return {
            "success": True,
            "message": "Đã gửi yêu cầu hỗ trợ tới Dashboard Nhân viên trực.",
            "log": log_entry.to_dict(),
        }

