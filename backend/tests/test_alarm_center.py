"""任务 E：告警中心 + 钉钉闭环测试。"""
import json
import os
import sys
from datetime import datetime

import numpy as np
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from app.models.entities import Base

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.models.database.SessionLocal", Session)
    yield Session
    engine.dispose()


@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    path = tmp_path / "snapshots"
    monkeypatch.setattr("app.config.Config.SNAPSHOT_DIR", str(path))
    return path


class FakeNotifier:
    def __init__(self):
        self.alarm_ids = []

    def notify(self, alarm_id):
        self.alarm_ids.append(alarm_id)


def test_raise_alarm_persists_snapshot_and_notifies(db, snapshot_dir):
    from app.detectors.base import AlarmEvent
    from app.models.entities import AlarmEvent as AlarmRecord
    from app.services.alarm import AlarmService

    sent = []
    notifier = FakeNotifier()
    svc = AlarmService(cooldown=30, notifier=notifier, broadcaster=sent.append)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    payload = svc.raise_alarm(
        AlarmEvent(type="intrusion", region_id=2, camera_id=3, ts=123.0),
        frame=frame,
    )

    session = db()
    try:
        records = session.query(AlarmRecord).all()
        assert len(records) == 1
        assert records[0].status == "pending"
        assert records[0].camera_id == 3
        assert records[0].face_match == "stranger"
    finally:
        session.close()

    assert payload["snapshot_url"].startswith("/api/alarms/snapshots/")
    assert (snapshot_dir / os.path.basename(payload["snapshot_url"])).exists()
    assert sent == [payload]
    assert notifier.alarm_ids == [payload["id"]]


def test_dedup_same_region_type_only_creates_one_record(db, snapshot_dir):
    from app.detectors.base import AlarmEvent
    from app.models.entities import AlarmEvent as AlarmRecord
    from app.services.alarm import AlarmService

    svc = AlarmService(cooldown=30, notifier=FakeNotifier(), broadcaster=lambda _: 0)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    first = svc.raise_alarm(AlarmEvent(type="fight", region_id=9, camera_id=1), frame=frame)
    second = svc.raise_alarm(AlarmEvent(type="fight", region_id=9, camera_id=1), frame=frame)

    session = db()
    try:
        assert first is not None
        assert second is None
        assert session.query(AlarmRecord).count() == 1
    finally:
        session.close()


def test_level_zero_alarm_is_private_only(db, snapshot_dir):
    from app.detectors.base import AlarmEvent
    from app.models.entities import AlarmEvent as AlarmRecord
    from app.services.alarm import AlarmService

    sent = []
    notifier = FakeNotifier()
    svc = AlarmService(cooldown=30, notifier=notifier, broadcaster=sent.append)

    payload = svc.raise_alarm(AlarmEvent(type="fatigue", region_id=4, camera_id=1, level=0))

    session = db()
    try:
        assert payload["level"] == 0
        assert session.query(AlarmRecord).count() == 1
        assert sent == []
        assert notifier.alarm_ids == []
    finally:
        session.close()


def test_dingtalk_notify_confirm_and_escalate_update_logs(db):
    from app.models.entities import AlarmEvent, Guard, NotificationLog
    from app.services.dingtalk import DingTalkNotifier

    session = db()
    try:
        session.add_all([
            Guard(id=1, name="主责", role="primary", priority=0),
            Guard(id=2, name="科长", role="leader", priority=0),
            AlarmEvent(id=10, region_id=1, camera_id=1, type="intrusion", level=1, status="pending", created_at=datetime.utcnow()),
            AlarmEvent(id=11, region_id=1, camera_id=1, type="fight", level=2, status="notified", created_at=datetime.utcnow()),
        ])
        session.commit()
    finally:
        session.close()

    notifier = DingTalkNotifier(webhook="", timeout=0, session_factory=db)
    notifier.notify(10)
    assert notifier.confirm(10) is True
    notifier._escalate(11)

    session = db()
    try:
        confirmed = session.get(AlarmEvent, 10)
        escalated = session.get(AlarmEvent, 11)
        logs = session.query(NotificationLog).order_by(NotificationLog.id).all()
        assert confirmed.status == "confirmed"
        assert confirmed.confirmed_at is not None
        assert escalated.status == "escalated"
        assert escalated.level == 3
        assert [(log.alarm_id, log.guard_id, log.stage) for log in logs] == [
            (10, 1, "primary"),
            (11, 2, "escalated"),
        ]
        assert logs[0].ack_at is not None
    finally:
        session.close()


def test_alarm_api_lists_and_confirms(monkeypatch, db):
    from app.api.alarms import bp
    from app.models.entities import AlarmEvent

    session = db()
    try:
        session.add(AlarmEvent(
            id=21,
            region_id=5,
            camera_id=6,
            type="fight",
            level=2,
            status="pending",
            extra=json.dumps({"fuse": 0.9}),
            created_at=datetime.utcnow(),
        ))
        session.commit()
    finally:
        session.close()

    class FakeApiNotifier:
        def confirm(self, alarm_id):
            return alarm_id == 21

    monkeypatch.setattr("app.services.dingtalk.get_notifier", lambda: FakeApiNotifier())

    app = Flask(__name__)
    app.register_blueprint(bp)
    client = app.test_client()

    listed = client.get("/api/alarms?status=pending")
    assert listed.status_code == 200
    assert listed.get_json()["data"][0]["extra"] == {"fuse": 0.9}

    confirmed = client.post("/api/alarms/21/confirm")
    assert confirmed.status_code == 200
    assert confirmed.get_json()["data"] == {"id": 21, "status": "confirmed"}
