"""SQLAlchemy 数据模型 (§8.2)。"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Camera(Base):
    __tablename__ = "camera"
    id = Column(Integer, primary_key=True)
    name = Column(String(128))
    stream_url = Column(String(256))
    resolution = Column(String(32))
    status = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class AppUser(Base):
    __tablename__ = "app_user"
    id = Column(Integer, primary_key=True)
    nickname = Column(Text)
    device_token = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Region(Base):
    __tablename__ = "region"
    id = Column(Integer, primary_key=True)
    camera_id = Column(Integer, ForeignKey("camera.id"))
    user_id = Column(Integer, ForeignKey("app_user.id"))
    name = Column(String(128))
    type = Column(Text)
    polygon = Column(Text)
    x_distance = Column(Integer)
    y_stay_time = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class SeatStatus(Base):
    __tablename__ = "seat_status"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("app_user.id"))
    region_id = Column(Integer, ForeignKey("region.id"))
    guard_id = Column(Integer, ForeignKey("guard.id"))
    status = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlarmEvent(Base):
    __tablename__ = "alarm_event"
    id = Column(Integer, primary_key=True)
    region_id = Column(Integer, ForeignKey("region.id"))
    camera_id = Column(Integer, ForeignKey("camera.id"))
    type = Column(Enum("intrusion", "fire_smoke", "occupy", "fatigue", "fight", "face_recognition", "face_spoof", name="alarm_type"))
    snapshot_url = Column(String(256))     # 抓拍图路径
    clip_url = Column(String(256))         # 视频片段路径(任务书G)
    face_match = Column(String(64))        # 会员ID / stranger
    message = Column(Text)                 # 告警文字描述(任务书G4)
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
    name = Column(Text)
    feature = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class SeatReservation(Base):
    """Long-lived seat-to-member binding used by identity intrusion checks."""

    __tablename__ = "seat_reservation"

    id = Column(Integer, primary_key=True)
    region_id = Column(Integer, ForeignKey("region.id", ondelete="CASCADE"), unique=True, nullable=False)
    member_id = Column(
        Integer,
        ForeignKey("member.member_id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_seat_reservation_member", "member_id"),
    )


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
