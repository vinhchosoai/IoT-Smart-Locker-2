import logging
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.config import MYSQL_URL, SQLITE_FALLBACK_URL
from backend.models import ActionLog, Base, Locker, User, hash_password

logger = logging.getLogger("smart_locker.db")

ACTIVE_DB_URL = MYSQL_URL
ACTIVE_DB_ENGINE_TYPE = "MySQL 8.0"


def _create_resilient_engine():
    global ACTIVE_DB_URL, ACTIVE_DB_ENGINE_TYPE
    if os.getenv("FORCE_SQLITE") == "1":
        ACTIVE_DB_URL = SQLITE_FALLBACK_URL
        ACTIVE_DB_ENGINE_TYPE = "SQLite (Test Mode)"
        return create_engine(
            SQLITE_FALLBACK_URL,
            connect_args={"check_same_thread": False},
        )

    try:
        # First ensure database exists if connecting to local MySQL
        if MYSQL_URL.startswith("mysql+pymysql://"):
            base_url, db_part = MYSQL_URL.rsplit("/", 1)
            db_name = db_part.split("?")[0]
            root_engine = create_engine(base_url, pool_pre_ping=True)
            with root_engine.connect() as conn:
                conn.execute(
                    text(
                        f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
                    )
                )
                conn.commit()
            root_engine.dispose()

        engine = create_engine(
            MYSQL_URL,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        ACTIVE_DB_URL = MYSQL_URL
        ACTIVE_DB_ENGINE_TYPE = "MySQL 8.0"
        logger.info("Connected to MySQL database: %s", MYSQL_URL)
        return engine
    except Exception as exc:
        logger.warning(
            "MySQL connection unavailable (%s). Falling back to local SQLite: %s",
            exc,
            SQLITE_FALLBACK_URL,
        )
        ACTIVE_DB_URL = SQLITE_FALLBACK_URL
        ACTIVE_DB_ENGINE_TYPE = "SQLite (Fallback)"
        return create_engine(
            SQLITE_FALLBACK_URL,
            connect_args={"check_same_thread": False},
        )


engine = _create_resilient_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session_scope() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables and seed initial Admin, Staff, and Lockers."""
    Base.metadata.create_all(bind=engine)
    with db_session_scope() as db:
        # Seed default Admin & Staff accounts (FR-04)
        if db.query(User).count() == 0:
            default_users = [
                User(
                    userUUID="00000000-0000-4000-a000-000000000001",
                    username="admin",
                    passwordHash=hash_password("admin123"),
                    fullName="Nguyễn Quản Trị (System Admin)",
                    role="ADMIN",
                ),
                User(
                    userUUID="00000000-0000-4000-a000-000000000002",
                    username="staff01",
                    passwordHash=hash_password("staff123"),
                    fullName="Trần Nhân Viên Ca Sáng",
                    role="STAFF",
                ),
                User(
                    userUUID="00000000-0000-4000-a000-000000000003",
                    username="staff02",
                    passwordHash=hash_password("staff123"),
                    fullName="Lê Nhân Viên Ca Chiều",
                    role="STAFF",
                ),
            ]
            db.add_all(default_users)
            db.flush()

        # Seed default Lockers (FR-03, Chapter 6)
        if db.query(Locker).count() == 0:
            default_lockers = [
                Locker(
                    LockerID=1,
                    lockerUUID="11111111-0001-4000-8000-000000000001",
                    LockerNumber=1,
                    status="AVAILABLE",
                    doorState="CLOSED",
                    lockState="LOCKED",
                    alertState="NONE",
                ),
                Locker(
                    LockerID=2,
                    lockerUUID="11111111-0002-4000-8000-000000000002",
                    LockerNumber=2,
                    status="AVAILABLE",
                    doorState="CLOSED",
                    lockState="LOCKED",
                    alertState="NONE",
                ),
                Locker(
                    LockerID=3,
                    lockerUUID="11111111-0003-4000-8000-000000000003",
                    LockerNumber=3,
                    status="AVAILABLE",
                    doorState="CLOSED",
                    lockState="LOCKED",
                    alertState="NONE",
                ),
                Locker(
                    LockerID=4,
                    lockerUUID="11111111-0004-4000-8000-000000000004",
                    LockerNumber=4,
                    status="AVAILABLE",
                    doorState="CLOSED",
                    lockState="LOCKED",
                    alertState="NONE",
                ),
                Locker(
                    LockerID=5,
                    lockerUUID="11111111-0005-4000-8000-000000000005",
                    LockerNumber=5,
                    status="AVAILABLE",
                    doorState="CLOSED",
                    lockState="LOCKED",
                    alertState="NONE",
                ),
                Locker(
                    LockerID=6,
                    lockerUUID="11111111-0006-4000-8000-000000000006",
                    LockerNumber=6,
                    status="MAINTENANCE",
                    doorState="CLOSED",
                    lockState="LOCKED",
                    alertState="NONE",
                ),
            ]
            db.add_all(default_lockers)
            db.flush()
        else:
            # Ensure users exist even if lockers were pre-seeded by SQL script
            admin_exists = db.query(User).filter(User.username == "admin").first()
            if not admin_exists:
                db.add_all(
                    [
                        User(
                            userUUID="00000000-0000-4000-a000-000000000001",
                            username="admin",
                            passwordHash=hash_password("admin123"),
                            fullName="Nguyễn Quản Trị (System Admin)",
                            role="ADMIN",
                        ),
                        User(
                            userUUID="00000000-0000-4000-a000-000000000002",
                            username="staff01",
                            passwordHash=hash_password("staff123"),
                            fullName="Trần Nhân Viên Ca Sáng",
                            role="STAFF",
                        ),
                        User(
                            userUUID="00000000-0000-4000-a000-000000000003",
                            username="staff02",
                            passwordHash=hash_password("staff123"),
                            fullName="Lê Nhân Viên Ca Chiều",
                            role="STAFF",
                        ),
                    ]
                )

