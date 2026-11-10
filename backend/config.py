import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FACES_UPLOAD_DIR = DATA_DIR / "captured_faces"
SAMPLE_FACES_DIR = DATA_DIR / "sample_faces"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FACES_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_FACES_DIR.mkdir(parents=True, exist_ok=True)

# Database configuration (MySQL 8.0 primary, SQLite fallback if needed)
MYSQL_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root@127.0.0.1:3306/iot_smart_locker?charset=utf8mb4",
)
SQLITE_FALLBACK_URL = f"sqlite:///{(DATA_DIR / 'smart_locker.db').as_posix()}"

# MQTT Configuration (Section 3.3 & 3.4 of Report)
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "broker.hivemq.com")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
MQTT_COMMAND_TOPIC = os.getenv("MQTT_COMMAND_TOPIC", "iot_smartlocker_2026/command")
MQTT_STATUS_TOPIC = os.getenv("MQTT_STATUS_TOPIC", "iot_smartlocker_2026/status")

# AI / Face Recognition Configuration (Section 2.5 & 3.2.1 of Report)
FACE_MODEL_NAME = os.getenv("FACE_MODEL_NAME", "YOLOv5-Face + OpenCV-128D-Embedder")
FACE_DISTANCE_THRESHOLD = float(os.getenv("FACE_DISTANCE_THRESHOLD", "0.45"))

# IoT Hardware Timing Constants (Section 2.5, 6.2, 6.3 of Report)
RELAY_AUTO_LOCK_SECONDS = int(os.getenv("RELAY_AUTO_LOCK_SECONDS", "5"))
DOOR_OPEN_TIMEOUT_SECONDS = int(os.getenv("DOOR_OPEN_TIMEOUT_SECONDS", "30"))

# Security / Auth Configuration (Section 2.2 of Report)
JWT_SECRET = os.getenv("JWT_SECRET", "iot-smartlocker-2026-secret-key-very-secure")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

