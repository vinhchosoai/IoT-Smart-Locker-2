/*
 * ============================================================================
 * DỰ ÁN: HỆ THỐNG TỦ ĐỒ THÔNG MINH TÍCH HỢP NHẬN DIỆN KHUÔN MẶT (IoT SMART LOCKER)
 * Thiết bị: ESP32 Controller (Mô phỏng trên Wokwi - Chương 6 Báo cáo)
 * ============================================================================
 * Sơ đồ chân (Mục 6.1):
 *   - LCD 1602 I2C : SDA = GPIO 21, SCL = GPIO 22
 *   - Buzzer       : GPIO 15
 *   - Relay Tủ 1   : GPIO 26 (HIGH = Mở khóa, tự ngắt về LOW sau 5 giây bằng millis())
 *   - Cửa Tủ 1     : GPIO 32 (INPUT_PULLUP: LOW = CLOSED, HIGH = OPEN)
 *   - Relay Tủ 2   : GPIO 27 (HIGH = Mở khóa, tự ngắt về LOW sau 5 giây bằng millis())
 *   - Cửa Tủ 2     : GPIO 33 (INPUT_PULLUP: LOW = CLOSED, HIGH = OPEN)
 *
 * Giao thức MQTT (Mục 3.4 & 6.4):
 *   - Broker       : broker.hivemq.com:1883
 *   - Sub Topic    : iot_smartlocker_2026/command
 *   - Pub Topic    : iot_smartlocker_2026/status
 * ============================================================================
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ArduinoJson.h>

// --- Cấu hình Wi-Fi & MQTT Broker (Mục 3.3 & 3.4) ---
const char* WIFI_SSID     = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";
const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;

const char* TOPIC_COMMAND = "iot_smartlocker_2026/command";
const char* TOPIC_STATUS  = "iot_smartlocker_2026/status";

// --- Định nghĩa chân GPIO (Mục 6.1) ---
#define PIN_I2C_SDA       21
#define PIN_I2C_SCL       22
#define PIN_BUZZER        15
#define PIN_RELAY_1       26
#define PIN_RELAY_2       27
#define PIN_DOOR_SENSOR_1 32
#define PIN_DOOR_SENSOR_2 33

// --- Hằng số thời gian không chặn millis() (Mục 2.5, 6.2, 6.3) ---
const unsigned long RELAY_UNLOCK_DURATION_MS = 5000UL;   // Tự ngắt relay sau 5 giây (TC-06)
const unsigned long DOOR_OPEN_TIMEOUT_MS     = 30000UL;  // Cảnh báo cửa mở quá 30 giây (TC-07)

LiquidCrystal_I2C lcd(0x27, 16, 2);
WiFiClient espClient;
PubSubClient mqttClient(espClient);

struct LockerHardware {
  int lockerId;
  int relayPin;
  int sensorPin;
  bool relayActive;
  unsigned long relayActivatedAt;
  bool doorOpen;
  unsigned long doorOpenedAt;
  bool timeoutAlertActive;
};

LockerHardware lockers[2] = {
  {1, PIN_RELAY_1, PIN_DOOR_SENSOR_1, false, 0, false, 0, false},
  {2, PIN_RELAY_2, PIN_DOOR_SENSOR_2, false, 0, false, 0, false}
};

void updateLcd(const char* line1, const char* line2) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);
}

void beepShort() {
  digitalWrite(PIN_BUZZER, HIGH);
  delay(120);
  digitalWrite(PIN_BUZZER, LOW);
}

void publishLockerStatus(int idx, const char* alertStr) {
  StaticJsonDocument<256> doc;
  doc["locker_id"]  = lockers[idx].lockerId;
  doc["door"]       = lockers[idx].doorOpen ? "OPEN" : "CLOSED";
  doc["lock_state"] = lockers[idx].relayActive ? "UNLOCKED" : "LOCKED";
  doc["alert"]      = alertStr;

  char buffer[256];
  serializeJson(doc, buffer);
  mqttClient.publish(TOPIC_STATUS, buffer);

  Serial.print("[MQTT PUB] ");
  Serial.println(buffer);
}

void activateRelayUnlock(int idx, const char* userType) {
  lockers[idx].relayActive = true;
  lockers[idx].relayActivatedAt = millis();
  digitalWrite(lockers[idx].relayPin, HIGH);
  beepShort();

  char l1[17], l2[17];
  snprintf(l1, sizeof(l1), "UNLOCK LOCKER #%d", lockers[idx].lockerId);
  snprintf(l2, sizeof(l2), "BY: %-12s", userType);
  updateLcd(l1, l2);

  publishLockerStatus(idx, lockers[idx].timeoutAlertActive ? "DOOR_OPEN_TIMEOUT" : "NONE");
}

void onMqttCallback(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    Serial.print("[MQTT ERR] Invalid JSON: ");
    Serial.println(err.c_str());
    return;
  }

  int lockerId = doc["locker_id"] | 0;
  const char* action = doc["action"] | "";
  const char* userType = doc["user_type"] | "CUSTOMER";

  if (strcmp(action, "OPEN") == 0) {
    for (int i = 0; i < 2; i++) {
      if (lockers[i].lockerId == lockerId) {
        activateRelayUnlock(i, userType);
        break;
      }
    }
  }
}

void connectWiFi() {
  updateLcd("Connecting WiFi", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println("\n[WiFi] Connected!");
  updateLcd("WiFi Connected!", WiFi.localIP().toString().c_str());
}

void reconnectMqtt() {
  while (!mqttClient.connected()) {
    String clientId = "ESP32_SmartLocker_" + String(random(0xffff), HEX);
    if (mqttClient.connect(clientId.c_str())) {
      mqttClient.subscribe(TOPIC_COMMAND);
      updateLcd("SMART LOCKER RDY", "L1:CLSD  L2:CLSD");
      Serial.println("[MQTT] Subscribed to command topic");
    } else {
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  lcd.init();
  lcd.backlight();

  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);

  for (int i = 0; i < 2; i++) {
    pinMode(lockers[i].relayPin, OUTPUT);
    digitalWrite(lockers[i].relayPin, LOW);
    pinMode(lockers[i].sensorPin, INPUT_PULLUP);
    lockers[i].doorOpen = (digitalRead(lockers[i].sensorPin) == HIGH);
    if (lockers[i].doorOpen) {
      lockers[i].doorOpenedAt = millis();
    }
  }

  connectWiFi();
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMqttCallback);
}

void loop() {
  if (!mqttClient.connected()) {
    reconnectMqtt();
  }
  mqttClient.loop();

  unsigned long now = millis();
  bool anyTimeoutAlarm = false;

  for (int i = 0; i < 2; i++) {
    // 1. Kiểm tra tự ngắt Relay sau 5 giây (Mục 6.2 - TC-06)
    if (lockers[i].relayActive && (now - lockers[i].relayActivatedAt >= RELAY_UNLOCK_DURATION_MS)) {
      lockers[i].relayActive = false;
      digitalWrite(lockers[i].relayPin, LOW);
      Serial.printf("[RELAY] Locker #%d auto-locked after 5s\n", lockers[i].lockerId);
      publishLockerStatus(i, lockers[i].timeoutAlertActive ? "DOOR_OPEN_TIMEOUT" : "NONE");
    }

    // 2. Đọc cảm biến cửa từ Slide Switch (Mục 6.3)
    bool currentDoorOpen = (digitalRead(lockers[i].sensorPin) == HIGH);
    if (currentDoorOpen != lockers[i].doorOpen) {
      lockers[i].doorOpen = currentDoorOpen;
      if (currentDoorOpen) {
        lockers[i].doorOpenedAt = now;
        lockers[i].timeoutAlertActive = false;
        publishLockerStatus(i, "NONE");
      } else {
        lockers[i].timeoutAlertActive = false;
        publishLockerStatus(i, "NONE");
      }
      char l1[17], l2[17];
      snprintf(l1, sizeof(l1), "DOOR STATE CHG");
      snprintf(l2, sizeof(l2), "L1:%s L2:%s",
               lockers[0].doorOpen ? "OPEN" : "CLSD",
               lockers[1].doorOpen ? "OPEN" : "CLSD");
      updateLcd(l1, l2);
    }

    // 3. Cảnh báo cửa mở quá 30 giây (Mục 6.3 - TC-07)
    if (lockers[i].doorOpen) {
      if (!lockers[i].timeoutAlertActive && (now - lockers[i].doorOpenedAt >= DOOR_OPEN_TIMEOUT_MS)) {
        lockers[i].timeoutAlertActive = true;
        publishLockerStatus(i, "DOOR_OPEN_TIMEOUT");
        char l1[17];
        snprintf(l1, sizeof(l1), "ALERT LOCKER #%d!", lockers[i].lockerId);
        updateLcd(l1, "DOOR OPEN > 30S!");
      }
      if (lockers[i].timeoutAlertActive) {
        anyTimeoutAlarm = true;
      }
    }
  }

  // Điều khiển Buzzer khi có cảnh báo cửa mở quá 30 giây
  if (anyTimeoutAlarm) {
    digitalWrite(PIN_BUZZER, ((now / 300) % 2 == 0) ? HIGH : LOW);
  } else {
    digitalWrite(PIN_BUZZER, LOW);
  }

  delay(20);
}

