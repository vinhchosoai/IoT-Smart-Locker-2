-- ============================================================================
-- HỆ THỐNG TỦ ĐỒ THÔNG MINH TÍCH HỢP NHẬN DIỆN KHUÔN MẶT (IoT SMART LOCKER)
-- Physical MySQL 8.0 Schema (Standardized from Chapter 4 Class Diagram & Chapter 5 ERD)
-- ============================================================================

CREATE DATABASE IF NOT EXISTS iot_smart_locker
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE iot_smart_locker;

-- ----------------------------------------------------------------------------
-- 1. Table: users (Entity: User)
-- Stores Admin and Staff accounts for Dashboard authentication & RBAC (FR-04)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    userID INT AUTO_INCREMENT PRIMARY KEY,
    userUUID CHAR(36) NOT NULL UNIQUE COMMENT 'UUID representation from ERD',
    username VARCHAR(50) NOT NULL UNIQUE,
    passwordHash VARCHAR(255) NOT NULL COMMENT 'passwordHashed in ERD / passwordHash in Class Diagram',
    fullName VARCHAR(100) NOT NULL,
    role ENUM('ADMIN', 'STAFF') NOT NULL DEFAULT 'STAFF',
    createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_users_username (username),
    INDEX idx_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 2. Table: lockers (Entity: Locker)
-- Stores physical locker compartments, occupancy status, and IoT door state (FR-03, FR-06, FR-07)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lockers (
    LockerID INT AUTO_INCREMENT PRIMARY KEY,
    lockerUUID CHAR(36) NOT NULL UNIQUE COMMENT 'UUID representation from ERD',
    LockerNumber INT NOT NULL UNIQUE,
    status ENUM('AVAILABLE', 'OCCUPIED', 'MAINTENANCE') NOT NULL DEFAULT 'AVAILABLE',
    doorState ENUM('OPEN', 'CLOSED') NOT NULL DEFAULT 'CLOSED',
    lockState ENUM('LOCKED', 'UNLOCKED') NOT NULL DEFAULT 'LOCKED',
    alertState ENUM('NONE', 'DOOR_OPEN_TIMEOUT') NOT NULL DEFAULT 'NONE',
    updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_lockers_status (status),
    INDEX idx_lockers_number (LockerNumber)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 3. Table: storage_sessions (Entity: Session / StorageSession)
-- Stores customer storage sessions and 128D face embeddings (FR-01, FR-02)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS storage_sessions (
    sessionID INT AUTO_INCREMENT PRIMARY KEY,
    sessionUUID CHAR(36) NOT NULL UNIQUE COMMENT 'UUID representation from ERD',
    LockerID INT NOT NULL,
    faceImageURL VARCHAR(255) NOT NULL,
    faceEmbedding JSON NOT NULL COMMENT '128D normalized float vector <<VECTOR 128D>>',
    backupPin VARCHAR(20) NULL COMMENT 'Emergency/backup PIN from Class Diagram',
    customerLabel VARCHAR(100) NULL COMMENT 'Optional label for simulation/testing traceability',
    checkInAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checkOutAt DATETIME NULL,
    status ENUM('ACTIVE', 'COMPLETED', 'FORCE_OPENED') NOT NULL DEFAULT 'ACTIVE',
    CONSTRAINT fk_session_locker
        FOREIGN KEY (LockerID) REFERENCES lockers (LockerID)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    INDEX idx_sessions_status (status),
    INDEX idx_sessions_locker (LockerID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 4. Table: action_logs (Entity: ActionLog)
-- Audit trail for all Kiosk, Staff/Admin, and IoT Alert events (FR-05, FR-07, FR-08)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS action_logs (
    logID INT AUTO_INCREMENT PRIMARY KEY,
    actionLogUUID CHAR(36) NOT NULL UNIQUE COMMENT 'actionLogID UUID from ERD',
    LockerID INT NULL,
    userID INT NULL,
    sessionID INT NULL,
    actionType ENUM(
        'CLIENT_STORE',
        'CLIENT_RETRIEVE',
        'TEMP_OPEN',
        'STAFF_FORCE_OPEN',
        'DOOR_ALERT',
        'CALL_STAFF',
        'LOCKER_STATUS_UPDATE',
        'STAFF_MANAGEMENT'
    ) NOT NULL COMMENT 'Maps to status ENUM in ERD and actionType in Class Diagram',
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note VARCHAR(500) NULL,
    CONSTRAINT fk_log_locker
        FOREIGN KEY (LockerID) REFERENCES lockers (LockerID)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_log_user
        FOREIGN KEY (userID) REFERENCES users (userID)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_log_session
        FOREIGN KEY (sessionID) REFERENCES storage_sessions (sessionID)
        ON DELETE SET NULL ON UPDATE CASCADE,
    INDEX idx_logs_action (actionType),
    INDEX idx_logs_timestamp (timestamp),
    INDEX idx_logs_locker (LockerID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 5. Default Seed Data (for Simulation & Testing)
-- Passwords below are bcrypt hashes for 'admin123' and 'staff123'
-- ----------------------------------------------------------------------------
INSERT IGNORE INTO lockers (LockerID, lockerUUID, LockerNumber, status, doorState, lockState, alertState) VALUES
(1, '11111111-0001-4000-8000-000000000001', 1, 'AVAILABLE', 'CLOSED', 'LOCKED', 'NONE'),
(2, '11111111-0002-4000-8000-000000000002', 2, 'AVAILABLE', 'CLOSED', 'LOCKED', 'NONE'),
(3, '11111111-0003-4000-8000-000000000003', 3, 'AVAILABLE', 'CLOSED', 'LOCKED', 'NONE'),
(4, '11111111-0004-4000-8000-000000000004', 4, 'AVAILABLE', 'CLOSED', 'LOCKED', 'NONE'),
(5, '11111111-0005-4000-8000-000000000005', 5, 'AVAILABLE', 'CLOSED', 'LOCKED', 'NONE'),
(6, '11111111-0006-4000-8000-000000000006', 6, 'MAINTENANCE', 'CLOSED', 'LOCKED', 'NONE');

