from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Camera, Member, Region, SeatReservation


class FakeEngine:
    def __init__(self):
        self.changes = []

    def on_config_changed(self, name, cfg):
        self.changes.append((name, cfg))


class FakeScheduler:
    def __init__(self):
        self.engine = FakeEngine()


def make_client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    from app.api import members, seat_reservations

    monkeypatch.setattr(members, "SessionLocal", Session)
    monkeypatch.setattr(seat_reservations, "SessionLocal", Session)
    scheduler = FakeScheduler()
    monkeypatch.setattr(seat_reservations, "get_scheduler", lambda: scheduler)

    session = Session()
    session.add(Camera(id=1, name="cam", stream_url="rtmp://example/live/test"))
    session.add(Region(id=10, camera_id=1, name="A1", type="seat", polygon="[[0,0],[1,0],[1,1]]"))
    session.add(Region(id=11, camera_id=1, name="Danger", type="danger_zone", polygon="[[0,0],[1,0],[1,1]]"))
    session.add(Member(member_id=1001, name="Face Ready", feature="[1.0]"))
    session.add(Member(member_id=1002, name="No Face", feature=""))
    session.commit()
    session.close()

    app = Flask(__name__)
    app.register_blueprint(members.bp)
    app.register_blueprint(seat_reservations.bp)
    return app.test_client(), Session, scheduler


def test_members_filters_to_face_enrolled(monkeypatch):
    client, _Session, _scheduler = make_client(monkeypatch)

    response = client.get("/api/members?face_enrolled=true")

    assert response.status_code == 200
    assert response.get_json()["data"] == [{"member_id": 1001, "name": "Face Ready", "face_enrolled": True}]


def test_reservation_rejects_non_seat_and_member_without_feature(monkeypatch):
    client, _Session, _scheduler = make_client(monkeypatch)

    non_seat = client.put("/api/seat-reservations/11", json={"member_id": 1001})
    no_feature = client.put("/api/seat-reservations/10", json={"member_id": 1002})
    missing = client.put("/api/seat-reservations/999", json={"member_id": 1001})

    assert non_seat.status_code == 400
    assert no_feature.status_code == 400
    assert missing.status_code == 404


def test_reservation_upserts_lists_and_deletes_with_hot_reload(monkeypatch):
    client, Session, scheduler = make_client(monkeypatch)

    created = client.put("/api/seat-reservations/10", json={"member_id": 1001})
    assert created.status_code == 200
    assert created.get_json()["data"]["member_name"] == "Face Ready"
    assert scheduler.engine.changes == [("intrusion", {})]

    listed = client.get("/api/seat-reservations?camera_id=1")
    assert listed.status_code == 200
    assert listed.get_json()["data"][0]["region_id"] == 10

    session = Session()
    session.add(Member(member_id=1003, name="Second Face", feature="[2.0]"))
    session.commit()
    session.close()
    updated = client.put("/api/seat-reservations/10", json={"member_id": 1003})
    assert updated.status_code == 200
    assert updated.get_json()["data"]["member_id"] == 1003

    deleted = client.delete("/api/seat-reservations/10")
    assert deleted.status_code == 200
    assert len(scheduler.engine.changes) == 3

    session = Session()
    assert session.query(SeatReservation).count() == 0
    session.close()


def test_unauthorized_seat_alarm_description_names_reserved_member():
    from app.detectors.base import AlarmEvent
    from app.services.alarm import AlarmService

    message = AlarmService()._describe_alarm(AlarmEvent(
        type="occupy",
        region_id=10,
        extra={
            "kind": "unauthorized_seat",
            "seat_name": "A1",
            "reserved_member_name": "Face Ready",
            "actual_face_match": "stranger",
        },
    ))

    assert message == "非预约人员占用座位 A1（预约人：Face Ready，实际：陌生人员）"
