import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.detectors.base import Frame
from app.detectors.intrusion import IntrusionPlugin
from app.models.entities import Base, Camera, Region, SeatStatus


class FakePersonDetector:
    def setup(self):
        pass

    def detect_people(self, image):
        return [(20, 10, 80, 80)]


class FakeFaceMatcher:
    def __init__(self, result):
        self.result = result

    def encode(self, crop):
        return [1.0]

    def match(self, feature):
        return self.result


def make_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.detectors.intrusion.SessionLocal", Session)
    return Session


def seed_reserved_seat(Session, user_id=1001):
    session = Session()
    try:
        session.add(Camera(id=0, name="cam", stream_url="rtmp://example/live/test"))
        session.add(
            Region(
                id=10,
                camera_id=0,
                name="seat-10",
                type="seat",
                polygon="[[0,0],[100,0],[100,100],[0,100]]",
                x_distance=0,
                y_stay_time=0,
            )
        )
        session.add(SeatStatus(user_id=user_id, region_id=10, status="studying"))
        session.commit()
    finally:
        session.close()


def test_reserved_user_entering_seat_does_not_alarm(monkeypatch):
    Session = make_session(monkeypatch)
    seed_reserved_seat(Session, user_id=1001)
    plugin = IntrusionPlugin(
        person_detector=FakePersonDetector(),
        face_matcher=FakeFaceMatcher("member:1001"),
    )
    plugin.setup()
    image = np.zeros((120, 120, 3), dtype=np.uint8)

    plugin.detect(Frame(image=image, ts=1.0, camera_id=0, frame_idx=1))
    events = plugin.detect(Frame(image=image, ts=2.0, camera_id=0, frame_idx=2))

    assert events == []


def test_unreserved_user_entering_seat_raises_occupy(monkeypatch):
    Session = make_session(monkeypatch)
    seed_reserved_seat(Session, user_id=1001)
    plugin = IntrusionPlugin(
        person_detector=FakePersonDetector(),
        face_matcher=FakeFaceMatcher("member:2002"),
    )
    plugin.setup()
    image = np.zeros((120, 120, 3), dtype=np.uint8)

    plugin.detect(Frame(image=image, ts=1.0, camera_id=0, frame_idx=1))
    events = plugin.detect(Frame(image=image, ts=2.0, camera_id=0, frame_idx=2))

    assert len(events) == 1
    assert events[0].type == "occupy"
    assert events[0].region_id == 10
    assert events[0].face_match == "member:2002"
    assert events[0].extra["expected_user_id"] == 1001
    assert events[0].extra["kind"] == "unauthorized_seat"
