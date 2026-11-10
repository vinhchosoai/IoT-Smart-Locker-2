import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from backend.config import (
    DOOR_OPEN_TIMEOUT_SECONDS,
    MQTT_STATUS_TOPIC,
    RELAY_AUTO_LOCK_SECONDS,
)


class VirtualLockerPinState:
    def __init__(self, locker_id: int, relay_gpio: int, sensor_gpio: int):
        self.locker_id = locker_id
        self.relay_gpio = relay_gpio
        self.sensor_gpio = sensor_gpio
        self.relay_high: bool = False  # True = HIGH (UNLOCKED), False = LOW (LOCKED)
        self.relay_activated_at_ms: int = 0
        self.door_open: bool = False  # Slide switch state: False = CLOSED, True = OPEN
        self.door_opened_at_ms: int = 0
        self.timeout_alert_active: bool = False

    def to_dict(self, current_ms: int) -> Dict[str, Any]:
        relay_remaining_ms = 0
        if self.relay_high:
            elapsed = current_ms - self.relay_activated_at_ms
            relay_remaining_ms = max(0, RELAY_AUTO_LOCK_SECONDS * 1000 - elapsed)

        door_open_elapsed_ms = 0
        if self.door_open:
            door_open_elapsed_ms = max(0, current_ms - self.door_opened_at_ms)

        return {
            "locker_id": self.locker_id,
            "relay_gpio": self.relay_gpio,
            "sensor_gpio": self.sensor_gpio,
            "relay_pin_level": "HIGH" if self.relay_high else "LOW",
            "lock_state": "UNLOCKED" if self.relay_high else "LOCKED",
            "relay_remaining_sec": round(relay_remaining_ms / 1000.0, 1),
            "door": "OPEN" if self.door_open else "CLOSED",
            "door_open_elapsed_sec": round(door_open_elapsed_ms / 1000.0, 1),
            "alert": "DOOR_OPEN_TIMEOUT" if self.timeout_alert_active else "NONE",
        }


