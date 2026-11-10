import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import paho.mqtt.client as mqtt

from backend.config import (
    DOOR_OPEN_TIMEOUT_SECONDS,
    MQTT_BROKER_HOST,
    MQTT_BROKER_PORT,
    MQTT_COMMAND_TOPIC,
    MQTT_STATUS_TOPIC,
    RELAY_AUTO_LOCK_SECONDS,
)

logger = logging.getLogger("smart_locker.mqtt")


class MQTTService:
    """
    MQTT Communication Service (Chapter 3.4, Chapter 4.3 Class Diagram & Chapter 6.4).

    Attributes (per Class Diagram):
        - brokerHost: string (default 'broker.hivemq.com')
        - brokerPort: integer (default 1883)
        - commandTopic: string (default 'iot_smartlocker_2026/command')
        - statusTopic: string (default 'iot_smartlocker_2026/status')

    Methods (per Class Diagram):
        - connect(): void
        - publishOpenCommand(LockerID: integer, action: string): boolean
        - subscribeStatusTopic(): void
        - onMessageReceived(topic: string, payload: string): void
    """

    def __init__(
        self,
        broker_host: str = MQTT_BROKER_HOST,
        broker_port: int = MQTT_BROKER_PORT,
        command_topic: str = MQTT_COMMAND_TOPIC,
        status_topic: str = MQTT_STATUS_TOPIC,
        status_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.brokerHost: str = broker_host
        self.brokerPort: int = int(broker_port)
        self.commandTopic: str = command_topic
        self.statusTopic: str = status_topic

        self._status_callback = status_callback
        self._client: Optional[mqtt.Client] = None
        self.is_connected: bool = False
        self.broker_mode: str = "DISCONNECTED"
        self.simulate_offline: bool = False  # For TC-09 testing

        # History & Telemetry (Section 7.4)
        self.published_messages: List[Dict[str, Any]] = []
        self.received_messages: List[Dict[str, Any]] = []
        self.dispatch_latencies_ms: List[float] = []
        self._pending_cmd_timestamps: Dict[int, float] = {}
        self._lock = threading.Lock()

        # Local Virtual ESP32 hooks (for Hybrid Simulation when Wokwi is local or headless)
        self._virtual_esp32_listeners: List[Callable[[Dict[str, Any]], None]] = []

    def set_status_callback(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._status_callback = callback

    def register_virtual_esp32_listener(
        self, listener: Callable[[Dict[str, Any]], None]
    ) -> None:
        if listener not in self._virtual_esp32_listeners:
            self._virtual_esp32_listeners.append(listener)

    def connect(self, timeout_sec: float = 3.0) -> bool:
        """
        Class Diagram method: + connect(): void/boolean
        Connects to MQTT broker (broker.hivemq.com:1883) and activates local hybrid bridge.
        """
        if self.simulate_offline:
            self.is_connected = False
            self.broker_mode = "OFFLINE_SIMULATED"
            return False

        try:
            client_id = f"smartlocker_backend_{int(time.time() * 1000) % 100000}"
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
            )
            self._client.on_connect = self._on_mqtt_connect
            self._client.on_disconnect = self._on_mqtt_disconnect
            self._client.on_message = self._on_mqtt_message

            self._client.connect_async(self.brokerHost, self.brokerPort, keepalive=60)
            self._client.loop_start()

            deadline = time.time() + timeout_sec
            while time.time() < deadline and not self.is_connected:
                time.sleep(0.05)

            if self.is_connected:
                self.broker_mode = f"MQTT_LIVE ({self.brokerHost}:{self.brokerPort})"
                self.subscribeStatusTopic()
                return True
            else:
                # Hybrid Local Bridge active even if public broker is unreachable/firewalled
                self.is_connected = True
                self.broker_mode = "HYBRID_LOCAL_BROKER"
                logger.info(
                    "Using Hybrid Local MQTT Bridge (public broker %s:%s not reached within %.1fs)",
                    self.brokerHost,
                    self.brokerPort,
                    timeout_sec,
                )
                return True
        except Exception as exc:
            logger.warning("MQTT broker connection fallback to Hybrid Local: %s", exc)
            self.is_connected = True
            self.broker_mode = "HYBRID_LOCAL_BROKER"
            return True

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self.is_connected = False
        self.broker_mode = "DISCONNECTED"

    def set_simulate_offline(self, offline: bool) -> None:
        """Used for TC-09 (Mất kết nối MQTT) verification."""
        self.simulate_offline = bool(offline)
        if self.simulate_offline:
            self.is_connected = False
            self.broker_mode = "OFFLINE_SIMULATED"
        else:
            self.is_connected = True
            if self.broker_mode == "OFFLINE_SIMULATED":
                self.broker_mode = "HYBRID_LOCAL_BROKER"

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self.is_connected = True
            self.broker_mode = f"MQTT_LIVE ({self.brokerHost}:{self.brokerPort})"
            client.subscribe(self.statusTopic, qos=1)
            logger.info("Connected to MQTT Broker and subscribed to %s", self.statusTopic)

    def _on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if self.simulate_offline:
            self.is_connected = False
            self.broker_mode = "OFFLINE_SIMULATED"

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode("utf-8")
            self.onMessageReceived(msg.topic, payload_str)
        except Exception as exc:
            logger.error("Error decoding MQTT message: %s", exc)

    def subscribeStatusTopic(self) -> None:
        """Class Diagram method: + subscribeStatusTopic(): void"""
        if self._client is not None and self.is_connected:
            try:
                self._client.subscribe(self.statusTopic, qos=1)
            except Exception:
                pass

    def publishOpenCommand(
        self,
        LockerID: int,
        action: str = "OPEN",
        user_type: str = "CUSTOMER",
    ) -> bool:
        """
        Class Diagram method: + publishOpenCommand(LockerID: integer, action: string): boolean
        Publishes JSON command per Section 3.4:
        {"locker_id": 1, "action": "OPEN", "user_type": "CUSTOMER", "timestamp": "2026-10-29T09:30:00Z"}
        """
        if self.simulate_offline or not self.is_connected:
            logger.error(
                "MQTT unavailable (simulate_offline=%s, is_connected=%s). Command rejected.",
                self.simulate_offline,
                self.is_connected,
            )
            return False

        t0 = time.perf_counter()
        iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload_dict = {
            "locker_id": int(LockerID),
            "action": str(action).upper(),
            "user_type": str(user_type).upper(),
            "timestamp": iso_ts,
        }
        payload_json = json.dumps(payload_dict)

        with self._lock:
            self._pending_cmd_timestamps[int(LockerID)] = time.perf_counter()
            self.published_messages.append(
                {
                    "topic": self.commandTopic,
                    "payload": payload_dict,
                    "sentAt": iso_ts,
                    "brokerMode": self.broker_mode,
                }
            )
            if len(self.published_messages) > 200:
                self.published_messages = self.published_messages[-200:]

        # 1. Publish to real MQTT broker if connected
        if self._client is not None and "MQTT_LIVE" in self.broker_mode:
            try:
                self._client.publish(self.commandTopic, payload_json, qos=1)
            except Exception as exc:
                logger.warning("Real MQTT publish warning: %s", exc)

        # 2. Deliver to local Virtual ESP32 listeners (Hybrid Simulation)
        for listener in list(self._virtual_esp32_listeners):
            try:
                listener(payload_dict)
            except Exception as exc:
                logger.error("Virtual ESP32 listener error: %s", exc)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.dispatch_latencies_ms.append(round(elapsed_ms, 3))
        return True

    def onMessageReceived(self, topic: str, payload: str) -> Optional[Dict[str, Any]]:
        """
        Class Diagram method: + onMessageReceived(topic: string, payload: string): void
        Validates incoming JSON payload per Section 3.4:
        {"locker_id": 1, "door": "OPEN", "lock_state": "UNLOCKED", "alert": "NONE"}
        """
        try:
            data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        except Exception as exc:
            logger.error("Invalid JSON payload on %s: %s", topic, exc)
            return None

        # Validate required fields per Section 3.4
        if "locker_id" not in data or "door" not in data:
            logger.warning("Malformed status payload missing locker_id or door: %s", data)
            return None

        try:
            locker_id = int(data["locker_id"])
        except (ValueError, TypeError):
            logger.warning("Invalid locker_id type in MQTT status payload: %s", data)
            return None

        door = str(data.get("door", "CLOSED")).upper().strip()
        if door == "CLOSE":
            door = "CLOSED"
        if door not in ("OPEN", "CLOSED"):
            logger.warning("Invalid door state in MQTT payload: %s", door)
            return None

        lock_state = str(data.get("lock_state", "LOCKED")).upper().strip()
        if lock_state not in ("LOCKED", "UNLOCKED"):
            lock_state = "LOCKED"

        alert = str(data.get("alert", "NONE")).upper().strip()
        if alert not in ("NONE", "DOOR_OPEN_TIMEOUT"):
            alert = "NONE"

        validated = {
            "locker_id": locker_id,
            "door": door,
            "lock_state": lock_state,
            "alert": alert,
            "received_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        with self._lock:
            if locker_id in self._pending_cmd_timestamps:
                rtt_ms = (
                    time.perf_counter() - self._pending_cmd_timestamps.pop(locker_id)
                ) * 1000.0
                self.dispatch_latencies_ms.append(round(rtt_ms, 2))

            self.received_messages.append(
                {
                    "topic": topic,
                    "payload": validated,
                }
            )
            if len(self.received_messages) > 200:
                self.received_messages = self.received_messages[-200:]

        if self._status_callback is not None:
            try:
                self._status_callback(validated)
            except Exception as exc:
                logger.error("Error in MQTT status callback: %s", exc)

        return validated

    def get_metrics_summary(self) -> Dict[str, Any]:
        avg_lat = (
            round(sum(self.dispatch_latencies_ms) / len(self.dispatch_latencies_ms), 2)
            if self.dispatch_latencies_ms
            else 0.0
        )
        return {
            "brokerHost": self.brokerHost,
            "brokerPort": self.brokerPort,
            "commandTopic": self.commandTopic,
            "statusTopic": self.statusTopic,
            "isConnected": self.is_connected,
            "brokerMode": self.broker_mode,
            "simulateOffline": self.simulate_offline,
            "publishedCount": len(self.published_messages),
            "receivedCount": len(self.received_messages),
            "avgDispatchLatencyMs": avg_lat,
        }

