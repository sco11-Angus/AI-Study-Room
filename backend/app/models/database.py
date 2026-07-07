"""数据库会话管理（SQLAlchemy）。"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..config import Config

_engine = create_engine(
    Config.DATABASE_URI,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in Config.DATABASE_URI else {},
)
SessionLocal = sessionmaker(bind=_engine)


def init_db():
    """创建所有表（首次启动调用）。"""
    from .entities import Base
    Base.metadata.create_all(_engine)
