"""数据库会话管理（SQLAlchemy）。"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from ..config import Config

_engine = create_engine(
    Config.DATABASE_URI,
    echo=False,
    pool_pre_ping=True,
)
SessionLocal = scoped_session(sessionmaker(bind=_engine))


def init_db():
    """验证数据库连接（表已通过init.sql创建）。"""
    try:
        with _engine.connect() as conn:
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
