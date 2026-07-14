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
        self.escalated_ids = []      # 启动了升级 timer 的告警
        self.non_escalated_ids = []  # 推送但不升级的告警(level=0)

    def notify(self, alarm_id, escalate=True):
        self.alarm_ids.append(alarm_id)
        (self.escalated_ids if escalate else self.non_escalated_ids).append(alarm_id)


def test_dingtalk_reports_missing_webhook_at_startup(caplog):
    from app.services.dingtalk import DingTalkNotifier

    caplog.set_level("WARNING")
    DingTalkNotifier(webhook="", timeout=0)

    assert "primary webhook is not configured" in caplog.text


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


def test_level_zero_alarm_pushes_without_escalation(db, snapshot_dir):
    """level=0 轻量提醒：照常入库+推前端+推钉钉，但不启动升级 timer。"""
    from app.detectors.base import AlarmEvent
    from app.models.entities import AlarmEvent as AlarmRecord
    from app.services.alarm import AlarmService

    sent = []
    notifier = FakeNotifier()
    svc = AlarmService(cooldown=30, notifier=notifier, broadcaster=sent.append)

    payload = svc.raise_alarm(AlarmEvent(type="fatigue", region_id=4, camera_id=0, level=0))

    session = db()
    try:
        assert payload["level"] == 0
        assert payload["camera_id"] == 0
        assert session.query(AlarmRecord).count() == 1
        assert session.query(AlarmRecord).one().camera_id == 0
        # 新行为：level=0 也推送到前端与钉钉
        assert sent == [payload]
        assert notifier.alarm_ids == [payload["id"]]
        # 但不升级
        assert notifier.non_escalated_ids == [payload["id"]]
        assert notifier.escalated_ids == []
    finally:
        session.close()


def test_level_one_fatigue_alarm_notifies(db, snapshot_dir):
    from app.detectors.base import AlarmEvent
    from app.services.alarm import AlarmService

    sent = []
    notifier = FakeNotifier()
    svc = AlarmService(cooldown=30, notifier=notifier, broadcaster=sent.append)

    payload = svc.raise_alarm(AlarmEvent(type="fatigue", region_id=4, camera_id=0, level=1))

    assert payload["type"] == "fatigue"
    assert payload["level"] == 1
    assert sent == [payload]
    assert notifier.alarm_ids == [payload["id"]]


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
    card_text = calls[0]["json"]["actionCard"]["text"]
    assert "https://example.test/api/alarms/snapshots/12.jpg" not in card_text
    assert "证据: 抓拍/回放已保存到服务器" in card_text


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
    assert "融合判断分约为 0.91" in card["text"]
    assert "请 Primary Guard 处理" in card["text"]
    assert "存在“pushed another student”的情况" in card["text"]
    assert "/api/alarms/snapshots/34.jpg" not in card["text"]
    assert "证据: 抓拍/回放已保存到服务器" in card["text"]

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
            snapshot_url="/api/alarms/snapshots/21.jpg",
            clip_url="/api/alarms/clips/21.mp4",
            message="Li Ming triggered fight",
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
    assert "状态已同步到告警中心".encode("utf-8") in confirmed_page.data
    assert b"Li Ming triggered fight" not in confirmed_page.data
    assert b"/api/alarms/snapshots/21.jpg" not in confirmed_page.data
    assert b"/api/alarms/clips/21.mp4" not in confirmed_page.data

    missing_page = client.get("/api/alarms/404/confirm")
    assert missing_page.status_code == 404
    assert b"Alarm 404 not found" in missing_page.data


def test_alarm_clip_endpoint_supports_range(monkeypatch, tmp_path):
    from app.api.alarms import bp

    clip_dir = tmp_path / "clips"
    clip_dir.mkdir()
    (clip_dir / "alarm_21.mp4").write_bytes(b"0123456789")
    monkeypatch.setattr("app.config.Config.CLIP_DIR", str(clip_dir))

    app = Flask(__name__)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.get(
        "/api/alarms/clips/alarm_21.mp4",
        headers={"Range": "bytes=2-5"},
    )

    assert resp.status_code == 206
    assert resp.data == b"2345"
    assert resp.headers["Content-Range"].startswith("bytes 2-5/")


