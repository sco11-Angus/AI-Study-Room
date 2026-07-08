"""SQLAlchemy 数据模型 (§8.2)。"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Camera(Base):
    __tablename__ = "camera"
    id = Column(Integer, primary_key=True)
    name = Column(String(128))
    stream_url = Column(String(256))       # RTMP 拉流地址
    resolution = Column(String(32))        # 原始分辨率，用于坐标映射
    status = Column(Enum("online", "offline", name="camera_status"))


class Region(Base):
    __tablename__ = "region"
    id = Column(Integer, primary_key=True)
    camera_id = Column(Integer, ForeignKey("camera.id"))
    name = Column(String(128))
    type = Column(Enum("danger_zone", "seat", name="region_type"))
    polygon = Column(Text)                 # JSON 顶点数组(原始分辨率)
    x_distance = Column(Integer)           # 安全距离阈值(像素)
    y_stay_time = Column(Integer)          # 允许停留时间(秒)


class SeatStatus(Base):
    __tablename__ = "seat_status"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    region_id = Column(Integer, ForeignKey("region.id"))
    status = Column(Enum("idle", "studying", "resting", name="seat_state"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlarmEvent(Base):
    __tablename__ = "alarm_event"
    id = Column(Integer, primary_key=True)
    region_id = Column(Integer, ForeignKey("region.id"))
    camera_id = Column(Integer, ForeignKey("camera.id"))
    type = Column(Enum("intrusion", "fire_smoke", "occupy", "fatigue", "fight", name="alarm_type"))
    snapshot_url = Column(String(256))     # 抓拍图路径
    face_match = Column(String(64))        # 会员ID / stranger
    level = Column(Integer, default=1)     # 优先级(升级递增)
    status = Column(Enum("pending", "notified", "confirmed", "escalated", name="alarm_status"), default="pending")
    extra = Column(Text)                   # 附加信息(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime)

    __table_args__ = (
        Index("idx_alarm_status", "status"),
        Index("idx_alarm_created", "created_at"),
        Index("idx_alarm_region_type", "region_id", "type"),
    )


class Member(Base):
    __tablename__ = "member"
    member_id = Column(Integer, primary_key=True)
    name = Column(String(128))
    feature = Column(Text)                 # 128 维人脸特征向量(JSON)


class Guard(Base):
    __tablename__ = "guard"
    id = Column(Integer, primary_key=True)
    name = Column(String(128))
    dingtalk_id = Column(String(128))
    role = Column(Enum("primary", "leader", name="guard_role"), default="primary")
    priority = Column(Integer, default=0)


class NotificationLog(Base):
    __tablename__ = "notification_log"
    id = Column(Integer, primary_key=True)
    alarm_id = Column(Integer, ForeignKey("alarm_event.id"))
    guard_id = Column(Integer, ForeignKey("guard.id"))
    stage = Column(Enum("primary", "escalated", name="notify_stage"))
    sent_at = Column(DateTime, default=datetime.utcnow)
    ack_at = Column(DateTime)

    __table_args__ = (Index("idx_notify_alarm", "alarm_id"),)
