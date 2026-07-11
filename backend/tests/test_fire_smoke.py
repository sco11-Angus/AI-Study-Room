"""Fire/smoke detector unit tests for task C3."""
import os
import sys
import types
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config
from app.detectors.base import Frame
from app.detectors.fire_smoke import FireSmokeDetector, FireSmokePlugin


class _FakeBoxes:
    def __init__(self, conf, cls):
        self.conf = conf
        self.cls = cls


class _FakeResult:
    names = {0: "person", 1: "fire", 2: "smoke"}

    def __init__(self, conf, cls):
        self.boxes = _FakeBoxes(conf, cls)


class _FakeModel:
    names = _FakeResult.names

    def __init__(self, conf=0.9, cls=1):
        self.conf = conf
        self.cls = cls

    def __call__(self, image, **kwargs):
        return [_FakeResult([self.conf], [self.cls])]


def _frame(idx: int = 0):
    return Frame(
        image=np.zeros((8, 8, 3), dtype=np.uint8),
        ts=float(idx),
        camera_id=3,
        frame_idx=idx,
    )


def test_feed_requires_full_window_before_alarm():
    detector = FireSmokeDetector()
    for _ in range(Config.FIRE_WINDOW - 1):
        assert detector.feed(0.95) is False
    assert detector.feed(0.95) is True


def test_feed_rejects_single_high_confidence_flash():
    detector = FireSmokeDetector()
    assert detector.feed(1.0) is False
    for _ in range(Config.FIRE_WINDOW - 1):
        assert detector.feed(0.0) is False


def test_plugin_emits_fire_smoke_alarm_after_sustained_fire():
    plugin = FireSmokePlugin(region_id=7, model=_FakeModel(conf=0.9, cls=1))
    plugin.setup()

    events = []
    for idx in range(Config.FIRE_WINDOW):
        events.extend(plugin.detect(_frame(idx)))

    assert len(events) == 1
    evt = events[0]
    assert evt.type == "fire_smoke"
    assert evt.region_id == 7
    assert evt.camera_id == 3
    assert abs(evt.confidence - 0.9) < 1e-6
    assert evt.snapshot is not None
    assert evt.extra["detected_class"] == "fire"
    assert evt.extra["avg_conf"] > Config.FIRE_CONF
    assert evt.extra["window"] == Config.FIRE_WINDOW


def test_plugin_accepts_smoke_class():
    plugin = FireSmokePlugin(region_id=8, model=_FakeModel(conf=0.8, cls=2))
    plugin.setup()

    events = []
    for idx in range(Config.FIRE_WINDOW):
        events.extend(plugin.detect(_frame(idx)))

    assert len(events) == 1
    assert events[0].extra["detected_class"] == "smoke"


def test_plugin_ignores_non_fire_smoke_classes():
    plugin = FireSmokePlugin(region_id=7, model=_FakeModel(conf=0.99, cls=0))
    plugin.setup()

    events = []
    for idx in range(Config.FIRE_WINDOW + 1):
        events.extend(plugin.detect(_frame(idx)))

    assert events == []


def test_setup_rejects_empty_weight_file():
    with TemporaryDirectory() as tmp_dir:
        empty_weights = os.path.join(tmp_dir, "fire_smoke.pt")
        open(empty_weights, "w", encoding="utf-8").close()

        plugin = FireSmokePlugin(weights_path=empty_weights)
        try:
            plugin.setup()
        except RuntimeError as exc:
            assert "model weights file is empty" in str(exc)
        else:
            raise AssertionError("empty fire_smoke.pt should be rejected")


def test_setup_uses_legacy_yolov5_by_default():
    with TemporaryDirectory() as tmp_dir:
        weights = os.path.join(tmp_dir, "fire_smoke.pt")
        with open(weights, "wb") as fh:
            fh.write(b"legacy-yolov5")

        plugin = FireSmokePlugin(weights_path=weights)
        legacy_model = _FakeModel(conf=0.7, cls=1)
        with patch.object(Config, "FIRE_SMOKE_MODEL_LOADER", "legacy"):
            with patch.object(plugin, "_load_legacy_yolov5", return_value=legacy_model) as load_legacy:
                plugin.setup()

        load_legacy.assert_called_once()
        assert plugin._model is legacy_model


def test_setup_can_fall_back_from_ultralytics_to_legacy():
    with TemporaryDirectory() as tmp_dir:
        weights = os.path.join(tmp_dir, "fire_smoke.pt")
        with open(weights, "wb") as fh:
            fh.write(b"legacy-yolov5")

        def fail_load(_path):
            raise TypeError("old checkpoint")

        plugin = FireSmokePlugin(weights_path=weights)
        legacy_model = _FakeModel(conf=0.7, cls=1)
        fake_ultralytics = types.SimpleNamespace(YOLO=fail_load)
        with patch.object(Config, "FIRE_SMOKE_MODEL_LOADER", "ultralytics"):
            with patch.dict(sys.modules, {"ultralytics": fake_ultralytics}):
                with patch.object(plugin, "_load_legacy_yolov5", return_value=legacy_model) as load_legacy:
                    plugin.setup()

        load_legacy.assert_called_once()
        assert plugin._model is legacy_model


if __name__ == "__main__":
    test_feed_requires_full_window_before_alarm()
    test_feed_rejects_single_high_confidence_flash()
    test_plugin_emits_fire_smoke_alarm_after_sustained_fire()
    test_plugin_accepts_smoke_class()
    test_plugin_ignores_non_fire_smoke_classes()
    test_setup_rejects_empty_weight_file()
    test_setup_uses_legacy_yolov5_by_default()
    test_setup_can_fall_back_from_ultralytics_to_legacy()
