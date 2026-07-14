"""Task B fatigue detector and study companion tests."""
import json
import os
import sys

import numpy as np
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _landmarks(eye="open", mouth="normal"):
    points = np.zeros((68, 2), dtype=np.float32)
    open_eye = np.array([[0, 0], [1, 1], [2, 1], [4, 0], [2, -1], [1, -1]], dtype=np.float32)
    closed_eye = np.array([[0, 0], [1, 0.1], [2, 0.1], [4, 0], [2, -0.1], [1, -0.1]], dtype=np.float32)
    eye_points = closed_eye if eye == "closed" else open_eye
    points[36:42] = eye_points
    points[42:48] = eye_points + np.array([10, 0], dtype=np.float32)

    normal_mouth = np.array(
        [[0, 0], [1, 0], [1, 0.2], [3, 0.2], [4, 0], [3, -0.2], [1, -0.2], [1, 0]],
        dtype=np.float32,
    )
    yawn_mouth = np.array(
        [[0, 0], [1, 0], [1, 4], [3, 4], [4, 0], [3, -4], [1, -4], [1, 0]],
        dtype=np.float32,
    )
    points[60:68] = yawn_mouth if mouth == "yawn" else normal_mouth
    return points


def test_closed_eye_before_duration_does_not_alert():
    from app.detectors.fatigue import FatigueDetector

    detector = FatigueDetector(ear_thresh=0.2, ear_duration=2.0, mar_thresh=0.6)

    assert detector.detect(_landmarks(eye="closed"), ts=10.0) is None
    assert detector.detect(_landmarks(eye="closed"), ts=11.0) is None


def test_closed_eye_after_duration_returns_sleepy():
    from app.detectors.fatigue import FatigueDetector

    detector = FatigueDetector(ear_thresh=0.2, ear_duration=2.0, mar_thresh=0.6)

    assert detector.detect(_landmarks(eye="closed"), ts=10.0) is None
    assert detector.detect(_landmarks(eye="closed"), ts=12.0) == "sleepy"


def test_open_eye_resets_closed_eye_timer():
    from app.detectors.fatigue import FatigueDetector

    detector = FatigueDetector(ear_thresh=0.2, ear_duration=2.0, mar_thresh=0.6)

    assert detector.detect(_landmarks(eye="closed"), ts=10.0) is None
    assert detector.detect(_landmarks(eye="open"), ts=11.0) is None
    assert detector.detect(_landmarks(eye="closed"), ts=12.5) is None


def test_yawn_requires_window_hits():
    from app.detectors.fatigue import FatigueDetector

    detector = FatigueDetector(
        ear_thresh=0.2,
        ear_duration=2.0,
        mar_thresh=0.6,
        yawn_window=3,
        yawn_hits=2,
    )

    assert detector.detect(_landmarks(eye="open", mouth="yawn"), ts=10.0) is None
    result = detector.detect(_landmarks(eye="open", mouth="yawn"), ts=10.2)
    assert result == "yawn"
    assert result.mar > 0.6
    assert result.yawn_hits == 2
    assert result.yawn_window == 3


def test_blink_does_not_accumulate_into_sleepy():
    from app.detectors.fatigue import FatigueDetector

    detector = FatigueDetector(ear_thresh=0.2, ear_duration=2.0, mar_thresh=0.6)

    assert detector.detect(_landmarks(eye="closed"), ts=10.0) is None
    assert detector.detect(_landmarks(eye="open"), ts=10.2) is None
    assert detector.detect(_landmarks(eye="closed"), ts=11.9) is None


class _FakeRect:
    def __init__(self, left, top, right, bottom):
        self._left = left
        self._top = top
        self._right = right
        self._bottom = bottom

    def left(self): return self._left
    def top(self): return self._top
    def right(self): return self._right
    def bottom(self): return self._bottom
    def width(self): return self._right - self._left
    def height(self): return self._bottom - self._top


class _FakePart:
    def __init__(self, x, y):
        self.x = int(x)
        self.y = int(y)


class _FakeShape:
    def __init__(self, points):
        self._points = points

    def part(self, index):
        x, y = self._points[index]
        return _FakePart(x, y)


class _FakeFaceDetector:
    def __call__(self, image, upsample):
        return [_FakeRect(0, 0, 20, 20)]


