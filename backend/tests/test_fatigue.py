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


def test_yawn_returns_yawn_immediately():
    from app.detectors.fatigue import FatigueDetector

    detector = FatigueDetector(ear_thresh=0.2, ear_duration=2.0, mar_thresh=0.6)

    assert detector.detect(_landmarks(eye="open", mouth="yawn"), ts=10.0) == "yawn"


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


def _seat_row(status="studying", region_id=5):
    seat_status = _Obj(user_id=1001, region_id=region_id, status=status)
    region = _Obj(
        id=region_id,
        camera_id=7,
        polygon=json.dumps([[0, 0], [100, 0], [100, 100], [0, 100]]),
    )
    return seat_status, region


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
    expected_cfg = {"region_id": 5, "status": "studying", "user_id": 1001}
    assert ("fatigue", expected_cfg) in scheduler.engine.configs
    assert ("intrusion", expected_cfg) in scheduler.engine.configs
    assert scheduler.engine.enabled[-1] == ("fatigue", True)

    response = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "resting"})

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "resting"
    assert ("fatigue", {"region_id": 5, "status": "resting", "user_id": 1001}) in scheduler.engine.configs
    assert ("intrusion", {"region_id": 5, "status": "resting", "user_id": 1001}) in scheduler.engine.configs
    assert scheduler.engine.enabled[-1] == ("fatigue", False)


def test_seat_status_invalid_status_and_missing_region(monkeypatch, seat_api_db):
    client = _client(monkeypatch, _FakeScheduler())

    invalid = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "sleeping"})
    missing = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 999, "status": "studying"})

    assert invalid.status_code == 400
    assert missing.status_code == 404


def test_disabling_one_region_keeps_fatigue_enabled_when_another_is_studying(monkeypatch, seat_api_db):
    scheduler = _FakeScheduler()
    client = _client(monkeypatch, scheduler)

    client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "studying"})
    client.post("/api/seat-status", json={"user_id": 1002, "region_id": 6, "status": "studying"})
    response = client.post("/api/seat-status", json={"user_id": 1001, "region_id": 5, "status": "resting"})

    assert response.status_code == 200
    assert scheduler.engine.enabled[-1] == ("fatigue", True)
