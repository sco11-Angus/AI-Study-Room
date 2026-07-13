import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.detectors.base import Frame
from app.detectors.intrusion import IntrusionPlugin
from app.models.entities import Base, Camera, Member, Region, SeatReservation


class FakePersonDetector:
    def __init__(self, boxes=None):
        self.boxes = boxes or [(20, 10, 80, 80)]

    def setup(self):
        pass

    def detect_people(self, image):
        return list(self.boxes)


class FakeFaceMatcher:
    def __init__(self, result):
        self.results = list(result) if isinstance(result, list) else [result]

    def encode(self, crop):
        return [1.0]

    def match(self, feature):
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class FakeRect:
    def __init__(self, left, top, right, bottom):
        self._left, self._top, self._right, self._bottom = left, top, right, bottom

    def left(self):
        return self._left

    def top(self):
        return self._top

    def right(self):
        return self._right

    def bottom(self):
        return self._bottom


class FaceAwareFakeMatcher(FakeFaceMatcher):
    def __init__(self, result, rects):
        super().__init__(result)
        self.rects = rects

    def detect_faces(self, image):
        return self.rects

    def encode_from_rect(self, image, rect):
        return [1.0]


def make_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.detectors.intrusion.SessionLocal", Session)
    return Session


def seed_reserved_seat(Session, member_id=1001, stay_time=0):
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
                y_stay_time=stay_time,
            )
        )
        session.add(Member(member_id=member_id, name="Reserved Student", feature="[1.0]"))
        session.add(SeatReservation(region_id=10, member_id=member_id, enabled=True))
        session.commit()
    finally:
        session.close()


def detect_twice(plugin, image, ts=1.0):
    plugin.detect(Frame(image=image, ts=ts, camera_id=0, frame_idx=1))
    return plugin.detect(Frame(image=image, ts=ts + 1, camera_id=0, frame_idx=2))


def test_reserved_member_entering_seat_does_not_alarm(monkeypatch):
    Session = make_session(monkeypatch)
    seed_reserved_seat(Session)
    plugin = IntrusionPlugin(FakePersonDetector(), FakeFaceMatcher("member:1001"))
    plugin.setup()

    assert detect_twice(plugin, np.zeros((120, 120, 3), dtype=np.uint8)) == []


def test_known_non_reserved_member_raises_occupy(monkeypatch):
    Session = make_session(monkeypatch)
    seed_reserved_seat(Session)
    plugin = IntrusionPlugin(FakePersonDetector(), FakeFaceMatcher("member:2002"))
    plugin.setup()

    events = detect_twice(plugin, np.zeros((120, 120, 3), dtype=np.uint8))

    assert len(events) == 1
    event = events[0]
    assert event.type == "occupy"
    assert event.region_id == 10
    assert event.face_match == "member:2002"
    assert event.extra["reserved_member_id"] == 1001
    assert event.extra["reserved_member_name"] == "Reserved Student"
    assert event.extra["kind"] == "unauthorized_seat"
    assert event.extra["track_key"] == "seat-10-track-1"


def test_stranger_entering_reserved_seat_raises_occupy(monkeypatch):
    Session = make_session(monkeypatch)
    seed_reserved_seat(Session)
    plugin = IntrusionPlugin(FakePersonDetector(), FakeFaceMatcher("stranger"))
    plugin.setup()

    events = detect_twice(plugin, np.zeros((120, 120, 3), dtype=np.uint8))

    assert len(events) == 1
    assert events[0].face_match == "stranger"
    assert events[0].extra["actual_face_match"] == "stranger"


def test_normalized_reserved_seat_uses_actual_stream_resolution(monkeypatch):
    """A 1280x720 OBS frame must not use the old fixed 640x480 polygon."""
    Session = make_session(monkeypatch)
    session = Session()
    session.add(Camera(id=0, name="cam", stream_url="rtmp://example/live/test"))
    session.add(
        Region(
            id=10,
            camera_id=0,
            name="seat-10",
            type="seat",
            polygon="[[0.3,0.1],[0.6,0.1],[0.6,0.9],[0.3,0.9]]",
            x_distance=0,
            y_stay_time=0,
        )
    )
    session.add(Member(member_id=1001, name="Reserved Student", feature="[1.0]"))
    session.add(SeatReservation(region_id=10, member_id=1001, enabled=True))
    session.commit()
    session.close()

    # Bottom center is (550, 600), inside the normalized seat on 1280x720.
    detector = FakePersonDetector([(400, 100, 700, 600)])
    plugin = IntrusionPlugin(detector, FakeFaceMatcher("stranger"))
    plugin.setup()

    events = detect_twice(plugin, np.zeros((720, 1280, 3), dtype=np.uint8))

    assert len(events) == 1
    assert events[0].type == "occupy"


