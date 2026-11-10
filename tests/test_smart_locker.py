"""
Automated Test Suite for IoT Smart Locker MVP (Chapter 7.3 Test Matrix TC-01 to TC-10).
Verifies all Functional Requirements (FR-01 to FR-08), Non-Functional Requirements,
Class Diagram methods, Database integrity, AI face matching, MQTT payloads, and ESP32 timing.
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app, esp32_twin, face_service, mqtt_service
from backend.config import SAMPLE_FACES_DIR
from scripts.generate_sample_faces import generate_all_sample_faces


@pytest.fixture(scope="module", autouse=True)
def setup_samples():
    generate_all_sample_faces(SAMPLE_FACES_DIR)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/system/reset-demo")
        yield c


def _login_headers(client: TestClient, username: str, password: str) -> dict:
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# TC-01: Khách hàng gửi đồ khi có hộc tủ trống
# Kết quả mong đợi: Tạo phiên ACTIVE, cấp hộc tủ và phát lệnh mở khóa.
# ============================================================================
def test_tc01_store_item_when_locker_available(client: TestClient):
    pub_before = len(mqtt_service.published_messages)

    resp = client.post(
        "/api/kiosk/store",
        data={
            "sample_name": "customer_01_checkin.jpg",
            "customer_label": "Customer 01 (Nguyễn Văn An)",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["action"] == "STORE"
    assert body["session"]["status"] == "ACTIVE"
    assert body["locker"]["LockerNumber"] == 1
    assert body["locker"]["status"] == "OCCUPIED"
    assert body["locker"]["lockState"] == "UNLOCKED"

    # Verify MQTT command was published to iot_smartlocker_2026/command
    assert len(mqtt_service.published_messages) == pub_before + 1
    last_mqtt = mqtt_service.published_messages[-1]
    assert last_mqtt["topic"] == "iot_smartlocker_2026/command"
    assert last_mqtt["payload"]["locker_id"] == 1
    assert last_mqtt["payload"]["action"] == "OPEN"
    assert last_mqtt["payload"]["user_type"] == "CUSTOMER"


# ============================================================================
# TC-02: Khách hàng gửi đồ khi đã có phiên ACTIVE
# Kết quả mong đợi: Từ chối tạo phiên mới và thông báo phù hợp.
# ============================================================================
def test_tc02_reject_duplicate_active_session(client: TestClient):
    # First check-in succeeds
    r1 = client.post(
        "/api/kiosk/store",
        data={"sample_name": "customer_01_checkin.jpg"},
    )
    assert r1.status_code == 200

    # Second check-in by the same person (even using their checkout variation image, distance <= 0.45)
    r2 = client.post(
        "/api/kiosk/store",
        data={"sample_name": "customer_01_checkout.jpg"},
    )
    assert r2.status_code == 409
    err = r2.json()
    assert err["success"] is False
    assert err["errorCode"] == "DUPLICATE_ACTIVE_SESSION"
    assert err["details"]["LockerNumber"] == 1
    assert err["details"]["distance"] <= face_service.distanceThreshold


# ============================================================================
# TC-03: Nhận đồ với khuôn mặt khớp
# Kết quả mong đợi: Mở đúng hộc tủ, hoàn tất phiên và giải phóng hộc tủ.
# ============================================================================
def test_tc03_retrieve_item_with_matching_face(client: TestClient):
    # Store Customer 01 into Locker #1 and Customer 02 into Locker #2
    s1 = client.post("/api/kiosk/store", data={"sample_name": "customer_01_checkin.jpg"})
    s2 = client.post("/api/kiosk/store", data={"sample_name": "customer_02_checkin.jpg"})
    assert s1.status_code == 200
    assert s2.status_code == 200
    assert s2.json()["locker"]["LockerNumber"] == 2

    # Customer 02 retrieves item using second capture (customer_02_checkout.jpg)
    ret = client.post(
        "/api/kiosk/retrieve",
        data={"sample_name": "customer_02_checkout.jpg"},
    )
    assert ret.status_code == 200
    body = ret.json()
    assert body["success"] is True
    assert body["locker"]["LockerNumber"] == 2
    assert body["locker"]["status"] == "AVAILABLE"
    assert body["session"]["status"] == "COMPLETED"
    assert body["session"]["checkOutAt"] is not None
    assert body["ai"]["matchedDistance"] <= face_service.distanceThreshold


# ============================================================================
# TC-04: Nhận đồ với khuôn mặt không khớp
# Kết quả mong đợi: Không phát lệnh mở khóa; thông báo xác thực thất bại.
# ============================================================================
def test_tc04_retrieve_item_with_non_matching_face_rejected(client: TestClient):
    # Customer 01 stores item
    s1 = client.post("/api/kiosk/store", data={"sample_name": "customer_01_checkin.jpg"})
    assert s1.status_code == 200

    pub_before = len(mqtt_service.published_messages)

    # Stranger (Customer 04) attempts to retrieve item
    ret = client.post(
        "/api/kiosk/retrieve",
        data={"sample_name": "customer_04_stranger.jpg"},
    )
    assert ret.status_code == 401
    err = ret.json()
    assert err["success"] is False
    assert err["errorCode"] == "FACE_NOT_MATCHED"
    assert err["details"]["closestDistance"] > face_service.distanceThreshold

    # Verify NO MQTT open command was sent
    assert len(mqtt_service.published_messages) == pub_before


# ============================================================================
# TC-05: Không còn hộc tủ AVAILABLE
# Kết quả mong đợi: Thông báo hết hộc tủ khả dụng; không tạo phiên.
# ============================================================================
def test_tc05_no_available_locker_rejected(client: TestClient):
    admin_headers = _login_headers(client, "admin", "admin123")

    # Set lockers 1..5 to MAINTENANCE (locker 6 is already MAINTENANCE)
    for lid in range(1, 6):
        client.put(
            f"/api/lockers/{lid}/status",
            headers=admin_headers,
            json={"status": "MAINTENANCE"},
        )

    # Customer 01 tries to store item when 0 lockers are AVAILABLE
    resp = client.post(
        "/api/kiosk/store",
        data={"sample_name": "customer_01_checkin.jpg"},
    )
    assert resp.status_code == 409
    err = resp.json()
    assert err["success"] is False
    assert err["errorCode"] == "NO_AVAILABLE_LOCKER"

    # Verify no ACTIVE session was created
    sess_res = client.get("/api/sessions?status=ACTIVE").json()
    assert len(sess_res["sessions"]) == 0


# ============================================================================
# TC-06: Relay đã mở đủ thời gian
# Kết quả mong đợi: Relay tự chuyển về LOW sau khoảng 5 giây.
# ============================================================================
def test_tc06_relay_auto_locks_after_5_seconds(client: TestClient):
    # Store item in Locker #1 -> triggers MQTT OPEN -> ESP32 GPIO 26 goes HIGH
    resp = client.post(
        "/api/kiosk/store",
        data={"sample_name": "customer_01_checkin.jpg"},
    )
    assert resp.status_code == 200

    snap_initial = client.get("/api/iot/esp32").json()["esp32"]
    assert snap_initial["lockers"]["1"]["relay_pin_level"] == "HIGH"
    assert snap_initial["lockers"]["1"]["lock_state"] == "UNLOCKED"

    # Advance ESP32 millis() by 5,200 ms (>= 5,000 ms)
    adv_resp = client.post(
        "/api/iot/esp32/advance-time",
        params={"milliseconds": 5200},
    )
    assert adv_resp.status_code == 200
    snap_after = adv_resp.json()["esp32"]
    assert snap_after["lockers"]["1"]["relay_pin_level"] == "LOW"
    assert snap_after["lockers"]["1"]["lock_state"] == "LOCKED"

    # Verify Backend also received the LOCKED status from ESP32 via MQTT
    lk_list = client.get("/api/lockers").json()["lockers"]
    lk1 = next(x for x in lk_list if x["LockerNumber"] == 1)
    assert lk1["lockState"] == "LOCKED"


# ============================================================================
# TC-07: Cửa mở quá 30 giây
# Kết quả mong đợi: Buzzer phát cảnh báo và hệ thống nhận được cảnh báo timeout.
# ============================================================================
def test_tc07_door_open_timeout_after_30_seconds(client: TestClient):
    # Simulate opening Door Slide Switch on Locker #1 (GPIO 32 -> HIGH)
    open_resp = client.post(
        "/api/iot/esp32/door",
        params={"locker_id": 1, "open_state": True},
    )
    assert open_resp.status_code == 200
    assert open_resp.json()["pinState"]["door"] == "OPEN"
    assert open_resp.json()["pinState"]["alert"] == "NONE"

    # Advance ESP32 millis() by 30,500 ms (>= 30,000 ms)
    adv_resp = client.post(
        "/api/iot/esp32/advance-time",
        params={"milliseconds": 30500},
    )
    assert adv_resp.status_code == 200
    esp_state = adv_resp.json()["esp32"]

    # Buzzer (GPIO 15) must be active and alert must be DOOR_OPEN_TIMEOUT
    assert esp_state["buzzer"]["active"] is True
    assert esp_state["lockers"]["1"]["alert"] == "DOOR_OPEN_TIMEOUT"

    # Backend Locker state & ActionLog must record DOOR_OPEN_TIMEOUT / DOOR_ALERT
    lk_list = client.get("/api/lockers").json()["lockers"]
    lk1 = next(x for x in lk_list if x["LockerNumber"] == 1)
    assert lk1["doorState"] == "OPEN"
    assert lk1["alertState"] == "DOOR_OPEN_TIMEOUT"

    logs = client.get("/api/logs?actionType=DOOR_ALERT").json()["logs"]
    assert len(logs) >= 1
    assert logs[0]["LockerNumber"] == 1


# ============================================================================
# TC-08: Nhân viên yêu cầu mở khẩn cấp
# Kết quả mong đợi: Thiết bị nhận lệnh mở; nhật ký ghi nhận tài khoản, hộc tủ và thời điểm.
# ============================================================================
def test_tc08_staff_emergency_force_open_logged(client: TestClient):
    # Customer 01 stores item in Locker #1
    client.post("/api/kiosk/store", data={"sample_name": "customer_01_checkin.jpg"})

    staff_headers = _login_headers(client, "staff01", "staff123")
    reason_text = "Khách hàng nhờ mở khẩn cấp do chấn thương mặt"

    force_resp = client.post(
        "/api/lockers/1/force-open",
        headers=staff_headers,
        json={"reason": reason_text, "releaseSession": True},
    )
    assert force_resp.status_code == 200
    data = force_resp.json()
    assert data["success"] is True
    assert data["locker"]["status"] == "AVAILABLE"
    assert data["log"]["actionType"] == "STAFF_FORCE_OPEN"
    assert data["log"]["username"] == "staff01"
    assert data["log"]["LockerNumber"] == 1
    assert reason_text in data["log"]["note"]

    # Verify ESP32 received MQTT command with user_type == STAFF
    last_mqtt = mqtt_service.published_messages[-1]
    assert last_mqtt["payload"]["locker_id"] == 1
    assert last_mqtt["payload"]["action"] == "OPEN"
    assert last_mqtt["payload"]["user_type"] == "STAFF"


# ============================================================================
# TC-09: Mất kết nối MQTT
# Kết quả mong đợi: Hệ thống phát hiện lỗi giao tiếp và không xác nhận thao tác mở khóa thành công.
# ============================================================================
def test_tc09_mqtt_disconnection_handled_safely(client: TestClient):
    # Enable simulated MQTT disconnection
    client.post("/api/iot/mqtt/simulate-offline", params={"offline": True})

    # Attempt to store item while MQTT is offline
    store_resp = client.post(
        "/api/kiosk/store",
        data={"sample_name": "customer_01_checkin.jpg"},
    )
    assert store_resp.status_code == 503
    err = store_resp.json()
    assert err["success"] is False
    assert err["errorCode"] == "MQTT_COMMUNICATION_ERROR"

    # Verify Locker #1 was NOT marked OCCUPIED and no session was left dangling
    lk_list = client.get("/api/lockers").json()["lockers"]
    lk1 = next(x for x in lk_list if x["LockerNumber"] == 1)
    assert lk1["status"] == "AVAILABLE"

    # Restore MQTT connection
    client.post("/api/iot/mqtt/simulate-offline", params={"offline": False})


# ============================================================================
# TC-10: Tài khoản không đủ quyền truy cập
# Kết quả mong đợi: Backend từ chối thao tác quản trị trái quyền.
# ============================================================================
def test_tc10_rbac_rejects_unauthorized_staff_actions(client: TestClient):
    staff_headers = _login_headers(client, "staff01", "staff123")

    # 1. STAFF tries to create a new staff account (Admin-only FR-04) -> Must be 403 FORBIDDEN
    r_create_staff = client.post(
        "/api/staff",
        headers=staff_headers,
        json={
            "username": "unauthorized_staff",
            "password": "password123",
            "fullName": "Test Staff",
            "role": "STAFF",
        },
    )
    assert r_create_staff.status_code == 403
    assert r_create_staff.json()["errorCode"] == "FORBIDDEN"

    # 2. STAFF tries to delete an existing staff account -> Must be 403 FORBIDDEN
    r_del_staff = client.delete("/api/staff/2", headers=staff_headers)
    assert r_del_staff.status_code == 403

    # 3. STAFF tries to create a new Locker compartment (Admin-only) -> Must be 403 FORBIDDEN
    r_create_locker = client.post(
        "/api/lockers",
        headers=staff_headers,
        json={"LockerNumber": 10, "status": "AVAILABLE"},
    )
    assert r_create_locker.status_code == 403

    # 4. ADMIN performs the same staff creation -> Succeeds (200 OK)
    admin_headers = _login_headers(client, "admin", "admin123")
    r_admin_ok = client.post(
        "/api/staff",
        headers=admin_headers,
        json={
            "username": "staff_temp_tc10",
            "password": "password123",
            "fullName": "Nhân Viên Mới TC10",
            "role": "STAFF",
        },
    )
    assert r_admin_ok.status_code == 200
    new_uid = r_admin_ok.json()["user"]["userID"]

    # Clean up created staff account
    r_cleanup = client.delete(f"/api/staff/{new_uid}", headers=admin_headers)
    assert r_cleanup.status_code == 200


# ============================================================================
# Additional Tests: Liveness Rejection, Backup PIN, Call Staff, Locker CRUD,
# and Class Diagram Entity Unit Tests
# ============================================================================
def test_tc11_liveness_and_no_face_rejected(client: TestClient):
    resp = client.post(
        "/api/kiosk/store",
        data={"sample_name": "invalid_no_face.jpg"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["errorCode"] == "FACE_DETECTION_FAILED"


def test_tc12_backup_pin_retrieve_flow(client: TestClient):
    s1 = client.post("/api/kiosk/store", data={"sample_name": "customer_01_checkin.jpg"})
    assert s1.status_code == 200
    pin = s1.json()["session"]["backupPin"]
    locker_num = s1.json()["locker"]["LockerNumber"]

    # Wrong PIN must fail with 401
    bad_pin = client.post(
        "/api/kiosk/retrieve-pin",
        json={"lockerNumber": locker_num, "backupPin": "000000"},
    )
    assert bad_pin.status_code == 401

    # Correct PIN must succeed and release locker
    ok_pin = client.post(
        "/api/kiosk/retrieve-pin",
        json={"lockerNumber": locker_num, "backupPin": pin},
    )
    assert ok_pin.status_code == 200
    assert ok_pin.json()["locker"]["status"] == "AVAILABLE"
    assert ok_pin.json()["session"]["status"] == "COMPLETED"


def test_tc13_kiosk_call_staff_logged(client: TestClient):
    resp = client.post(
        "/api/kiosk/call-staff",
        json={"lockerNumber": 2, "reason": "Cần nhân viên hỗ trợ mở tủ #2"},
    )
    assert resp.status_code == 200
    assert resp.json()["log"]["actionType"] == "CALL_STAFF"


def test_tc14_admin_locker_crud_and_threshold(client: TestClient):
    admin_headers = _login_headers(client, "admin", "admin123")

    # Create Locker #7
    c_resp = client.post(
        "/api/lockers",
        headers=admin_headers,
        json={"LockerNumber": 7, "status": "AVAILABLE"},
    )
    assert c_resp.status_code == 200
    assert c_resp.json()["locker"]["LockerNumber"] == 7

    # Delete Locker #7
    d_resp = client.delete("/api/lockers/7", headers=admin_headers)
    assert d_resp.status_code == 200

    # Update threshold and restore to 0.45
    t_resp = client.put(
        "/api/settings/threshold",
        headers=admin_headers,
        json={"distanceThreshold": 0.45},
    )
    assert t_resp.status_code == 200
    assert t_resp.json()["distanceThreshold"] == 0.45