class VirtualESP32Twin:
    """
    Virtual ESP32 Hardware Twin (Chapter 6: Wokwi Hybrid Simulation).
    Mirrors the exact non-blocking millis() state machine of iot_esp32/wokwi/sketch.ino:
      - LCD 1602 I2C (SDA: GPIO 21, SCL: GPIO 22)
      - Buzzer (GPIO 15)
      - Relay 1 (GPIO 26) & Door Sensor 1 (GPIO 32)
      - Relay 2 (GPIO 27) & Door Sensor 2 (GPIO 33)
      - Additional virtual relays/sensors for Lockers 3..6
      - Relay auto-locks (HIGH -> LOW) after 5,000 ms (TC-06)
      - Door open > 30,000 ms activates Buzzer + publishes DOOR_OPEN_TIMEOUT (TC-07)
    """

    def __init__(
        self,
        publish_status_fn: Optional[Callable[[str, str], Any]] = None,
        relay_duration_ms: int = RELAY_AUTO_LOCK_SECONDS * 1000,
        door_timeout_ms: int = DOOR_OPEN_TIMEOUT_SECONDS * 1000,
    ):
        self._publish_status_fn = publish_status_fn
        self.relay_duration_ms = int(relay_duration_ms)
        self.door_timeout_ms = int(door_timeout_ms)

        self._boot_monotonic = time.monotonic()
        self._virtual_offset_ms: int = 0
        self._lock = threading.Lock()

        # Hardware mapping per Table 6.1 (plus virtual expansion for lockers 3..6)
        self.lcd_sda_gpio = 21
        self.lcd_scl_gpio = 22
        self.buzzer_gpio = 15
        self.buzzer_active: bool = False
        self.lcd_line1: str = "SMART LOCKER RDY"
        self.lcd_line2: str = "L1:CLSD  L2:CLSD"

        self.lockers: Dict[int, VirtualLockerPinState] = {
            1: VirtualLockerPinState(1, relay_gpio=26, sensor_gpio=32),
            2: VirtualLockerPinState(2, relay_gpio=27, sensor_gpio=33),
            3: VirtualLockerPinState(3, relay_gpio=25, sensor_gpio=34),
            4: VirtualLockerPinState(4, relay_gpio=14, sensor_gpio=35),
            5: VirtualLockerPinState(5, relay_gpio=12, sensor_gpio=36),
            6: VirtualLockerPinState(6, relay_gpio=13, sensor_gpio=39),
        }

        self.serial_log: List[str] = [
            "[BOOT] ESP32 Wokwi Twin initialized (SDA=21, SCL=22, BUZZER=15)",
            "[MQTT] Subscribed to iot_smartlocker_2026/command",
        ]
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def millis(self) -> int:
        real_ms = int((time.monotonic() - self._boot_monotonic) * 1000)
        return real_ms + self._virtual_offset_ms

    def advance_millis(self, delta_ms: int) -> None:
        """
        Advances virtual millis() clock for deterministic testing of
        5s relay auto-lock (TC-06) and 30s door open timeout (TC-07).
        """
        with self._lock:
            self._virtual_offset_ms += int(delta_ms)
        self.tick()

    def _log_serial(self, msg: str) -> None:
        ts_sec = self.millis() / 1000.0
        entry = f"[{ts_sec:8.2f}s] {msg}"
        self.serial_log.append(entry)
        if len(self.serial_log) > 150:
            self.serial_log = self.serial_log[-150:]

    def _update_lcd(self, line1: str, line2: str) -> None:
        self.lcd_line1 = (line1 or "")[:16].ljust(16)
        self.lcd_line2 = (line2 or "")[:16].ljust(16)

    def _emit_status(self, lk: VirtualLockerPinState) -> None:
        payload = {
            "locker_id": lk.locker_id,
            "door": "OPEN" if lk.door_open else "CLOSED",
            "lock_state": "UNLOCKED" if lk.relay_high else "LOCKED",
            "alert": "DOOR_OPEN_TIMEOUT" if lk.timeout_alert_active else "NONE",
        }
        payload_str = json.dumps(payload)
        self._log_serial(f"[MQTT PUB -> {MQTT_STATUS_TOPIC}] {payload_str}")
        if self._publish_status_fn is not None:
            self._publish_status_fn(MQTT_STATUS_TOPIC, payload_str)

    def on_command_received(self, cmd_payload: Dict[str, Any]) -> None:
        """Handles incoming command from Backend on iot_smartlocker_2026/command."""
        locker_id = int(cmd_payload.get("locker_id", 0))
        action = str(cmd_payload.get("action", "")).upper()
        user_type = str(cmd_payload.get("user_type", "CUSTOMER")).upper()

        with self._lock:
            if locker_id not in self.lockers:
                self.lockers[locker_id] = VirtualLockerPinState(
                    locker_id, relay_gpio=26, sensor_gpio=32
                )
            lk = self.lockers[locker_id]
            now_ms = self.millis()

            if action == "OPEN":
                lk.relay_high = True
                lk.relay_activated_at_ms = now_ms
                self._update_lcd(f"UNLOCK LOCKER #{locker_id}", f"BY: {user_type}")
                self._log_serial(
                    f"[GPIO {lk.relay_gpio} HIGH] Relay #{locker_id} UNLOCKED by {user_type} (5s timer started)"
                )
                self._emit_status(lk)

    def set_door_switch(self, locker_id: int, is_open: bool) -> Dict[str, Any]:
        """Simulates toggling the physical Slide Switch on GPIO 32 / GPIO 33."""
        with self._lock:
            if locker_id not in self.lockers:
                self.lockers[locker_id] = VirtualLockerPinState(
                    locker_id, relay_gpio=26, sensor_gpio=32
                )
            lk = self.lockers[locker_id]
            now_ms = self.millis()
            lk.door_open = bool(is_open)
            if lk.door_open:
                lk.door_opened_at_ms = now_ms
                lk.timeout_alert_active = False
                self._log_serial(
                    f"[GPIO {lk.sensor_gpio} HIGH] Door #{locker_id} Slide Switch -> OPEN"
                )
            else:
                lk.timeout_alert_active = False
                self._log_serial(
                    f"[GPIO {lk.sensor_gpio} LOW] Door #{locker_id} Slide Switch -> CLOSED"
                )

            l1_door = "OPEN" if self.lockers[1].door_open else "CLSD"
            l2_door = "OPEN" if self.lockers[2].door_open else "CLSD"
            self._update_lcd("DOOR STATE CHG", f"L1:{l1_door} L2:{l2_door}")
            self._emit_status(lk)
            self._refresh_buzzer_locked()
            return lk.to_dict(now_ms)

    def _refresh_buzzer_locked(self) -> None:
        self.buzzer_active = any(
            lk.door_open and lk.timeout_alert_active for lk in self.lockers.values()
        )

    def tick(self) -> None:
        """Single iteration of ESP32 loop() checking millis() timers."""
        with self._lock:
            now_ms = self.millis()
            for lk in self.lockers.values():
                # 1. Check 5-second relay auto-shutoff (Section 6.2, TC-06)
                if (
                    lk.relay_high
                    and (now_ms - lk.relay_activated_at_ms) >= self.relay_duration_ms
                ):
                    lk.relay_high = False
                    self._log_serial(
                        f"[GPIO {lk.relay_gpio} LOW] Relay #{lk.locker_id} auto-locked after 5s (millis() timer)"
                    )
                    l1_door = "OPEN" if self.lockers[1].door_open else "CLSD"
                    l2_door = "OPEN" if self.lockers[2].door_open else "CLSD"
                    if not any(x.timeout_alert_active for x in self.lockers.values()):
                        self._update_lcd("SMART LOCKER RDY", f"L1:{l1_door}  L2:{l2_door}")
                    self._emit_status(lk)

                # 2. Check 30-second door open timeout alarm (Section 6.3, TC-07)
                if lk.door_open and not lk.timeout_alert_active:
                    if (now_ms - lk.door_opened_at_ms) >= self.door_timeout_ms:
                        lk.timeout_alert_active = True
                        self._update_lcd(
                            f"ALERT LOCKER #{lk.locker_id}!", "DOOR OPEN > 30S!"
                        )
                        self._log_serial(
                            f"[GPIO {self.buzzer_gpio} HIGH] ALARM! Door #{lk.locker_id} open > 30s -> DOOR_OPEN_TIMEOUT"
                        )
                        self._emit_status(lk)

            self._refresh_buzzer_locked()

    def start_background_loop(self, interval_sec: float = 0.25) -> None:
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                try:
                    self.tick()
                except Exception:
                    pass
                time.sleep(interval_sec)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop_background_loop(self) -> None:
        self._running = False

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            now_ms = self.millis()
            return {
                "millis": now_ms,
                "lcd": {
                    "sdaGpio": self.lcd_sda_gpio,
                    "sclGpio": self.lcd_scl_gpio,
                    "line1": self.lcd_line1,
                    "line2": self.lcd_line2,
                },
                "buzzer": {
                    "gpio": self.buzzer_gpio,
                    "active": self.buzzer_active,
                    "level": "HIGH (BEEPING)" if self.buzzer_active else "LOW (SILENT)",
                },
                "lockers": {
                    k: v.to_dict(now_ms) for k, v in sorted(self.lockers.items())
                },
                "serialLog": list(self.serial_log[-30:]),
            }