def test_clip_recorder_keeps_post_window_when_started_late(monkeypatch, tmp_path):
    import cv2
    from app.services.clip_recorder import ClipRecorder

    encoded_frames = []
    for value in (40, 80, 120):
        ok, jpg = cv2.imencode(".jpg", np.full((24, 32, 3), value, dtype=np.uint8))
        assert ok
        encoded_frames.append(jpg.tobytes())

    class FakeCamera:
        online = True

        def __init__(self):
            self.index = 0

        def get_frames_since(self, ts):
            return []

        def latest_frame(self):
            frame = encoded_frames[min(self.index, len(encoded_frames) - 1)]
            self.index += 1
            return frame

        def wait_frame(self, timeout=0.1):
            return self.index < len(encoded_frames)

    class FakeScheduler:
        def __init__(self):
            self.camera = FakeCamera()

        def get_camera(self, camera_id):
            return self.camera if camera_id == 5 else None

    updates = []
    recorder = ClipRecorder(clip_dir=str(tmp_path / "clips"))
    monkeypatch.setattr("app.services.clip_recorder.get_scheduler", lambda: FakeScheduler())
    monkeypatch.setattr(
        recorder,
        "_update_alarm_clip_url",
        lambda alarm_id, filename: updates.append((alarm_id, filename)),
    )
    monkeypatch.setattr("app.config.Config.CLIP_POST_SECONDS", 1)
    monkeypatch.setattr("app.config.Config.CLIP_FPS", 15)

    recorder._do_record(
        camera_id=5,
        alarm_id=77,
        event_ts=1.0,
        alarm_type="fight",
        filename="alarm_77_late.mp4",
    )

    output = tmp_path / "clips" / "alarm_77_late.mp4"
    assert output.exists()
    assert output.stat().st_size > 0
    cap = cv2.VideoCapture(str(output))
    try:
        assert cap.isOpened()
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 1
        assert frames / fps >= 1.0
    finally:
        cap.release()
    assert updates == [(77, "alarm_77_late.mp4")]


def test_daily_report_generates_json_and_markdown_artifacts(monkeypatch, db, tmp_path):
    from app.models.entities import AlarmEvent, Camera, Region
    from app.services.daily_report import DailyReportService

    monkeypatch.setattr("app.config.Config.LLM_ENABLED", False)
    report_date = datetime(2026, 7, 11)

    session = db()
    try:
        session.add_all([
            Camera(
                id=61,
                name="Report Camera",
                stream_url="rtmp://unit/report",
                resolution="1920*1080",
                status="online",
                created_at=report_date,
            ),
            Region(
                id=62,
                camera_id=61,
                user_id=None,
                name="Report Region",
                type="danger_zone",
                polygon="[]",
                x_distance=10,
                y_stay_time=3,
                created_at=report_date,
            ),
            AlarmEvent(
                id=63,
                region_id=62,
                camera_id=61,
                type="fight",
                level=2,
                status="confirmed",
                message="Li Ming triggered fight",
                created_at=datetime(2026, 7, 11, 8, 30, 0),
                confirmed_at=datetime(2026, 7, 11, 8, 33, 0),
            ),
        ])
        session.commit()
    finally:
        session.close()

    service = DailyReportService(report_dir=str(tmp_path))
    report = service.generate_report(report_date)
    artifacts = service.generate_artifacts(report_date, formats=("json", "markdown"))

    assert report["summary"]["total_alarms"] == 1
    assert report["summary"]["confirmed_count"] == 1
    assert report["summary"]["avg_response_time_minutes"] == 3.0
    assert report["top_regions"][0]["name"] == "Report Region"
    assert report["alarm_details"][0]["message"] == "Li Ming triggered fight"
    assert os.path.exists(artifacts["outputs"]["json"])
    assert os.path.exists(artifacts["outputs"]["markdown"])


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


def test_stream_capture_configures_ffmpeg_options(monkeypatch):
    from app.services import stream_capture

    class FakeClosedCapture:
        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.delenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", raising=False)
    monkeypatch.delenv("OPENCV_FFMPEG_READ_ATTEMPTS", raising=False)
    monkeypatch.setattr(stream_capture.cv2, "VideoCapture", lambda *_args: FakeClosedCapture())

    with pytest.raises(stream_capture.StreamCaptureError):
        stream_capture.capture_frame("rtmp://unit/missing", timeout=1)

    assert "rtmp_live;live" in os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]
    assert os.environ["OPENCV_FFMPEG_READ_ATTEMPTS"] == "100000"


def test_stream_capture_does_not_use_other_camera_scheduler_frame(monkeypatch):
    from app.services import stream_capture

    class OtherCamera:
        def latest_frame(self):
            ok, jpg = stream_capture.cv2.imencode(".jpg", np.ones((2, 2, 3), dtype=np.uint8))
            assert ok
            return jpg.tobytes()

    class FakeScheduler:
        camera_ids = [99]

        def get_camera(self, camera_id):
            if camera_id == 99:
                return OtherCamera()
            return None

    class FakeClosedCapture:
        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.setattr("app.stream.scheduler.get_scheduler", lambda: FakeScheduler())
    monkeypatch.setattr(stream_capture.cv2, "VideoCapture", lambda *_args: FakeClosedCapture())

    with pytest.raises(stream_capture.StreamCaptureError, match="failed to open stream"):
        stream_capture.capture_frame("rtmp://unit/requested", timeout=1, camera_id=51)


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