class _StaticFaceDetector:
    def __init__(self, rects):
        self.rects = rects

    def __call__(self, image, upsample):
        return self.rects


class _FakeFaceMatcher:
    def __init__(self, result="member:2001"):
        self.result = result

    def encode_from_rect(self, image, rect):
        return np.array([1.0])

    def match(self, feature):
        return self.result


class _FakeShapePredictor:
    def __init__(self, points):
        self.points = points

    def __call__(self, image, rect):
        return _FakeShape(self.points)


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def query(self, *models):
        return self

    def join(self, *args, **kwargs):
        return self

    def outerjoin(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def close(self):
        pass


class _FakeSessionFactory:
    def __init__(self, rows):
        self.rows = rows

    def __call__(self):
        return _FakeSession(self.rows)


class _Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _seat_row(status="studying", region_id=5, mode="demo", member_id=None, reservation_member_id=None):
    seat_status = _Obj(user_id=1001, region_id=region_id, status=status, mode=mode, member_id=member_id)
    region = _Obj(
        id=region_id,
        camera_id=7,
        polygon=json.dumps([[0, 0], [100, 0], [100, 100], [0, 100]]),
    )
    reservation = _Obj(member_id=reservation_member_id) if reservation_member_id is not None else None
    return seat_status, region, reservation


def test_fatigue_plugin_emits_dingtalk_level_event_with_kind():
    from app.detectors.base import Frame
    from app.detectors.fatigue import FatigueDetector, FatiguePlugin

    plugin = FatiguePlugin(
        session_factory=_FakeSessionFactory([_seat_row()]),
        detector_factory=lambda: FatigueDetector(ear_thresh=0.2, ear_duration=0.0, mar_thresh=0.6),
        face_detector=_FakeFaceDetector(),
        shape_predictor=_FakeShapePredictor(_landmarks(eye="closed")),
    )
    plugin.setup()

    frame = Frame(image=np.zeros((120, 120, 3), dtype=np.uint8), ts=10.0, camera_id=7, frame_idx=1)
    events = plugin.detect(frame)

    assert len(events) == 1
    assert events[0].type == "fatigue"
    assert events[0].level == 1
    assert events[0].region_id == 5
    assert events[0].extra["kind"] == "sleepy"
    assert events[0].extra["user_id"] == 1001
    assert events[0].extra["level"] == 1
    assert events[0].extra["ear"] < 0.2
    assert "mar" in events[0].extra
    assert "closed_duration" in events[0].extra
    assert "yawn_hits" in events[0].extra
    assert "yawn_window" in events[0].extra
    assert events[0].extra["presentation"] == "companion"


def test_fatigue_plugin_rejects_outside_or_multiple_faces():
    from app.detectors.base import Frame
    from app.detectors.fatigue import FatigueDetector, FatiguePlugin

    outside = FatiguePlugin(
        session_factory=_FakeSessionFactory([_seat_row()]),
        detector_factory=lambda: FatigueDetector(ear_duration=0.0),
        face_detector=_StaticFaceDetector([_FakeRect(105, 0, 119, 20)]),
        shape_predictor=_FakeShapePredictor(_landmarks(eye="closed")),
    )
    outside.setup()
    frame = Frame(image=np.zeros((120, 120, 3), dtype=np.uint8), ts=10.0, camera_id=7, frame_idx=1)
    assert outside.detect(frame) == []
    assert outside.get_runtime_state(5)["reason"] == "no_in_seat_face"

    multiple = FatiguePlugin(
        session_factory=_FakeSessionFactory([_seat_row()]),
        detector_factory=lambda: FatigueDetector(ear_duration=0.0),
        face_detector=_StaticFaceDetector([_FakeRect(0, 0, 20, 20), _FakeRect(30, 0, 50, 20)]),
        shape_predictor=_FakeShapePredictor(_landmarks(eye="closed")),
    )
    multiple.setup()
    assert multiple.detect(frame) == []
    assert multiple.get_runtime_state(5)["reason"] == "ambiguous_face"


def test_verified_fatigue_requires_reserved_member_match():
    from app.detectors.base import Frame
    from app.detectors.fatigue import FatigueDetector, FatiguePlugin

    row = _seat_row(mode="verified", member_id=2001, reservation_member_id=2001)
    frame = Frame(image=np.zeros((120, 120, 3), dtype=np.uint8), ts=10.0, camera_id=7, frame_idx=1)
    blocked = FatiguePlugin(
        session_factory=_FakeSessionFactory([row]), detector_factory=lambda: FatigueDetector(ear_duration=0.0),
        face_detector=_FakeFaceDetector(), shape_predictor=_FakeShapePredictor(_landmarks(eye="closed")),
        face_matcher=_FakeFaceMatcher("stranger"),
    )
    blocked.setup()
    assert blocked.detect(frame) == []
    assert blocked.get_runtime_state(5)["reason"] == "identity_mismatch"

    accepted = FatiguePlugin(
        session_factory=_FakeSessionFactory([row]), detector_factory=lambda: FatigueDetector(ear_duration=0.0),
        face_detector=_FakeFaceDetector(), shape_predictor=_FakeShapePredictor(_landmarks(eye="closed")),
        face_matcher=_FakeFaceMatcher("member:2001"),
    )
    accepted.setup()
    assert accepted.detect(frame)[0].extra["mode"] == "verified"


def test_fatigue_plugin_cooldown_suppresses_repeated_alerts(monkeypatch):
    from app.detectors.base import Frame
    from app.detectors.fatigue import FatigueDetector, FatiguePlugin

    monkeypatch.setattr("app.detectors.fatigue.Config.FATIGUE_ALERT_COOLDOWN", 60)
    plugin = FatiguePlugin(
        session_factory=_FakeSessionFactory([_seat_row()]),
        detector_factory=lambda: FatigueDetector(ear_thresh=0.2, ear_duration=0.0, mar_thresh=0.6),
        face_detector=_FakeFaceDetector(),
        shape_predictor=_FakeShapePredictor(_landmarks(eye="closed")),
    )
    plugin.setup()

    first = Frame(image=np.zeros((120, 120, 3), dtype=np.uint8), ts=10.0, camera_id=7, frame_idx=1)
    second = Frame(image=np.zeros((120, 120, 3), dtype=np.uint8), ts=20.0, camera_id=7, frame_idx=2)
    third = Frame(image=np.zeros((120, 120, 3), dtype=np.uint8), ts=71.0, camera_id=7, frame_idx=3)

    assert len(plugin.detect(first)) == 1
    assert plugin.detect(second) == []
    assert len(plugin.detect(third)) == 1


def test_fatigue_plugin_resting_hot_update_disables_region():
    from app.detectors.base import Frame
    from app.detectors.fatigue import FatigueDetector, FatiguePlugin

    plugin = FatiguePlugin(
        session_factory=_FakeSessionFactory([_seat_row()]),
        detector_factory=lambda: FatigueDetector(ear_thresh=0.2, ear_duration=0.0, mar_thresh=0.6),
        face_detector=_FakeFaceDetector(),
        shape_predictor=_FakeShapePredictor(_landmarks(eye="closed")),
    )
    plugin.setup()
    plugin.on_config_changed({"region_id": 5, "status": "resting"})

    frame = Frame(image=np.zeros((120, 120, 3), dtype=np.uint8), ts=10.0, camera_id=7, frame_idx=1)
    assert plugin.detect(frame) == []
    assert plugin.enabled is False


@pytest.fixture
def seat_api_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from app.models.entities import Base, Region

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.api.seat_status.SessionLocal", Session)

    session = Session()
    session.add(Region(id=5, camera_id=7, type="seat", polygon=json.dumps([[0, 0], [1, 0], [1, 1]])))
    session.add(Region(id=6, camera_id=7, type="seat", polygon=json.dumps([[0, 0], [1, 0], [1, 1]])))
    session.commit()
    session.close()
    yield Session
    engine.dispose()


class _FakeEngine:
    def __init__(self):
        self.configs = []
        self.enabled = []

    def on_config_changed(self, name, cfg):
        self.configs.append((name, cfg))

    def set_enabled(self, name, enabled):
        self.enabled.append((name, enabled))


class _FakeScheduler:
    def __init__(self):
        self.engine = _FakeEngine()

    def status(self):
        return {7: True}


def _client(monkeypatch, scheduler):
    from app.api import seat_status

    monkeypatch.setattr(seat_status, "get_scheduler", lambda: scheduler)
    app = Flask(__name__)
    app.register_blueprint(seat_status.bp)
    return app.test_client()


def test_seat_status_upserts_and_notifies(monkeypatch, seat_api_db):
    scheduler = _FakeScheduler()
    client = _client(monkeypatch, scheduler)

    response = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "studying"})

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "studying"
    expected_cfg = scheduler.engine.configs[-1][1]
    assert expected_cfg["status"] == "studying"
    assert expected_cfg["mode"] == "demo"
    assert ("fatigue", expected_cfg) in scheduler.engine.configs
    assert scheduler.engine.enabled[-1] == ("fatigue", True)

    response = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "resting"})

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "resting"
    assert scheduler.engine.configs[-1][1]["status"] == "resting"
    assert scheduler.engine.enabled[-1] == ("fatigue", False)


