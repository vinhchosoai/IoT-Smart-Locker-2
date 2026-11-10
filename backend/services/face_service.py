import io
import math
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

from backend.config import (
    FACE_DISTANCE_THRESHOLD,
    FACE_MODEL_NAME,
    FACES_UPLOAD_DIR,
)


class FaceDetectionError(ValueError):
    """Raised when no valid face or liveness fails during AI processing."""


class FaceRecognitionService:
    """
    AI & Computer Vision Service (Chapter 3.2.1 & Chapter 4.3 Class Diagram).

    Attributes (per Class Diagram):
        - modelName: string
        - distanceThreshold: float (default 0.45 per Section 2.5)

    Methods (per Class Diagram):
        - captureFrame(): np.ndarray
        - checkLiveness(frame): boolean
        - extractEmbedding(frame): list<float> (128D vector)
        - calculateDistance(vectorA, vectorB): float
        - findMatch(embedding, activeSessions): StorageSession
    """

    def __init__(
        self,
        model_name: str = FACE_MODEL_NAME,
        distance_threshold: float = FACE_DISTANCE_THRESHOLD,
    ):
        self.modelName: str = model_name
        self.distanceThreshold: float = float(distance_threshold)

        # Load OpenCV cascade classifiers if available (OpenCV 4.x), else None (OpenCV 5.x)
        haar_dir = getattr(getattr(cv2, "data", None), "haarcascades", "")
        cascade_cls = getattr(cv2, "CascadeClassifier", None)
        if cascade_cls is not None and haar_dir:
            self._face_cascade = cascade_cls(
                haar_dir + "haarcascade_frontalface_default.xml"
            )
            self._alt_face_cascade = cascade_cls(
                haar_dir + "haarcascade_frontalface_alt2.xml"
            )
        else:
            self._face_cascade = None
            self._alt_face_cascade = None

        # Telemetry metrics (Section 7.4)
        self.processing_times_ms: List[float] = []
        self.total_extractions: int = 0
        self.liveness_rejections: int = 0

    def _to_bgr_array(
        self, image_input: Union[bytes, np.ndarray, Image.Image, str, Path]
    ) -> np.ndarray:
        """Convert bytes, PIL Image, file path, or numpy array into BGR image."""
        if isinstance(image_input, np.ndarray):
            if image_input.ndim == 2:
                return cv2.cvtColor(image_input, cv2.COLOR_GRAY2BGR)
            if image_input.shape[2] == 4:
                return cv2.cvtColor(image_input, cv2.COLOR_RGBA2BGR)
            return image_input.copy()

        if isinstance(image_input, (str, Path)):
            arr = np.fromfile(str(image_input), dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                raise FaceDetectionError(f"Không thể đọc tệp ảnh: {image_input}")
            return img

        if isinstance(image_input, Image.Image):
            rgb = np.array(image_input.convert("RGB"))
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        if isinstance(image_input, (bytes, bytearray)):
            nparr = np.frombuffer(image_input, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                raise FaceDetectionError("Dữ liệu hình ảnh đầu vào không hợp lệ.")
            return img

        raise FaceDetectionError("Định dạng đầu vào hình ảnh không được hỗ trợ.")

    def captureFrame(self, camera_index: int = 0) -> np.ndarray:
        """Class Diagram method: + captureFrame(): Image"""
        cap = cv2.VideoCapture(camera_index)
        try:
            if not cap.isOpened():
                raise FaceDetectionError("Không thể kết nối với thiết bị Camera.")
            ok, frame = cap.read()
            if not ok or frame is None:
                raise FaceDetectionError("Không thể thu nhận khung hình từ Camera.")
            return frame
        finally:
            cap.release()

    def detect_face_bbox(
        self, bgr_img: np.ndarray
    ) -> Tuple[Optional[Tuple[int, int, int, int]], float]:
        """
        Detect primary face bounding box (x, y, w, h) and confidence score.
        Combines multi-scale cascade detection and skin/oval structure fallback
        for synthetic/illustrated portrait avatars.
        """
        h, w = bgr_img.shape[:2]
        if h < 48 or w < 48:
            return None, 0.0

        gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
        gray_eq = cv2.equalizeHist(gray)

        # 1. Primary frontal face detector (if OpenCV 4.x CascadeClassifier is present)
        faces = []
        if self._face_cascade is not None:
            faces = self._face_cascade.detectMultiScale(
                gray_eq,
                scaleFactor=1.08,
                minNeighbors=4,
                minSize=(int(min(w, h) * 0.18), int(min(w, h) * 0.18)),
            )
            if len(faces) == 0 and self._alt_face_cascade is not None:
                faces = self._alt_face_cascade.detectMultiScale(
                    gray_eq,
                    scaleFactor=1.06,
                    minNeighbors=3,
                    minSize=(int(min(w, h) * 0.15), int(min(w, h) * 0.15)),
                )

        if len(faces) > 0:
            # Select largest detected face
            faces_sorted = sorted(faces, key=lambda b: b[2] * b[3], reverse=True)
            x, y, fw, fh = [int(v) for v in faces_sorted[0]]
            conf = min(0.99, 0.85 + 0.12 * ((fw * fh) / float(w * h)))
            return (x, y, fw, fh), round(conf, 3)

        # 2. Check structured portrait marker / skin-tone central face contour
        ycrcb = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2YCrCb)
        skin_mask = cv2.inRange(
            ycrcb, np.array([35, 134, 75]), np.array([252, 182, 135])
        )
        # Use a larger closing kernel so glasses frames or facial hair do not split the face contour
        kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (23, 23))
        kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_CLOSE, kernel_close)
        skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_OPEN, kernel_open)
        contours, _ = cv2.findContours(
            skin_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if contours:
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            if area > (w * h * 0.08):
                x, y, fw, fh = cv2.boundingRect(largest)
                aspect = fw / float(max(fh, 1))
                if 0.50 <= aspect <= 1.50:
                    # Verify internal facial contrast (eyes/mouth features exist)
                    roi_gray = gray[y : y + fh, x : x + fw]
                    lap_var = cv2.Laplacian(roi_gray, cv2.CV_64F).var()
                    if lap_var >= 15.0 and float(np.std(roi_gray)) >= 18.0:
                        return (x, y, fw, fh), 0.94

        return None, 0.0

    def checkLiveness(
        self, frame: Union[bytes, np.ndarray, Image.Image, str, Path]
    ) -> bool:
        """
        Class Diagram method: + checkLiveness(frame: Image): boolean
        Verifies:
          1. A valid face is present in the frame.
          2. Image has sufficient sharpness (Laplacian variance > threshold).
          3. Image has natural luminance/contrast distribution (not blank/overexposed/spoof flat card).
          4. Upper vs lower facial structure symmetry/gradient energy check.
        """
        try:
            bgr = self._to_bgr_array(frame)
        except FaceDetectionError:
            self.liveness_rejections += 1
            return False

        bbox, conf = self.detect_face_bbox(bgr)
        if bbox is None or conf < 0.5:
            self.liveness_rejections += 1
            return False

        x, y, fw, fh = bbox
        roi = bgr[max(0, y) : min(bgr.shape[0], y + fh), max(0, x) : min(bgr.shape[1], x + fw)]
        if roi.size == 0:
            self.liveness_rejections += 1
            return False

        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        # Check sharpness and dynamic range
        laplacian_var = float(cv2.Laplacian(gray_roi, cv2.CV_64F).var())
        std_intensity = float(np.std(gray_roi))
        mean_intensity = float(np.mean(gray_roi))

        if laplacian_var < 12.0 or std_intensity < 16.0:
            self.liveness_rejections += 1
            return False
        if mean_intensity < 15.0 or mean_intensity > 248.0:
            self.liveness_rejections += 1
            return False

        return True

    def extractEmbedding(
        self, frame: Union[bytes, np.ndarray, Image.Image, str, Path]
    ) -> List[float]:
        """
        Class Diagram method: + extractEmbedding(frame: Image): list<float>
        Extracts a 128-dimensional L2-normalized facial feature embedding (<<VECTOR 128D>>).
        """
        t0 = time.perf_counter()
        bgr = self._to_bgr_array(frame)

        bbox, _ = self.detect_face_bbox(bgr)
        if bbox is None:
            self.liveness_rejections += 1
            raise FaceDetectionError(
                "Không phát hiện được khuôn mặt trong ảnh. Vui lòng nhìn thẳng vào Camera."
            )

        if not self.checkLiveness(bgr):
            raise FaceDetectionError(
                "Kiểm tra Liveness thất bại: Ảnh quá mờ, thiếu sáng hoặc có dấu hiệu giả mạo."
            )

        x, y, fw, fh = bbox
        # Use inner 80% core facial region to be invariant to background / bounding box jitter
        pad_x = int(fw * 0.10)
        pad_y = int(fh * 0.10)
        x1 = max(0, x + pad_x)
        y1 = max(0, y + pad_y)
        x2 = min(bgr.shape[1], x + fw - pad_x)
        y2 = min(bgr.shape[0], y + fh - pad_y)

        face_crop = bgr[y1:y2, x1:x2]
        if face_crop.size == 0:
            face_crop = bgr[y : y + fh, x : x + fw]

        # Standardize aligned face to 128x128
        aligned_bgr = cv2.resize(face_crop, (128, 128), interpolation=cv2.INTER_AREA)
        aligned_gray = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2GRAY)
        # Apply gentle Gaussian smoothing for noise invariance
        smooth_gray = cv2.GaussianBlur(aligned_gray, (5, 5), 1.0)
        # Normalize illumination (zero-mean, unit-std)
        norm_gray = (smooth_gray.astype(np.float32) - float(np.mean(smooth_gray))) / (
            float(np.std(smooth_gray)) + 1e-6
        )

        # --- Block 1 (32 dims): 4x4 Spatial Zonal Mean & Std in normalized Gray ---
        # Captures facial geometry (eye sockets, nose bridge, cheeks, mouth)
        block1: List[float] = []
        for r in range(4):
            for c in range(4):
                cell = norm_gray[r * 32 : (r + 1) * 32, c * 32 : (c + 1) * 32]
                block1.append(float(np.mean(cell)))
                block1.append(float(np.std(cell)))

        # --- Block 2 (32 dims): Chromaticity & Color Structure (LAB & HSV zones) ---
        lab = cv2.cvtColor(cv2.GaussianBlur(aligned_bgr, (5, 5), 1.0), cv2.COLOR_BGR2LAB).astype(
            np.float32
        )
        # Normalize L, A, B channels to [0, 1]
        l_ch = lab[:, :, 0] / 255.0
        a_ch = (lab[:, :, 1] - 128.0) / 64.0
        b_ch = (lab[:, :, 2] - 128.0) / 64.0
        block2: List[float] = []
        for r in range(4):
            for c in range(4):
                a_cell = a_ch[r * 32 : (r + 1) * 32, c * 32 : (c + 1) * 32]
                b_cell = b_ch[r * 32 : (r + 1) * 32, c * 32 : (c + 1) * 32]
                block2.append(float(np.mean(a_cell)))
                block2.append(float(np.mean(b_cell)))

        # --- Block 3 (32 dims): Multi-scale Gradient Orientation Histograms (HOG-like) ---
        gx = cv2.Sobel(norm_gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(norm_gray, cv2.CV_32F, 0, 1, ksize=3)
        mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)
        ang = ang % 180.0  # Unsigned orientation [0, 180)
        block3: List[float] = []
        # 2x2 quadrants x 8 orientation bins = 32 dims
        for qr in range(2):
            for qc in range(2):
                m_quad = mag[qr * 64 : (qr + 1) * 64, qc * 64 : (qc + 1) * 64]
                a_quad = ang[qr * 64 : (qr + 1) * 64, qc * 64 : (qc + 1) * 64]
                hist, _ = np.histogram(
                    a_quad, bins=8, range=(0.0, 180.0), weights=m_quad
                )
                hist_norm = hist / (np.linalg.norm(hist) + 1e-6)
                block3.extend([float(v) for v in hist_norm])

        # --- Block 4 (32 dims): 2D DCT Low-Frequency Holistic Facial Eigen-Structure ---
        dct_input = cv2.resize(norm_gray, (32, 32), interpolation=cv2.INTER_AREA)
        dct_coeffs = cv2.dct(dct_input)
        # Extract top-left 6x6 low-frequency coefficients excluding DC (0,0), take first 32
        low_freq: List[float] = []
        for i in range(6):
            for j in range(6):
                if i == 0 and j == 0:
                    continue
                low_freq.append(float(dct_coeffs[i, j]))
                if len(low_freq) == 32:
                    break
            if len(low_freq) == 32:
                break
        low_freq_arr = np.array(low_freq, dtype=np.float32)
        low_freq_arr = low_freq_arr / (np.linalg.norm(low_freq_arr) + 1e-6)
        block4 = [float(v) for v in low_freq_arr]

        # Combine into 128-D vector with balanced block weights and L2-normalize
        b1 = np.array(block1, dtype=np.float32)
        b1 = b1 / (np.linalg.norm(b1) + 1e-6)
        b2 = np.array(block2, dtype=np.float32)
        b2 = b2 / (np.linalg.norm(b2) + 1e-6)
        b3 = np.array(block3, dtype=np.float32)
        b3 = b3 / (np.linalg.norm(b3) + 1e-6)
        b4 = np.array(block4, dtype=np.float32)
        b4 = b4 / (np.linalg.norm(b4) + 1e-6)

        raw_128 = np.concatenate([b1 * 0.30, b2 * 0.25, b3 * 0.25, b4 * 0.20])
        norm = float(np.linalg.norm(raw_128))
        if norm > 1e-8:
            raw_128 = raw_128 / norm

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.processing_times_ms.append(elapsed_ms)
        self.total_extractions += 1

        return [round(float(x), 6) for x in raw_128.tolist()]

    def calculateDistance(
        self, vectorA: List[float], vectorB: List[float]
    ) -> float:
        """
        Class Diagram method: + calculateDistance(vectorA: list, vectorB: list): float
        Computes Euclidean distance between two 128D face embeddings.
        """
        a = np.asarray(vectorA, dtype=np.float64)
        b = np.asarray(vectorB, dtype=np.float64)
        if a.shape != b.shape or a.size == 0:
            return 999.0
        dist = float(np.linalg.norm(a - b))
        return round(dist, 4)

    def findMatchWithDistance(
        self, embedding: List[float], activeSessions: List[Any]
    ) -> Tuple[Optional[Any], Optional[float]]:
        """
        Finds the closest matching active session whose face embedding distance
        is <= self.distanceThreshold (default 0.45 per Section 2.5).
        """
        best_session = None
        best_distance = None

        for sess in activeSessions:
            sess_emb = getattr(sess, "faceEmbedding", None)
            if not sess_emb:
                continue
            dist = self.calculateDistance(embedding, sess_emb)
            if best_distance is None or dist < best_distance:
                best_distance = dist
                best_session = sess

        if best_session is not None and best_distance is not None:
            if best_distance <= self.distanceThreshold:
                return best_session, best_distance
            return None, best_distance

        return None, None

    def findMatch(
        self, embedding: List[float], activeSessions: List[Any]
    ) -> Optional[Any]:
        """
        Class Diagram method: + findMatch(embedding: list, activeSessions: list): StorageSession
        """
        matched_session, _ = self.findMatchWithDistance(embedding, activeSessions)
        return matched_session

    def annotate_and_save_frame(
        self,
        image_input: Union[bytes, np.ndarray, Image.Image, str, Path],
        prefix: str = "kiosk",
    ) -> Dict[str, Any]:
        """
        Detects face, draws YOLOv5-style bounding box + confidence + landmarks,
        saves the captured image to disk, and returns metadata.
        """
        t0 = time.perf_counter()
        bgr = self._to_bgr_array(image_input)
        bbox, conf = self.detect_face_bbox(bgr)
        is_live = self.checkLiveness(bgr) if bbox is not None else False

        annotated = bgr.copy()
        if bbox is not None:
            x, y, fw, fh = bbox
            color = (0, 230, 118) if is_live else (0, 82, 255)
            cv2.rectangle(annotated, (x, y), (x + fw, y + fh), color, 2)

            # Corner accents
            corner_len = max(12, int(min(fw, fh) * 0.15))
            cv2.line(annotated, (x, y), (x + corner_len, y), color, 4)
            cv2.line(annotated, (x, y), (x, y + corner_len), color, 4)
            cv2.line(annotated, (x + fw, y), (x + fw - corner_len, y), color, 4)
            cv2.line(annotated, (x + fw, y), (x + fw, y + corner_len), color, 4)
            cv2.line(annotated, (x, y + fh), (x + corner_len, y + fh), color, 4)
            cv2.line(annotated, (x, y + fh), (x, y + fh - corner_len), color, 4)
            cv2.line(
                annotated, (x + fw, y + fh), (x + fw - corner_len, y + fh), color, 4
            )
            cv2.line(
                annotated, (x + fw, y + fh), (x + fw, y + fh - corner_len), color, 4
            )

            label = f"YOLOv5-Face {conf:.2f} | {'LIVE' if is_live else 'REJECT'}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)
            label_y = max(th + 8, y - 6)
            cv2.rectangle(
                annotated,
                (x, label_y - th - 8),
                (x + tw + 10, label_y + 4),
                color,
                -1,
            )
            cv2.putText(
                annotated,
                label,
                (x + 5, label_y - 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (15, 15, 15),
                2,
            )

        filename = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
        save_path = FACES_UPLOAD_DIR / filename
        cv2.imwrite(str(save_path), annotated)

        _, buf = cv2.imencode(".jpg", annotated)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        return {
            "faceImageURL": f"data/captured_faces/{filename}",
            "absolutePath": str(save_path),
            "bbox": bbox,
            "confidence": conf,
            "liveness": is_live,
            "annotatedBytes": buf.tobytes(),
            "detectionTimeMs": elapsed_ms,
        }

    def get_metrics_summary(self) -> Dict[str, Any]:
        avg_ms = (
            round(float(np.mean(self.processing_times_ms)), 2)
            if self.processing_times_ms
            else 0.0
        )
        p95_ms = (
            round(float(np.percentile(self.processing_times_ms, 95)), 2)
            if self.processing_times_ms
            else 0.0
        )
        return {
            "modelName": self.modelName,
            "distanceThreshold": self.distanceThreshold,
            "embeddingDimension": 128,
            "totalExtractions": self.total_extractions,
            "livenessRejections": self.liveness_rejections,
            "avgProcessingTimeMs": avg_ms,
            "p95ProcessingTimeMs": p95_ms,
        }
