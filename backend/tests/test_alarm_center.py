"""任务 E：告警中心 + 钉钉闭环测试。"""
import json
import os
import sys
from io import BytesIO
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


def test_dingtalk_signed_action_card_uses_public_confirm_url(monkeypatch, db):
    import base64
    import hashlib
    import hmac
    from urllib.parse import quote_plus

    from app.models.entities import AlarmEvent, Guard
    from app.services.dingtalk import DingTalkNotifier

    session = db()
    try:
        session.add_all([
            Guard(id=3, name="primary", role="primary", priority=0),
            AlarmEvent(
                id=12,
                region_id=1,
                camera_id=1,
                type="intrusion",
                level=1,
                status="pending",
                snapshot_url="/api/alarms/snapshots/12.jpg",
                created_at=datetime.utcnow(),
            ),
        ])
        session.commit()
    finally:
        session.close()

    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})

    monkeypatch.setattr("app.services.dingtalk.time.time", lambda: 1234.567)
    notifier = DingTalkNotifier(
        webhook="https://oapi.dingtalk.com/robot/send?access_token=test-token",
        secret="SECtest",
        public_base_url="https://example.test",
        timeout=0,
        session_factory=db,
        http_post=fake_post,
    )

    notifier.notify(12)

    timestamp = "1234567"
    string_to_sign = f"{timestamp}\nSECtest".encode("utf-8")
    expected_sign = quote_plus(
        base64.b64encode(hmac.new(b"SECtest", string_to_sign, hashlib.sha256).digest())
    )
    assert len(calls) == 1
    assert calls[0]["url"].endswith(f"&timestamp={timestamp}&sign={expected_sign}")
    assert "SECtest" not in calls[0]["url"]
    assert calls[0]["json"]["actionCard"]["singleURL"] == "https://example.test/api/alarms/12/confirm"
    assert "https://example.test/api/alarms/snapshots/12.jpg" in calls[0]["json"]["actionCard"]["text"]


def test_dingtalk_card_describes_actor_behavior_and_mentions_guard(db):
    from app.models.entities import AlarmEvent, Camera, Guard, Region
    from app.services.dingtalk import DingTalkNotifier

    session = db()
    try:
        session.add_all([
            Guard(
                id=31,
                name="Primary Guard",
                dingtalk_id="guard-userid-001",
                role="primary",
                priority=0,
            ),
            Camera(
                id=32,
                name="Reading Room Camera",
                stream_url="rtmp://local/test",
                resolution="1920*1080",
                status="online",
                created_at=datetime.utcnow(),
            ),
            Region(
                id=33,
                camera_id=32,
                user_id=None,
                name="Seat A1",
                type="danger_zone",
                polygon="[]",
                x_distance=10,
                y_stay_time=3,
                created_at=datetime.utcnow(),
            ),
            AlarmEvent(
                id=34,
                region_id=33,
                camera_id=32,
                type="fight",
                level=2,
                status="pending",
                face_match="member:7",
                snapshot_url="/api/alarms/snapshots/34.jpg",
                extra=json.dumps({
                    "actor": "Li Ming",
                    "behavior": "pushed another student",
                    "fuse": 0.91,
                }),
                created_at=datetime.utcnow(),
            ),
        ])
        session.commit()
    finally:
        session.close()

    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})

    notifier = DingTalkNotifier(
        webhook="https://oapi.dingtalk.com/robot/send?access_token=test-token",
        public_base_url="https://example.test",
        timeout=0,
        session_factory=db,
        http_post=fake_post,
    )

    notifier.notify(34)

    assert len(calls) == 2
    card = calls[0]["json"]["actionCard"]
    assert card["singleTitle"] == "确认处理"
    assert card["singleURL"] == "https://example.test/api/alarms/34/confirm"
    assert "Li Ming" in card["text"]
    assert "pushed another student" in card["text"]
    assert "Primary Guard" in card["text"]
    assert "Seat A1" in card["text"]
    assert "fuse=0.91" in card["text"]

    mention = calls[1]["json"]
    assert mention["msgtype"] == "text"
    assert mention["at"] == {"atUserIds": ["guard-userid-001"], "isAtAll": False}
    assert "Primary Guard" in mention["text"]["content"]
    assert "Alarm ID: 34" in mention["text"]["content"]


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

    confirmed_page = client.get("/api/alarms/21/confirm")
    assert confirmed_page.status_code == 200
    assert b"Alarm 21 confirmed" in confirmed_page.data

    missing_page = client.get("/api/alarms/404/confirm")
    assert missing_page.status_code == 404
    assert b"Alarm 404 not found" in missing_page.data


