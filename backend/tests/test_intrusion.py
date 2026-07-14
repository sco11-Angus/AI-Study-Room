"""Temporal debounce and lifecycle tests for intrusion detection."""
import numpy as np

from app.detectors.base import AlarmEvent, Detector, Frame
from app.detectors.intrusion import IntrusionDetector, IntrusionPlugin
from app.stream.engine import InferenceEngine, SharedPersonContext

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


class _FakePersonDetector:
    """Stub YOLO wrapper — returns fixed boxes without loading a model."""

    def __init__(self, boxes):
        self._boxes = list(boxes)

    def setup(self):
        pass

    def detect_people(self, image):
        return list(self._boxes)


def test_person_boxes_written_to_shared_ctx_without_regions():
    """方案B：即使摄像头未配置防区/座位，YOLO 人员框也应写入共享上下文，
    供打架检测复用（人员框只算一次）。"""
    ctx = SharedPersonContext()
    boxes = [(10.0, 20.0, 30.0, 80.0), (100.0, 40.0, 140.0, 120.0)]
    plugin = IntrusionPlugin(
        person_detector=_FakePersonDetector(boxes),
        face_matcher=object(),
        shared_ctx=ctx,
    )
    # 不调用 setup()（避免加载 DB/权重）；无防区、无座位。
    plugin._regions = {}
    plugin._seats = {}

    frame = Frame(np.zeros((4, 4, 3)), ts=1.0, camera_id=6, frame_idx=42)
    events = plugin.detect(frame)

    assert events == []  # 无防区可判定，无告警
    assert ctx.get_person_boxes(6, 42) == boxes  # 但人员框已写入共享上下文


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
