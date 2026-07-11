"""Backend service facade for the fire/smoke detector."""
from __future__ import annotations

import time
from threading import Lock
from typing import Any

import numpy as np

from ..config import Config
from ..detectors.base import Frame
from ..detectors.fire_smoke import FireSmokePlugin
from .alarm import get_alarm_service

_plugin: FireSmokePlugin | None = None
_lock = Lock()


def get_fire_smoke_plugin() -> FireSmokePlugin:
    global _plugin
    if _plugin is None:
        _plugin = FireSmokePlugin()
        _plugin.setup()
    return _plugin


def detect_fire_smoke_image(
    image: np.ndarray,
    *,
    camera_id: int = 0,
    region_id: int | None = None,
    frames: int = 1,
    raise_alarm: bool = False,
) -> dict[str, Any]:
    """Run the grafted fire/smoke model from a backend API request."""
    if image is None:
        raise ValueError("image is required")
    if frames <= 0:
        raise ValueError("frames must be positive")

    with _lock:
        plugin = get_fire_smoke_plugin()
        plugin.region_id = Config.FIRE_SMOKE_REGION_ID if region_id is None else region_id
        plugin.reset_window()

        detections = plugin.raw_detections(image)
        events = []
        for idx in range(frames):
            events.extend(
                plugin.detect(
                    Frame(
                        image=image,
                        ts=time.time(),
                        camera_id=camera_id,
                        frame_idx=idx,
                    )
                )
            )

        alarms = []
        if raise_alarm:
            svc = get_alarm_service()
            for event in events:
                payload = svc.raise_alarm(event, frame=image)
                if payload is not None:
                    alarms.append(payload)

        return {
            "detections": detections,
            "events": [event.to_dict() for event in events],
            "alarms": alarms,
            "frames": frames,
            "window": Config.FIRE_WINDOW,
            "threshold": Config.FIRE_CONF,
        }