def test_fire_smoke_detect_endpoint_accepts_uploaded_image(monkeypatch):
    from app.api.alarms import bp

    called = {}

    def fake_detect(image, camera_id, region_id, frames, raise_alarm):
        called.update({
            "shape": image.shape,
            "camera_id": camera_id,
            "region_id": region_id,
            "frames": frames,
            "raise_alarm": raise_alarm,
        })
        return {
            "detections": [{"class": "fire", "confidence": 0.9}],
            "events": [],
            "alarms": [],
            "frames": frames,
            "window": 30,
            "threshold": 0.45,
        }

    monkeypatch.setattr("app.services.fire_smoke.detect_fire_smoke_image", fake_detect)

    app = Flask(__name__)
    app.register_blueprint(bp)
    client = app.test_client()

    import cv2

    ok, encoded = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok

    resp = client.post(
        "/api/alarms/fire-smoke/detect",
        data={
            "image": (BytesIO(encoded.tobytes()), "frame.jpg"),
            "camera_id": "5",
            "region_id": "7",
            "frames": "30",
            "raise_alarm": "true",
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["detections"] == [{"class": "fire", "confidence": 0.9}]
    assert called == {
        "shape": (8, 8, 3),
        "camera_id": 5,
        "region_id": 7,
        "frames": 30,
        "raise_alarm": True,
    }


def test_stream_capture_reads_frame_after_warmup(monkeypatch):
    from app.services import stream_capture

    state = {}

    class FakeCapture:
        def __init__(self, url, backend):
            self.url = url
            self.backend = backend
            self.read_count = 0
            self.released = False

        def isOpened(self):
            return True

        def set(self, *_args):
            return True

        def read(self):
            self.read_count += 1
            return True, np.full((2, 2, 3), self.read_count, dtype=np.uint8)

        def release(self):
            self.released = True

    def fake_video_capture(url, backend):
        cap = FakeCapture(url, backend)
        state["cap"] = cap
        return cap

    monkeypatch.setattr(stream_capture.cv2, "VideoCapture", fake_video_capture)

    frame = stream_capture.capture_frame("rtmp://unit/test", timeout=1, warmup_frames=1)

    assert frame[0, 0, 0] == 2
    assert state["cap"].url == "rtmp://unit/test"
    assert state["cap"].released is True


def test_stream_capture_reports_open_failure(monkeypatch):
    from app.services import stream_capture

    class FakeClosedCapture:
        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.setattr(stream_capture.cv2, "VideoCapture", lambda *_args: FakeClosedCapture())

    with pytest.raises(stream_capture.StreamCaptureError, match="failed to open stream"):
        stream_capture.capture_frame("rtmp://unit/missing", timeout=1)


def test_alarm_test_capture_endpoint_pulls_frame_and_raises_alarm(monkeypatch, db, snapshot_dir):
    from app.api.alarms import bp
    from app.models.entities import AlarmEvent, Camera, Region
    from app.services.alarm import AlarmService

    session = db()
    try:
        session.add_all([
            Camera(
                id=51,
                name="Unit Camera",
                stream_url="rtmp://unit/test",
                resolution="1920*1080",
                status="online",
                created_at=datetime.utcnow(),
            ),
            Region(
                id=52,
                camera_id=51,
                user_id=None,
                name="Unit Region",
                type="danger_zone",
                polygon="[]",
                x_distance=10,
                y_stay_time=3,
                created_at=datetime.utcnow(),
            ),
        ])
        session.commit()
    finally:
        session.close()

    captured = {}

    def fake_capture_frame(stream_url, timeout, warmup_frames, camera_id=None):
        captured.update({
            "stream_url": stream_url,
            "timeout": timeout,
            "warmup_frames": warmup_frames,
        })
        return np.zeros((6, 6, 3), dtype=np.uint8)

    sent = []
    notifier = FakeNotifier()
    svc = AlarmService(cooldown=30, notifier=notifier, broadcaster=sent.append)

    monkeypatch.setattr("app.services.stream_capture.capture_frame", fake_capture_frame)
    monkeypatch.setattr("app.services.alarm.get_alarm_service", lambda: svc)

    app = Flask(__name__)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/alarms/test-capture", json={
        "camera_id": 51,
        "region_id": 52,
        "type": "fight",
        "level": 2,
        "actor": "Li Ming",
        "behavior": "pushed another student",
        "timeout": 3,
        "warmup_frames": 0,
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    assert body["data"]["snapshot_url"].startswith("/api/alarms/snapshots/")
    assert captured == {
        "stream_url": "rtmp://unit/test",
        "timeout": 3.0,
        "warmup_frames": 0,
    }
    assert sent == [body["data"]]
    assert notifier.alarm_ids == [body["data"]["id"]]
    assert (snapshot_dir / os.path.basename(body["data"]["snapshot_url"])).exists()

    session = db()
    try:
        record = session.get(AlarmEvent, body["data"]["id"])
        extra = json.loads(record.extra)
        assert record.camera_id == 51
        assert record.region_id == 52
        assert record.type == "fight"
        assert record.level == 2
        assert extra["actor"] == "Li Ming"
        assert extra["behavior"] == "pushed another student"
        assert extra["source"] == "task_e_test_capture"
    finally:
        session.close()