def test_seat_status_invalid_status_and_missing_region(monkeypatch, seat_api_db):
    client = _client(monkeypatch, _FakeScheduler())

    invalid = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "sleeping"})
    missing = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 999, "status": "studying"})

    assert invalid.status_code == 400
    assert missing.status_code == 404


def test_verified_session_requires_matching_reservation(monkeypatch, seat_api_db):
    from app.models.entities import Member, SeatReservation

    session = seat_api_db()
    session.add(Member(member_id=2001, name="Verified", feature="[1.0]"))
    session.add(SeatReservation(region_id=5, member_id=2001, enabled=True))
    session.commit()
    session.close()
    client = _client(monkeypatch, _FakeScheduler())

    missing = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "studying", "mode": "verified"})
    mismatch = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "studying", "mode": "verified", "member_id": 2002})
    accepted = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "studying", "mode": "verified", "member_id": 2001})

    assert missing.status_code == 400
    assert mismatch.status_code == 400
    assert accepted.status_code == 200
    assert accepted.get_json()["data"]["member_id"] == 2001


def test_new_study_session_idles_previous_user(monkeypatch, seat_api_db):
    from app.models.entities import SeatStatus

    client = _client(monkeypatch, _FakeScheduler())
    first = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "studying"})
    second = client.post("/api/seat-status", json={"user_id": 1002, "region_id": 5, "status": "studying"})
    assert first.status_code == 200
    assert second.status_code == 200

    session = seat_api_db()
    rows = session.query(SeatStatus).filter_by(region_id=5).all()
    session.close()
    assert sum(row.status == "studying" for row in rows) == 1
    assert next(row for row in rows if row.status == "studying").user_id == 1002


