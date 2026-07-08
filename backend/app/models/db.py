"""数据库初始化与会话管理。"""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from dotenv import load_dotenv
from .entities import Base

env_path = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(env_path)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "study_room")

DATABASE_URI = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

engine = create_engine(DATABASE_URI, pool_pre_ping=True, echo=True)
SessionLocal = scoped_session(sessionmaker(bind=engine))


def init_db():
    """初始化数据库（表已通过init.sql创建，此处仅验证连接）。"""
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        print("数据库连接成功")
    except Exception as e:
        print(f"数据库连接失败: {e}")
        raise


def get_db():
    """获取数据库会话（依赖注入用）。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()