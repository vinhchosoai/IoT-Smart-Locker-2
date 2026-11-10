# Hệ thống Tủ đồ Thông minh Tích hợp Nhận diện Khuôn mặt (IoT Smart Locker MVP)

Dự án MVP hoàn chỉnh được xây dựng dựa trên đặc tả kỹ thuật trong tài liệu báo cáo **[Bao_cao_do_an_IoT_Smart_Locker.docx.md](file:///d:/school/IoT/test/document/Bao_cao_do_an_IoT_Smart_Locker.docx.md)** theo mô hình **Hybrid Simulation**:
- **Kiosk & AI**: Python, Streamlit, YOLOv5-Face / OpenCV Localization + Kiểm tra Liveness + Trích xuất Vector đặc trưng **128 chiều (`<<VECTOR 128D>>`)** với ngưỡng khoảng cách Euclidean $\le 0.45$.
- **Backend & Database**: FastAPI + SQLAlchemy ORM + **MySQL 8.0** (tự động dự phòng SQLite nếu chạy trên máy không cài MySQL).
- **Thiết bị IoT & Giao tiếp**: Giao thức **MQTT** (`broker.hivemq.com:1883`) với 2 topic `iot_smartlocker_2026/command` và `iot_smartlocker_2026/status`, đi kèm trọn bộ mã nguồn **ESP32 trên Wokwi** (`sketch.ino`, `diagram.json`) và **Bộ mô phỏng phần cứng Virtual ESP32 Twin** tích hợp sẵn.
- **Dashboard Nhân viên & Quản trị viên**: Phân quyền RBAC (`ADMIN` / `STAFF`), giám sát trạng thái tủ thời gian thực, mở khóa khẩn cấp có lưu vết (`STAFF_FORCE_OPEN`), cảnh báo cửa mở quá 30 giây (`DOOR_OPEN_TIMEOUT`), quản lý nhân viên và xuất nhật ký hoạt động.

---

## 1. Cấu trúc Thư mục Dự án

```text
d:\school\IoT\test\
├── backend\
│   ├── config.py                 # Cấu hình hệ thống (MySQL, MQTT, Ngưỡng AI 0.45, Thời gian Relay 5s / Cửa 30s)
│   ├── database.py               # Kết nối MySQL 8.0 (kèm cơ chế tự động khởi tạo & fallback SQLite)
│   ├── models.py                 # Thực thể User, Locker, StorageSession, ActionLog (chuẩn hóa ERD & Class Diagram)
│   ├── repositories.py           # LockerRepository, SessionRepository, LogRepository, UserRepository
│   ├── schemas.py                # Pydantic Schemas kiểm tra tính hợp lệ dữ liệu API & MQTT
│   ├── services\
│   │   ├── face_service.py       # FaceRecognitionService (YOLOv5-Face bbox, Liveness, 128D Vector, Euclidean <= 0.45)
│   │   ├── mqtt_service.py       # MQTTService (Kết nối broker.hivemq.com:1883 & Hybrid Local Bridge)
│   │   └── locker_service.py     # LockerManagerService (Nghiệp vụ Gửi đồ, Nhận đồ, Mở khẩn cấp, Cảnh báo cửa)
│   ├── controllers\
│   │   ├── kiosk_controller.py   # KioskController
│   │   └── admin_controller.py   # AdminDashboardController
│   └── main.py                   # FastAPI Application & REST API Endpoints
├── frontend\
│   ├── app.py                    # Giao diện hợp nhất Streamlit (Kiosk + Dashboard + Mô phỏng Phần cứng ESP32)
│   ├── kiosk.py                  # Điểm vào riêng cho Kiosk Khách hàng
│   └── dashboard.py              # Điểm vào riêng cho Dashboard Quản trị (Staff/Admin)
├── iot_esp32\
│   ├── wokwi\
│   │   ├── sketch.ino            # Mã nguồn Arduino C/C++ cho ESP32 (LCD I2C, Buzzer, Relay 5s millis(), Cửa 30s)
│   │   ├── diagram.json          # Sơ đồ mạch phần cứng Wokwi (GPIO 21/22, GPIO 15, GPIO 26/27, GPIO 32/33)
│   │   ├── libraries.txt         # Thư viện Arduino cần thiết trên Wokwi
│   │   └── wokwi.toml            # Cấu hình Wokwi
│   └── esp32_simulator.py        # Virtual ESP32 Hardware Twin đồng bộ trực tiếp với MQTT & Dashboard
├── database\
│   ├── mysql_schema.sql          # Lược đồ vật lý MySQL 8.0 chuẩn hóa và dữ liệu khởi tạo
│   └── schema_mapping_notes.md   # Tài liệu đối chiếu chuẩn hóa ERD và Class Diagram (Mục 5.4)
├── scripts\
│   ├── generate_sample_faces.py  # Sinh bộ ảnh khuôn mặt mẫu kiểm thử AI (Customer 01..04 & ảnh lỗi Liveness)
│   └── run_experiments.py        # Thu thập số liệu thực nghiệm và đánh giá hệ thống (Mục 7.4)
├── tests\
│   └── test_smart_locker.py      # Bộ kiểm thử tự động Pytest cho toàn bộ 10 tình huống TC-01..TC-10 + Unit Tests
├── requirements.txt              # Danh sách thư viện Python trong .venv
└── start_mvp.ps1                 # Script khởi chạy toàn bộ hệ thống bằng 1 lệnh
```

---

## 2. Hướng dẫn Khởi chạy Nhanh

### Cách 1: Khởi chạy tự động bằng PowerShell Script
```powershell
.\start_mvp.ps1
```

### Cách 2: Khởi chạy từng thành phần
1. **Khởi chạy FastAPI Backend (Cổng 8000):**
   ```powershell
   $env:PYTHONPATH = "d:\school\IoT\test"
   .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
   ```
   - Tài liệu Swagger UI trực tuyến: http://127.0.0.1:8000/docs

2. **Khởi chạy Giao diện Streamlit Kiosk & Dashboard (Cổng 8501):**
   ```powershell
   $env:PYTHONPATH = "d:\school\IoT\test"
   .\.venv\Scripts\streamlit.exe run frontend\app.py --server.port 8501
   ```
   - Truy cập giao diện tại: http://127.0.0.1:8501

### Tài khoản Đăng nhập Mặc định trên Dashboard
| Vai trò | Tên đăng nhập (`username`) | Mật khẩu (`password`) | Quyền hạn |
| :--- | :--- | :--- | :--- |
| **Quản trị viên (`ADMIN`)** | `admin` | `admin123` | Toàn quyền quản lý hộc tủ, mở khẩn cấp, quản lý tài khoản nhân viên (`FR-04`), xem nhật ký, chỉnh ngưỡng AI. |
| **Nhân viên (`STAFF`)** | `staff01` / `staff02` | `staff123` | Theo dõi trạng thái tủ, mở khóa khẩn cấp có ghi lý do (`FR-08`), cập nhật trạng thái tủ, xem nhật ký. |

---

## 3. Kết quả Kiểm thử Ma trận Đề xuất (Mục 7.3) & Chỉ tiêu Thực nghiệm (Mục 7.4)

Chạy toàn bộ bộ kiểm thử tự động:
```powershell
$env:PYTHONPATH = "d:\school\IoT\test"
.\.venv\Scripts\pytest.exe -v tests\test_smart_locker.py
```

| Mã TC | Tình huống kiểm thử | Kết quả Thực tế | Trạng thái |
| :--- | :--- | :--- | :--- |
| **TC-01** | Khách hàng gửi đồ khi có hộc tủ trống | Tạo phiên `ACTIVE`, cấp Hộc tủ `#1` (`OCCUPIED`), phát lệnh MQTT `OPEN`. | **PASSED** |
| **TC-02** | Khách hàng gửi đồ khi đã có phiên `ACTIVE` | Từ chối (`409 DUPLICATE_ACTIVE_SESSION`), báo rõ số tủ đang sử dụng. | **PASSED** |
| **TC-03** | Nhận đồ với khuôn mặt khớp ($\le 0.45$) | Mở đúng hộc tủ, chuyển phiên sang `COMPLETED`, giải phóng tủ về `AVAILABLE`. | **PASSED** |
| **TC-04** | Nhận đồ với khuôn mặt không khớp ($> 0.45$) | Từ chối (`401 FACE_NOT_MATCHED`), **không** phát lệnh MQTT mở khóa. | **PASSED** |
| **TC-05** | Không còn hộc tủ `AVAILABLE` | Từ chối (`409 NO_AVAILABLE_LOCKER`), không tạo phiên mới. | **PASSED** |
| **TC-06** | Relay đã mở đủ thời gian (5 giây) | Bộ đếm `millis()` tự động đưa chân GPIO 26/27 về `LOW` (`LOCKED`) sau 5s. | **PASSED** |
| **TC-07** | Cửa mở quá 30 giây | Kích hoạt Buzzer (`GPIO 15 HIGH`), gửi `DOOR_OPEN_TIMEOUT`, ghi log `DOOR_ALERT`. | **PASSED** |
| **TC-08** | Nhân viên yêu cầu mở khẩn cấp | Phát lệnh MQTT với `user_type="STAFF"`, lưu vết tài khoản, tủ và lý do vào `ActionLog`. | **PASSED** |
| **TC-09** | Mất kết nối MQTT | Phát hiện lỗi (`503 MQTT_COMMUNICATION_ERROR`), hủy giao dịch để bảo toàn dữ liệu. | **PASSED** |
| **TC-10** | Tài khoản không đủ quyền truy cập | Từ chối (`403 FORBIDDEN`) khi `STAFF` gọi API quản lý nhân viên hoặc tạo/xóa tủ. | **PASSED** |

### Số liệu Thực nghiệm Thu thập (Mục 7.4 - `scripts/run_experiments.py`)
- **Khoảng cách Euclidean cùng 1 khách hàng (Genuine pairs)**: `0.0170` – `0.1956` (nhỏ hơn ngưỡng `0.45` $\rightarrow$ Tỷ lệ nhận diện đúng **TAR = 100%**).
- **Khoảng cách Euclidean khác khách hàng (Impostor pairs)**: `0.7791` – `1.0211` (lớn hơn ngưỡng `0.45` $\rightarrow$ Tỷ lệ từ chối người lạ **TRR = 100%**, **FAR = 0%**).
- **Thời gian xử lý ảnh & trích xuất vector 128D trung bình**: `~12.0 ms` (P95: `18.19 ms`).
- **Thời gian phản hồi API đầu cuối (Store / Retrieve)**: `38.11 ms` – `57.13 ms`.
- **Thời gian phát lệnh MQTT Backend $\rightarrow$ ESP32**: `~4.85 ms` (Broker trực tuyến: `broker.hivemq.com:1883`).

# IoT-Smart-Locker-2
# IoT-Smart-Locker-2
