"""数据库会话管理（SQLAlchemy）。"""
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, scoped_session

from ..config import Config

_engine = create_engine(
    Config.DATABASE_URI,
    echo=False,
    pool_pre_ping=True,
)
SessionLocal = scoped_session(sessionmaker(bind=_engine))


def init_db():
    """Validate the connection; SQLite development databases create all tables."""
    try:
        if Config.DATABASE_URI.startswith("sqlite"):
            from .entities import Base

            Base.metadata.create_all(_engine)
        _ensure_seat_status_session_columns()
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("数据库连接成功")
    except Exception as e:
        print(f"数据库连接失败: {e}")
        raise


def _ensure_seat_status_session_columns() -> None:
    """Additive compatibility migration for existing demonstration databases."""
    inspector = inspect(_engine)
    if "seat_status" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("seat_status")}
    statements = []
    if "mode" not in columns:
        statements.append("ALTER TABLE seat_status ADD COLUMN mode VARCHAR(16) DEFAULT 'demo'")
    if "member_id" not in columns:
        statements.append("ALTER TABLE seat_status ADD COLUMN member_id INTEGER NULL")
    if not statements:
        return
    with _engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
        conn.execute(text("UPDATE seat_status SET mode = 'demo' WHERE mode IS NULL OR mode = ''"))


def get_db():
    """获取数据库会话（依赖注入用）。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
