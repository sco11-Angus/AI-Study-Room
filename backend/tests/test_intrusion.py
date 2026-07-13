"""Temporal debounce and lifecycle tests for intrusion detection."""
import numpy as np

from app.detectors.base import AlarmEvent, Detector, Frame
from app.detectors.intrusion import IntrusionDetector
from app.stream.engine import InferenceEngine

SQUARE = [[0, 0], [100, 0], [100, 100], [0, 100]]


def test_base_point_is_box_bottom_center():
    assert IntrusionDetector(SQUARE, 10, 5).base_point((10, 10, 30, 50)) == (20, 50)


def test_alarm_after_stay_time():
    det = IntrusionDetector(SQUARE, x_distance=10, y_stay_time=5)
    box = (40, 40, 60, 60)
    assert det.judge(box, ts=0) is False
    assert det.judge(box, ts=5) is True


def test_timer_resets_when_leaving():
    det = IntrusionDetector(SQUARE, x_distance=10, y_stay_time=5)
    inside = (40, 40, 60, 60)
    outside = (400, 400, 420, 420)
    det.judge(inside, ts=0)
    det.judge(outside, ts=2)
    assert det.judge(inside, ts=4) is False


class ClearOnlyDetector(Detector):
    name = "clear_only"

    def setup(self):
        pass

    def detect(self, frame):
        return [
            AlarmEvent(
                type="occupy",
                region_id=10,
                camera_id=frame.camera_id,
                extra={"lifecycle": "cleared", "track_key": "seat-10-track-1"},
            )
        ]


def test_clear_lifecycle_is_broadcast_without_persisting(monkeypatch):
    calls = []

    class FakeService:
        def raise_alarm(self, *args, **kwargs):
            raise AssertionError("clear lifecycle must not be persisted")

    monkeypatch.setattr("app.services.alarm.get_alarm_service", lambda: FakeService())
    monkeypatch.setattr("app.api.ws.broadcast_alarm", calls.append)

    engine = InferenceEngine()
    engine.register(ClearOnlyDetector())
    engine._dispatch_and_raise(Frame(np.zeros((4, 4, 3)), ts=1, camera_id=6, frame_idx=0))
    engine.shutdown()

    assert calls == [{
        "event": "region_state",
        "state": "cleared",
        "region_id": 10,
        "camera_id": 6,
        "alarm_type": "occupy",
        "track_key": "seat-10-track-1",
    }]