def test_companion_websocket_routes_only_matching_fatigue_event():
    from app.api import ws

    class FakeSocket:
        def __init__(self):
            self.messages = []

        def send(self, data):
            self.messages.append(data)

    matching = FakeSocket()
    other = FakeSocket()
    old = ws._companion_subscribers
    ws._companion_subscribers = {(1001, 5): {matching}, (1002, 5): {other}}
    try:
        sent = ws.broadcast_companion_alarm({
            "type": "fatigue", "region_id": 5, "extra": {"user_id": 1001, "kind": "yawn"},
        })
        assert sent == 1
        assert len(matching.messages) == 1
        assert other.messages == []
    finally:
        ws._companion_subscribers = old


def test_disabling_one_region_keeps_fatigue_enabled_when_another_is_studying(monkeypatch, seat_api_db):
    scheduler = _FakeScheduler()
    client = _client(monkeypatch, scheduler)

    client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "studying"})
    client.post("/api/seat-status", json={"user_id": 1002, "region_id": 6, "status": "studying"})
    response = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "resting"})

    assert response.status_code == 200
    assert scheduler.engine.enabled[-1] == ("fatigue", True)


def test_companion_status_reports_latest_fatigue(monkeypatch, seat_api_db):
    from app.models.entities import AlarmEvent, SeatStatus

    session = seat_api_db()
    try:
        session.add(SeatStatus(user_id=1001, region_id=5, status="studying"))
        session.add(AlarmEvent(
            type="fatigue",
            region_id=5,
            camera_id=7,
            level=1,
            status="notified",
            extra=json.dumps({"kind": "yawn", "user_id": 1001, "ear": 0.31, "mar": 0.82}),
        ))
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr("app.api.seat_status.Config.DINGTALK_WEBHOOK", "")
    client = _client(monkeypatch, _FakeScheduler())

    response = client.get("/api/seat-status/companion?user_id=1001&region_id=5")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "studying"
    assert data["dingtalk_configured"] is False
    assert data["latest_fatigue"]["extra"]["kind"] == "yawn"
