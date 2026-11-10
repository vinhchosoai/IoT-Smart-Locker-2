import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.getenv("SMART_LOCKER_API_URL", "http://127.0.0.1:8000")
BASE_DIR = Path(__file__).resolve().parent.parent


def api_request(
    method: str,
    endpoint: str,
    token: Optional[str] = None,
    json_data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"{API_BASE_URL}{endpoint}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
            params=params,
            files=files,
            data=data,
            timeout=10,
        )
        try:
            payload = resp.json()
        except Exception:
            payload = {"success": False, "message": resp.text}
        payload["_http_status"] = resp.status_code
        return payload
    except Exception as exc:
        return {
            "success": False,
            "errorCode": "BACKEND_UNREACHABLE",
            "message": f"Không thể kết nối tới FastAPI Backend ({API_BASE_URL}): {exc}",
            "_http_status": 503,
        }


def inject_custom_css():
    st.markdown(
        """
        <style>
        .locker-card {
            border-radius: 12px;
            padding: 14px 16px;
            margin-bottom: 12px;
            border: 1px solid rgba(128, 128, 128, 0.25);
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
        }
        .locker-available {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.14), rgba(5, 150, 105, 0.06));
            border-left: 6px solid #10b981;
        }
        .locker-occupied {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.16), rgba(217, 119, 6, 0.06));
            border-left: 6px solid #f59e0b;
        }
        .locker-maintenance {
            background: linear-gradient(135deg, rgba(107, 114, 128, 0.16), rgba(75, 85, 99, 0.06));
            border-left: 6px solid #6b7280;
        }
        .locker-alert {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.22), rgba(185, 28, 28, 0.10));
            border-left: 6px solid #ef4444;
        }
        .lcd-screen {
            font-family: 'Courier New', Courier, monospace;
            background-color: #1b3b1a;
            color: #7cfc00;
            border: 4px solid #374151;
            border-radius: 8px;
            padding: 14px 18px;
            font-size: 20px;
            font-weight: bold;
            letter-spacing: 2px;
            line-height: 1.45;
            text-shadow: 0 0 6px rgba(124, 252, 0, 0.55);
            margin-bottom: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_locker_grid(lockers: list):
    cols = st.columns(3)
    for idx, lk in enumerate(lockers):
        col = cols[idx % 3]
        status = lk.get("status", "AVAILABLE")
        door = lk.get("doorState", "CLOSED")
        lock_st = lk.get("lockState", "LOCKED")
        alert = lk.get("alertState", "NONE")
        active_sess = lk.get("activeSession")

        if alert == "DOOR_OPEN_TIMEOUT":
            css_class = "locker-alert"
            badge = "🚨 CẢNH BÁO CỬA MỞ >30s"
        elif status == "AVAILABLE":
            css_class = "locker-available"
            badge = "🟢 TRỐNG (AVAILABLE)"
        elif status == "OCCUPIED":
            css_class = "locker-occupied"
            badge = "🟠 ĐANG SỬ DỤNG (OCCUPIED)"
        else:
            css_class = "locker-maintenance"
            badge = "⚪ BẢO TRÌ (MAINTENANCE)"

        door_icon = "🚪 Cửa: MỞ (OPEN)" if door == "OPEN" else "🚪 Cửa: ĐÓNG (CLOSED)"
        lock_icon = (
            "🔓 Khóa: MỞ (UNLOCKED)"
            if lock_st == "UNLOCKED"
            else "🔒 Khóa: ĐÓNG (LOCKED)"
        )
        sess_html = ""
        if active_sess:
            sess_html = (
                f"<div style='font-size:12px; margin-top:6px; opacity:0.9;'>"
                f"📌 Phiên <b>#{active_sess.get('sessionID')}</b> | "
                f"PIN: <code>{active_sess.get('backupPin', '---')}</code>"
                f"</div>"
            )

        with col:
            st.markdown(
                f"""
                <div class="locker-card {css_class}">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:18px; font-weight:700;">TỦ SỐ #{lk['LockerNumber']}</span>
                        <span style="font-size:12px; font-weight:600;">{badge}</span>
                    </div>
                    <div style="font-size:13px; margin-top:6px;">
                        {door_icon} &nbsp;|&nbsp; {lock_icon}
                    </div>
                    {sess_html}
                </div>
                """,
                unsafe_allow_html=True,
            )


# ============================================================================
# VIEW 1: CUSTOMER KIOSK (FR-01, FR-02, Call Staff)
# ============================================================================
def render_kiosk_view():
    st.subheader("🖥️ Kiosk Khách Hàng - Gửi & Nhận Đồ Bằng Khuôn Mặt (YOLOv5 + 128D AI)")

    lockers_res = api_request("GET", "/api/lockers")
    lockers = lockers_res.get("lockers", []) if lockers_res.get("success") else []

    avail_count = sum(1 for x in lockers if x.get("status") == "AVAILABLE")
    occ_count = sum(1 for x in lockers if x.get("status") == "OCCUPIED")
    alert_count = sum(
        1 for x in lockers if x.get("alertState") == "DOOR_OPEN_TIMEOUT"
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tổng số Hộc tủ", len(lockers))
    m2.metric("Hộc tủ Khả dụng (AVAILABLE)", avail_count)
    m3.metric("Đang gửi đồ (OCCUPIED)", occ_count)
    m4.metric("Cảnh báo Cửa", alert_count)

    render_locker_grid(lockers)
    st.divider()

    left_col, right_col = st.columns([1.05, 1.15])

    with left_col:
        st.markdown("#### 1️⃣ Thu nhận Khuôn mặt tại Kiosk")
        input_mode = st.radio(
            "Phương thức thu nhận hình ảnh:",
            options=[
                "🎭 Mô phỏng (Chọn khuôn mặt mẫu)",
                "📷 Camera trực tiếp (Webcam)",
                "📁 Tải tệp ảnh lên",
            ],
            horizontal=True,
        )

        selected_sample: Optional[str] = None
        selected_label: Optional[str] = None
        uploaded_bytes: Optional[bytes] = None

        if input_mode.startswith("🎭"):
            samples_res = api_request("GET", "/api/kiosk/sample-faces")
            samples = samples_res.get("samples", [])
            if samples:
                labels_map = {s["label"]: s["filename"] for s in samples}
                chosen_label = st.selectbox(
                    "Chọn khách hàng / tình huống kiểm thử:",
                    options=list(labels_map.keys()),
                )
                selected_sample = labels_map[chosen_label]
                selected_label = chosen_label
                img_path = BASE_DIR / "data" / "sample_faces" / selected_sample
                if img_path.exists():
                    st.image(
                        str(img_path),
                        caption=f"Ảnh đầu vào Camera Kiosk: {chosen_label}",
                        width=280,
                    )
        elif input_mode.startswith("📷"):
            cam_photo = st.camera_input("Nhìn thẳng vào Camera để xác thực khuôn mặt")
            if cam_photo is not None:
                uploaded_bytes = cam_photo.getvalue()
        else:
            up_file = st.file_uploader(
                "Chọn ảnh khuôn mặt (.jpg, .png)", type=["jpg", "jpeg", "png"]
            )
            if up_file is not None:
                uploaded_bytes = up_file.getvalue()
                st.image(uploaded_bytes, caption="Ảnh tải lên", width=280)

    with right_col:
        st.markdown("#### 2️⃣ Chọn Thao tác Nghiệp vụ")
        st.info(
            "💡 **Quy trình chuẩn:**\n"
            "- **Gửi đồ (FR-01):** Kiểm tra chống gửi trùng (khoảng cách Euclidean $\\le 0.45$) $\\rightarrow$ Cấp tủ trống $\\rightarrow$ Mở khóa MQTT 5 giây.\n"
            "- **Nhận đồ (FR-02):** Đối sánh vector 128 chiều với các phiên ACTIVE $\\rightarrow$ Mở đúng hộc tủ $\\rightarrow$ Hoàn tất phiên (COMPLETED) & giải phóng tủ về AVAILABLE."
        )

        b_store, b_retrieve = st.columns(2)

        with b_store:
            store_clicked = st.button(
                "📦 GỬI ĐỒ (STORE ITEM)",
                type="primary",
                use_container_width=True,
            )
        with b_retrieve:
            retrieve_clicked = st.button(
                "🔓 NHẬN ĐỒ (RETRIEVE ITEM)",
                type="secondary",
                use_container_width=True,
            )

        if store_clicked:
            with st.spinner("Đang nhận diện khuôn mặt YOLOv5 và cấp phát hộc tủ..."):
                if uploaded_bytes is not None:
                    res = api_request(
                        "POST",
                        "/api/kiosk/store",
                        files={"file": ("capture.jpg", uploaded_bytes, "image/jpeg")},
                        data={"customer_label": "Camera/Upload Customer"},
                    )
                else:
                    res = api_request(
                        "POST",
                        "/api/kiosk/store",
                        data={
                            "sample_name": selected_sample,
                            "customer_label": selected_label,
                        },
                    )
                st.session_state["last_kiosk_result"] = res
                st.rerun()

        if retrieve_clicked:
            with st.spinner("Đang đối sánh vector đặc trưng 128D và mở khóa hộc tủ..."):
                if uploaded_bytes is not None:
                    res = api_request(
                        "POST",
                        "/api/kiosk/retrieve",
                        files={"file": ("capture.jpg", uploaded_bytes, "image/jpeg")},
                    )
                else:
                    res = api_request(
                        "POST",
                        "/api/kiosk/retrieve",
                        data={"sample_name": selected_sample},
                    )
                st.session_state["last_kiosk_result"] = res
                st.rerun()

        # Display last Kiosk transaction result
        last_res = st.session_state.get("last_kiosk_result")
        if last_res:
            if last_res.get("success"):
                st.success(f"✅ {last_res.get('message')}")
                lk_info = last_res.get("locker", {})
                sess_info = last_res.get("session", {})
                ai_info = last_res.get("ai", {})

                r1, r2, r3 = st.columns(3)
                r1.metric("Hộc tủ được mở", f"Tủ #{lk_info.get('LockerNumber')}")
                r2.metric(
                    "Mã PIN Dự phòng",
                    sess_info.get("backupPin", "N/A"),
                )
                r3.metric("Thời gian xử lý", f"{last_res.get('latencyMs', 0)} ms")

                if ai_info.get("annotatedImageB64"):
                    img_data = base64.b64decode(ai_info["annotatedImageB64"])
                    st.image(
                        img_data,
                        caption=(
                            f"Kết quả YOLOv5-Face (Confidence={ai_info.get('confidence')}, "
                            f"Liveness={'PASS' if ai_info.get('liveness') else 'FAIL'}, "
                            f"Ngưỡng={ai_info.get('threshold')})"
                        ),
                        width=300,
                    )
            else:
                st.error(
                    f"❌ **[{last_res.get('errorCode', 'ERROR')}]** {last_res.get('message')}"
                )
                if last_res.get("details"):
                    st.caption(f"Chi tiết kỹ thuật: `{json.dumps(last_res['details'], ensure_ascii=False)}`")

        st.markdown("---")
        with st.expander("🔢 Nhận đồ bằng Mã PIN Dự phòng / 🆘 Gọi Nhân viên Hỗ trợ"):
            p_col1, p_col2 = st.columns(2)
            with p_col1:
                st.markdown("**Mở tủ bằng Backup PIN**")
                pin_locker = st.number_input("Số hộc tủ", min_value=1, max_value=20, value=1)
                pin_val = st.text_input("Mã PIN 6 số (cấp khi gửi đồ)")
                if st.button("Xác nhận mở bằng PIN", use_container_width=True):
                    pin_res = api_request(
                        "POST",
                        "/api/kiosk/retrieve-pin",
                        json_data={"lockerNumber": int(pin_locker), "backupPin": pin_val},
                    )
                    st.session_state["last_kiosk_result"] = pin_res
                    st.rerun()

            with p_col2:
                st.markdown("**Yêu cầu Nhân viên Hỗ trợ (Use Case: Call Staff)**")
                help_locker = st.number_input(
                    "Số tủ gặp sự cố (tùy chọn)", min_value=1, max_value=20, value=1, key="help_lk"
                )
                help_reason = st.text_input(
                    "Nội dung cần hỗ trợ",
                    value="Không xác thực được khuôn mặt tại Kiosk, nhờ nhân viên hỗ trợ.",
                )
                if st.button("🆘 Gửi Yêu Cầu Hỗ Trợ", use_container_width=True):
                    call_res = api_request(
                        "POST",
                        "/api/kiosk/call-staff",
                        json_data={"lockerNumber": int(help_locker), "reason": help_reason},
                    )
                    if call_res.get("success"):
                        st.toast("Đã gửi thông báo hỗ trợ tới Dashboard Nhân viên!", icon="🔔")
                        st.success(call_res.get("message"))


# ============================================================================
# VIEW 2: STAFF & ADMIN DASHBOARD (FR-03, FR-04, FR-05, FR-07, FR-08)
# ============================================================================
def render_dashboard_view():
    st.subheader("🛡️ Hệ thống Quản trị & Giám sát Tủ đồ (Staff & Admin Dashboard)")

    token = st.session_state.get("auth_token")
    current_user = st.session_state.get("auth_user")

    if not token or not current_user:
        st.info("🔐 Vui lòng đăng nhập tài khoản **Nhân viên (STAFF)** hoặc **Quản trị viên (ADMIN)** để truy cập Dashboard.")
        c_login, c_hint = st.columns([1, 1])
        with c_login:
            with st.form("login_form"):
                uname = st.text_input("Tên đăng nhập (Username)", value="admin")
                upass = st.text_input("Mật khẩu (Password)", value="admin123", type="password")
                submitted = st.form_submit_button("Đăng nhập hệ thống", type="primary", use_container_width=True)
                if submitted:
                    res = api_request(
                        "POST",
                        "/api/auth/login",
                        json_data={"username": uname, "password": upass},
                    )
                    if res.get("success"):
                        st.session_state["auth_token"] = res["token"]
                        st.session_state["auth_user"] = res["user"]
                        st.rerun()
                    else:
                        st.error(res.get("message", "Đăng nhập thất bại."))

        with c_hint:
            st.markdown(
                """
                #### 📋 Tài khoản Mặc định (Phân quyền RBAC - FR-04):
                - **Quản trị viên (ADMIN):**
                  - Username: `admin` | Password: `admin123`
                  - Quyền hạn: Toàn quyền quản lý hộc tủ, mở khẩn cấp, quản lý nhân viên, xem nhật ký, cấu hình ngưỡng AI.
                - **Nhân viên trực (STAFF):**
                  - Username: `staff01` | Password: `staff123`
                  - Quyền hạn: Giám sát trạng thái tủ, mở khóa khẩn cấp (FR-08), cập nhật trạng thái tủ, xem nhật ký. Không có quyền thêm/xóa nhân viên (TC-10).
                """
            )
            q1, q2 = st.columns(2)
            if q1.button("⚡ Đăng nhập nhanh ADMIN", use_container_width=True):
                res = api_request("POST", "/api/auth/login", json_data={"username": "admin", "password": "admin123"})
                if res.get("success"):
                    st.session_state["auth_token"] = res["token"]
                    st.session_state["auth_user"] = res["user"]
                    st.rerun()
            if q2.button("⚡ Đăng nhập nhanh STAFF", use_container_width=True):
                res = api_request("POST", "/api/auth/login", json_data={"username": "staff01", "password": "staff123"})
                if res.get("success"):
                    st.session_state["auth_token"] = res["token"]
                    st.session_state["auth_user"] = res["user"]
                    st.rerun()
        return

    # Logged-in Header Bar
    h1, h2, h3 = st.columns([2.5, 1.5, 1])
    h1.markdown(
        f"👤 Đang đăng nhập: **{current_user.get('fullName')}** (`{current_user.get('username')}`) "
        f"— Vai trò: **`{current_user.get('role')}`**"
    )
    metrics_res = api_request("GET", "/api/metrics")
    db_type = metrics_res.get("database", {}).get("engineType", "MySQL")
    h2.markdown(f"🗄️ CSDL: **`{db_type}`** | 📡 MQTT: **`{metrics_res.get('mqtt', {}).get('brokerMode', 'OK')}`**")
    if h3.button("🚪 Đăng xuất", use_container_width=True):
        st.session_state.pop("auth_token", None)
        st.session_state.pop("auth_user", None)
        st.rerun()

    # Check Door Alerts (FR-07 / TC-07)
    lockers_res = api_request("GET", "/api/lockers", token=token)
    lockers = lockers_res.get("lockers", [])
    timeout_lockers = [
        lk for lk in lockers if lk.get("alertState") == "DOOR_OPEN_TIMEOUT"
    ]
    if timeout_lockers:
        nums = ", ".join(f"#{x['LockerNumber']}" for x in timeout_lockers)
        st.error(
            f"🚨 **CẢNH BÁO AN NINH IoT (DOOR_OPEN_TIMEOUT - FR-07):** "
            f"Cửa hộc tủ **{nums}** đang mở quá thời gian quy định (30 giây)! "
            "Còi Buzzer trên ESP32 đang phát âm báo. Vui lòng kiểm tra và đóng cửa tủ!"
        )

    tab_lockers, tab_staff, tab_logs, tab_metrics = st.tabs(
        [
            "🗄️ Quản lý & Mở Khẩn Cấp Hộc Tủ (FR-03, FR-08)",
            "👥 Quản lý Nhân Viên (FR-04, TC-10)",
            "📜 Nhật ký Hoạt động (FR-05)",
            "📊 Chỉ tiêu Đánh giá Thực nghiệm (Mục 7.4)",
        ]
    )

    with tab_lockers:
        render_locker_grid(lockers)
        st.divider()
        c_force, c_status, c_crud = st.columns(3)

        locker_numbers = [lk["LockerNumber"] for lk in lockers] if lockers else [1]

        with c_force:
            st.markdown("#### 🚨 Mở Khóa Khẩn Cấp (FR-08 / TC-08)")
            f_locker = st.selectbox("Chọn Hộc tủ cần mở:", options=locker_numbers, key="f_lk")
            f_reason = st.text_input(
                "Lý do mở khẩn cấp (Bắt buộc lưu vết):",
                value="Khách hàng mất khả năng xác thực khuôn mặt, đã kiểm tra giấy tờ tùy thân.",
            )
            f_release = st.checkbox(
                "Kết thúc phiên ACTIVE và giải phóng tủ về AVAILABLE",
                value=True,
            )
            if st.button("🔓 Phát Lệnh Mở Khẩn Cấp (MQTT)", type="primary", use_container_width=True):
                res = api_request(
                    "POST",
                    f"/api/lockers/{f_locker}/force-open",
                    token=token,
                    json_data={"reason": f_reason, "releaseSession": f_release},
                )
                if res.get("success"):
                    st.success(f"Đã phát lệnh mở khẩn cấp Tủ #{f_locker} và ghi nhận vào ActionLog!")
                    st.rerun()
                else:
                    st.error(res.get("message"))

        with c_status:
            st.markdown("#### 🔧 Cập nhật Trạng thái Tủ (FR-03)")
            u_locker = st.selectbox("Chọn Hộc tủ:", options=locker_numbers, key="u_lk")
            u_status = st.selectbox(
                "Trạng thái sử dụng mới:",
                options=["AVAILABLE", "OCCUPIED", "MAINTENANCE"],
            )
            u_door = st.selectbox(
                "Trạng thái cửa (tùy chọn):",
                options=["Giữ nguyên", "CLOSED", "OPEN"],
            )
            if st.button("💾 Cập nhật Trạng thái", use_container_width=True):
                payload = {"status": u_status}
                if u_door != "Giữ nguyên":
                    payload["doorState"] = u_door
                res = api_request(
                    "PUT",
                    f"/api/lockers/{u_locker}/status",
                    token=token,
                    json_data=payload,
                )
                if res.get("success"):
                    st.success(f"Đã cập nhật Tủ #{u_locker} -> {u_status}")
                    st.rerun()
                else:
                    st.error(res.get("message"))

        with c_crud:
            st.markdown("#### ➕ Thêm / Xóa Hộc Tủ (Quyền ADMIN)")
            next_num = max(locker_numbers) + 1 if locker_numbers else 1
            new_lk_num = st.number_input("Số Hộc tủ mới:", min_value=1, max_value=99, value=next_num)
            new_lk_st = st.selectbox("Trạng thái ban đầu:", options=["AVAILABLE", "MAINTENANCE"])
            if st.button("➕ Tạo Hộc Tủ Mới", use_container_width=True):
                res = api_request(
                    "POST",
                    "/api/lockers",
                    token=token,
                    json_data={"LockerNumber": int(new_lk_num), "status": new_lk_st},
                )
                if res.get("success"):
                    st.success(f"Đã tạo Hộc tủ #{new_lk_num}!")
                    st.rerun()
                else:
                    st.error(f"[{res.get('errorCode')}] {res.get('message')}")

            del_lk_num = st.selectbox("Chọn tủ cần xóa:", options=locker_numbers, key="del_lk")
            if st.button("🗑️ Xóa Hộc Tủ", use_container_width=True):
                res = api_request("DELETE", f"/api/lockers/{del_lk_num}", token=token)
                if res.get("success"):
                    st.success(f"Đã xóa Hộc tủ #{del_lk_num}!")
                    st.rerun()
                else:
                    st.error(f"[{res.get('errorCode')}] {res.get('message')}")

    with tab_staff:
        st.markdown("#### 👥 Danh sách Tài khoản Nhân viên & Quản trị viên (FR-04)")
        staff_res = api_request("GET", "/api/staff", token=token)
        staff_list = staff_res.get("staff", [])
        if staff_list:
            st.dataframe(pd.DataFrame(staff_list), use_container_width=True, hide_index=True)

        st.divider()
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown("##### ➕ Tạo Tài khoản Mới (Chỉ ADMIN - Kiểm thử TC-10)")
            with st.form("create_staff_form"):
                new_uname = st.text_input("Tên đăng nhập (username)")
                new_fname = st.text_input("Họ và tên (fullName)")
                new_pass = st.text_input("Mật khẩu", type="password")
                new_role = st.selectbox("Vai trò (role)", options=["STAFF", "ADMIN"])
                if st.form_submit_button("Tạo Tài khoản", type="primary"):
                    res = api_request(
                        "POST",
                        "/api/staff",
                        token=token,
                        json_data={
                            "username": new_uname,
                            "fullName": new_fname,
                            "password": new_pass,
                            "role": new_role,
                        },
                    )
                    if res.get("success"):
                        st.success(f"Đã tạo tài khoản '{new_uname}' thành công!")
                        st.rerun()
                    else:
                        st.error(f"❌ [{res.get('errorCode')}] {res.get('message')}")

        with sc2:
            st.markdown("##### ✏️ Cập nhật / Xóa Tài khoản (Chỉ ADMIN)")
            if staff_list:
                user_options = {
                    f"#{u['userID']} - {u['username']} ({u['role']})": u["userID"]
                    for u in staff_list
                }
                chosen_u_label = st.selectbox("Chọn tài khoản:", options=list(user_options.keys()))
                chosen_uid = user_options[chosen_u_label]
                upd_fname = st.text_input("Họ tên mới (để trống nếu giữ nguyên)")
                upd_role = st.selectbox("Vai trò mới:", options=["STAFF", "ADMIN"], key="upd_r")
                upd_pass = st.text_input("Mật khẩu mới (để trống nếu giữ nguyên)", type="password")

                uc1, uc2 = st.columns(2)
                if uc1.button("💾 Lưu thay đổi", use_container_width=True):
                    payload: Dict[str, Any] = {"role": upd_role}
                    if upd_fname.strip():
                        payload["fullName"] = upd_fname.strip()
                    if upd_pass.strip():
                        payload["password"] = upd_pass.strip()
                    res = api_request("PUT", f"/api/staff/{chosen_uid}", token=token, json_data=payload)
                    if res.get("success"):
                        st.success("Cập nhật tài khoản thành công!")
                        st.rerun()
                    else:
                        st.error(f"❌ [{res.get('errorCode')}] {res.get('message')}")

                if uc2.button("🗑️ Xóa tài khoản", use_container_width=True):
                    res = api_request("DELETE", f"/api/staff/{chosen_uid}", token=token)
                    if res.get("success"):
                        st.success(f"Đã xóa tài khoản {res.get('deletedUsername')}!")
                        st.rerun()
                    else:
                        st.error(f"❌ [{res.get('errorCode')}] {res.get('message')}")

    with tab_logs:
        st.markdown("#### 📜 Nhật ký Hoạt động Hệ thống (ActionLog - FR-05)")
        f1, f2, f3 = st.columns(3)
        action_filter = f1.selectbox(
            "Lọc theo Loại Sự kiện (actionType):",
            options=[
                "Tất cả",
                "CLIENT_STORE",
                "CLIENT_RETRIEVE",
                "STAFF_FORCE_OPEN",
                "DOOR_ALERT",
                "CALL_STAFF",
                "LOCKER_STATUS_UPDATE",
                "STAFF_MANAGEMENT",
            ],
        )
        locker_filter = f2.selectbox(
            "Lọc theo Hộc tủ:",
            options=["Tất cả"] + [str(x["LockerID"]) for x in lockers],
        )
        limit_val = f3.number_input("Số bản ghi tối đa:", min_value=10, max_value=500, value=100)

        params: Dict[str, Any] = {"limit": int(limit_val)}
        if action_filter != "Tất cả":
            params["actionType"] = action_filter
        if locker_filter != "Tất cả":
            params["LockerID"] = int(locker_filter)

        logs_res = api_request("GET", "/api/logs", token=token, params=params)
        logs_data = logs_res.get("logs", [])
        if logs_data:
            df_logs = pd.DataFrame(logs_data)[
                [
                    "logID",
                    "timestamp",
                    "actionType",
                    "LockerNumber",
                    "username",
                    "sessionID",
                    "note",
                ]
            ]
            st.dataframe(df_logs, use_container_width=True, hide_index=True)
            csv_bytes = df_logs.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "📥 Xuất Nhật ký ra CSV",
                data=csv_bytes,
                file_name="smart_locker_action_logs.csv",
                mime="text/csv",
            )
        else:
            st.info("Chưa có bản ghi nhật ký nào khớp bộ lọc.")

    with tab_metrics:
        st.markdown("#### 📊 Chỉ tiêu Đánh giá Hệ thống (Mục 7.4 Báo cáo)")
        if metrics_res.get("success"):
            ai_m = metrics_res.get("ai", {})
            api_m = metrics_res.get("api", {})
            mqtt_m = metrics_res.get("mqtt", {})
            sess_m = metrics_res.get("sessions", {})

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Thời gian xử lý AI TB", f"{ai_m.get('avgProcessingTimeMs', 0)} ms")
            k2.metric("Thời gian phản hồi API TB", f"{api_m.get('avgLatencyMs', 0)} ms")
            k3.metric("Độ trễ phát lệnh MQTT TB", f"{mqtt_m.get('avgDispatchLatencyMs', 0)} ms")
            k4.metric("Ngưỡng khoảng cách AI", f"{ai_m.get('distanceThreshold', 0.45)}")

            st.markdown("##### ⚙️ Hiệu chỉnh Ngưỡng Xác thực Khuôn mặt (Mục 2.5 - Mặc định 0.45)")
            new_thresh = st.slider(
                "Ngưỡng khoảng cách Euclidean tối đa (<= ngưỡng được tính là cùng 1 người):",
                min_value=0.20,
                max_value=0.90,
                value=float(ai_m.get("distanceThreshold", 0.45)),
                step=0.01,
            )
            if st.button("Cập nhật Ngưỡng AI"):
                t_res = api_request(
                    "PUT",
                    "/api/settings/threshold",
                    token=token,
                    json_data={"distanceThreshold": new_thresh},
                )
                if t_res.get("success"):
                    st.success(f"Đã cập nhật ngưỡng khoảng cách AI thành {new_thresh}!")
                    st.rerun()
                else:
                    st.error(t_res.get("message"))

            st.json(metrics_res)


# ============================================================================
# VIEW 3: VIRTUAL ESP32 WOKWI HARDWARE SIMULATOR (Chapter 6, TC-06, TC-07, TC-09)
# ============================================================================
def render_esp32_wokwi_view():
    st.subheader("🔌 Mô phỏng Phần cứng ESP32 trên Wokwi & Kênh truyền MQTT (Chương 6)")

    iot_res = api_request("GET", "/api/iot/esp32")
    if not iot_res.get("success"):
        st.error(iot_res.get("message", "Không lấy được trạng thái ESP32."))
        return

    esp = iot_res["esp32"]
    mqtt_info = iot_res["mqtt"]
    lcd = esp["lcd"]
    buzzer = esp["buzzer"]
    esp_lockers = esp["lockers"]

    top_left, top_right = st.columns([1.1, 1.2])

    with top_left:
        st.markdown("#### 📟 Màn hình LCD 1602 I2C (`SDA: GPIO 21, SCL: GPIO 22`)")
        st.markdown(
            f"""
            <div class="lcd-screen">
                <div>{lcd['line1'].replace(' ', '&nbsp;')}</div>
                <div>{lcd['line2'].replace(' ', '&nbsp;')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        bz_color = "🔴 ĐANG KÊU CẢNH BÁO (HIGH)" if buzzer["active"] else "🟢 TẮT (LOW)"
        st.markdown(
            f"**🔊 Còi báo Buzzer (`GPIO {buzzer['gpio']}`):** {bz_color} &nbsp;|&nbsp; "
            f"**⏱️ Bộ đếm `millis()`:** `{esp['millis']} ms`"
        )

        st.markdown("#### ⚡ Công tắc & Kiểm thử Tình huống Phần cứng (TC-06, TC-07, TC-09)")
        b1, b2, b3 = st.columns(3)
        if b1.button("⏩ Tua +5.5 giây (TC-06: Relay tự ngắt)", use_container_width=True):
            api_request("POST", "/api/iot/esp32/advance-time", params={"milliseconds": 5500})
            st.rerun()
        if b2.button("⏩ Tua +31 giây (TC-07: Cảnh báo Cửa >30s)", use_container_width=True):
            api_request("POST", "/api/iot/esp32/advance-time", params={"milliseconds": 31000})
            st.rerun()

        offline_now = mqtt_info.get("simulateOffline", False)
        btn_label = (
            "🟢 Khôi phục Kết nối MQTT"
            if offline_now
            else "🔌 Ngắt kết nối MQTT (Kiểm thử TC-09)"
        )
        if b3.button(btn_label, use_container_width=True):
            api_request(
                "POST",
                "/api/iot/mqtt/simulate-offline",
                params={"offline": not offline_now},
            )
            st.rerun()

    with top_right:
        st.markdown("#### 🔩 Trạng thái Chân GPIO Relay & Cảm biến Cửa từ (Slide Switch)")
        for lid_str, pstate in list(esp_lockers.items())[:2]:
            lid = int(lid_str)
            with st.container(border=True):
                c1, c2, c3 = st.columns([1.4, 1.3, 1.1])
                c1.markdown(
                    f"**Hộc tủ #{lid}**\n"
                    f"- Relay `GPIO {pstate['relay_gpio']}`: **`{pstate['relay_pin_level']}`** ({pstate['lock_state']})\n"
                    f"- Tự ngắt còn: `{pstate['relay_remaining_sec']}s`"
                )
                c2.markdown(
                    f"**Cảm biến cửa `GPIO {pstate['sensor_gpio']}`**\n"
                    f"- Cửa: **`{pstate['door']}`** (Mở `{pstate['door_open_elapsed_sec']}s`)\n"
                    f"- Cảnh báo: **`{pstate['alert']}`**"
                )
                is_open = pstate["door"] == "OPEN"
                toggle_label = (
                    f"Đóng cửa Tủ #{lid} (LOW)"
                    if is_open
                    else f"Mở cửa Tủ #{lid} (HIGH)"
                )
                if c3.button(toggle_label, key=f"sw_btn_{lid}", use_container_width=True):
                    api_request(
                        "POST",
                        "/api/iot/esp32/door",
                        params={"locker_id": lid, "open_state": not is_open},
                    )
                    st.rerun()

    st.divider()
    m_col1, m_col2 = st.columns(2)
    with m_col1:
        st.markdown("#### 📡 Bản tin MQTT `iot_smartlocker_2026/command` & `status`")
        st.caption(
            f"Broker: `{mqtt_info.get('brokerHost')}:{mqtt_info.get('brokerPort')}` | "
            f"Chế độ: `{mqtt_info.get('brokerMode')}`"
        )
        st.markdown("**Lệnh Backend $\\rightarrow$ ESP32 (`iot_smartlocker_2026/command`):**")
        st.json(mqtt_info.get("recentPublished", [])[-5:])
        st.markdown("**Trạng thái ESP32 $\\rightarrow$ Backend (`iot_smartlocker_2026/status`):**")
        st.json(mqtt_info.get("recentReceived", [])[-5:])

    with m_col2:
        st.markdown("#### 🖥️ ESP32 Serial Monitor (115200 baud)")
        serial_text = "\n".join(esp.get("serialLog", []))
        st.code(serial_text, language="text")

    with st.expander("📄 Xem mã nguồn Firmware ESP32 (`iot_esp32/wokwi/sketch.ino`) & Sơ đồ Wokwi (`diagram.json`)"):
        sketch_path = BASE_DIR / "iot_esp32" / "wokwi" / "sketch.ino"
        diag_path = BASE_DIR / "iot_esp32" / "wokwi" / "diagram.json"
        sc1, sc2 = st.columns(2)
        if sketch_path.exists():
            sc1.markdown("**`iot_esp32/wokwi/sketch.ino`**")
            sc1.code(sketch_path.read_text(encoding="utf-8"), language="cpp")
        if diag_path.exists():
            sc2.markdown("**`iot_esp32/wokwi/diagram.json`**")
            sc2.code(diag_path.read_text(encoding="utf-8"), language="json")


# ============================================================================
# MAIN STREAMLIT ENTRYPOINT
# ============================================================================
def main():
    st.set_page_config(
        page_title="IoT Smart Locker - AI Face Recognition",
        page_icon="🔐",
        layout="wide",
    )
    inject_custom_css()

    with st.sidebar:
        st.markdown("## 🔐 IoT Smart Locker")
        st.caption("Hệ thống Tủ đồ Thông minh tích hợp Nhận diện Khuôn mặt AI & ESP32 MQTT")
        st.divider()

        default_mode = os.getenv("SMART_LOCKER_UI_MODE", "ALL")
        nav_options = [
            "🖥️ 1. Kiosk Khách Hàng (Gửi/Nhận đồ)",
            "🛡️ 2. Dashboard Quản Trị (Staff/Admin)",
            "🔌 3. Mô phỏng Phần cứng ESP32 (Wokwi/MQTT)",
        ]
        default_idx = 0
        if default_mode == "DASHBOARD":
            default_idx = 1
        elif default_mode == "ESP32":
            default_idx = 2

        selected_nav = st.radio(
            "Chọn Phân hệ Giao diện:",
            options=nav_options,
            index=default_idx,
        )

        st.divider()
        c_ref, c_rst = st.columns(2)
        if c_ref.button("🔄 Làm mới", use_container_width=True):
            st.rerun()
        if c_rst.button("♻️ Reset Demo", use_container_width=True):
            api_request("POST", "/api/system/reset-demo")
            st.session_state.pop("last_kiosk_result", None)
            st.toast("Đã đặt lại dữ liệu Demo về trạng thái ban đầu!", icon="✅")
            st.rerun()

        st.markdown("---")
        st.markdown(
            """
            **Thông số Kỹ thuật MVP:**
            - **AI:** YOLOv5-Face + 128D Vector
            - **Ngưỡng Euclidean:** $\\le 0.45$
            - **Relay Auto-lock:** $5\\text{ s}$ (`millis()`)
            - **Door Timeout:** $30\\text{ s}$ (`Buzzer`)
            - **MQTT Topics:**
              - `iot_smartlocker_2026/command`
              - `iot_smartlocker_2026/status`
            """
        )

    if selected_nav.startswith("🖥️"):
        render_kiosk_view()
    elif selected_nav.startswith("🛡️"):
        render_dashboard_view()
    else:
        render_esp32_wokwi_view()


if __name__ == "__main__":
    main()