def test_seated_face_in_seat_triggers_when_person_bottom_is_outside(monkeypatch):
    Session = make_session(monkeypatch)
    seed_reserved_seat(Session)
    # The body extends below the desk polygon, while the visible face is inside it.
    detector = FakePersonDetector([(20, 30, 80, 118)])
    matcher = FaceAwareFakeMatcher("stranger", [FakeRect(40, 30, 60, 60)])
    plugin = IntrusionPlugin(detector, matcher)
    plugin.setup()

    events = detect_twice(plugin, np.zeros((120, 120, 3), dtype=np.uint8))

    assert len(events) == 1
    assert events[0].type == "occupy"


def test_owner_and_stranger_are_evaluated_independently(monkeypatch):
    Session = make_session(monkeypatch)
    seed_reserved_seat(Session)
    detector = FakePersonDetector([(5, 10, 40, 80), (55, 10, 95, 80)])
    plugin = IntrusionPlugin(detector, FakeFaceMatcher(["member:1001", "stranger"]))
    plugin.setup()

    events = detect_twice(plugin, np.zeros((120, 120, 3), dtype=np.uint8))

    assert len(events) == 1
    assert events[0].face_match == "stranger"
    assert events[0].extra["track_key"] == "seat-10-track-2"


def test_exit_resets_timer_before_reentry(monkeypatch):
    Session = make_session(monkeypatch)
    seed_reserved_seat(Session, stay_time=3)
    detector = FakePersonDetector([(20, 10, 80, 80)])
    plugin = IntrusionPlugin(detector, FakeFaceMatcher("stranger"))
    plugin.setup()
    image = np.zeros((120, 120, 3), dtype=np.uint8)

    assert plugin.detect(Frame(image=image, ts=0, camera_id=0, frame_idx=1)) == []
    detector.boxes = [(150, 10, 210, 80)]
    assert plugin.detect(Frame(image=image, ts=2, camera_id=0, frame_idx=2)) == []
    detector.boxes = [(20, 10, 80, 80)]
    assert plugin.detect(Frame(image=image, ts=3, camera_id=0, frame_idx=3)) == []
    assert plugin.detect(Frame(image=image, ts=5, camera_id=0, frame_idx=4)) == []
    events = plugin.detect(Frame(image=image, ts=6, camera_id=0, frame_idx=5))
    assert len(events) == 1


def test_binding_hot_reload_and_unbind_stop_identity_checks(monkeypatch):
    Session = make_session(monkeypatch)
    session = Session()
    session.add(Camera(id=0, name="cam", stream_url="rtmp://example/live/test"))
    session.add(Region(id=10, camera_id=0, name="seat-10", type="seat", polygon="[[0,0],[100,0],[100,100],[0,100]]", x_distance=0, y_stay_time=0))
    session.add(Member(member_id=1001, name="Reserved Student", feature="[1.0]"))
    session.commit()
    session.close()

    plugin = IntrusionPlugin(FakePersonDetector(), FakeFaceMatcher("stranger"))
    plugin.setup()
    image = np.zeros((120, 120, 3), dtype=np.uint8)
    assert detect_twice(plugin, image) == []

    session = Session()
    session.add(SeatReservation(region_id=10, member_id=1001, enabled=True))
    session.commit()
    session.close()
    plugin.on_config_changed({})
    assert len(detect_twice(plugin, image, ts=10)) == 1

    session = Session()
    session.query(SeatReservation).delete()
    session.commit()
    session.close()
    plugin.on_config_changed({})
    assert detect_twice(plugin, image, ts=20) == []
