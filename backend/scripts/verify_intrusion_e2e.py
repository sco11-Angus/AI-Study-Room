"""Verify region configuration -> intrusion detection -> alarm persistence."""
from __future__ import annotations

import json
import time

import numpy as np

from app.detectors.base import Frame
from app.detectors.intrusion import IntrusionPlugin
from app.models.database import SessionLocal
from app.models.entities import AlarmEvent, Region
from app.services.alarm import AlarmService


class FakePersonDetector:
    def setup(self) -> None:
        pass

    def detect_people(self, image) -> list[tuple[float, float, float, float]]:
        return [(200.0, 40.0, 360.0, 260.0)]


def main() -> None:
    session = SessionLocal()
    try:
        region = (
            session.query(Region)
            .filter(Region.camera_id == 0, Region.type == "danger_zone")
            .order_by(Region.id.desc())
            .first()
        )
        if region is None:
            raise RuntimeError("no danger_zone region found for camera_id=0")
        region_id = int(region.id)
    finally:
        session.close()

    plugin = IntrusionPlugin(person_detector=FakePersonDetector())
    plugin.setup()

    frame_img = np.zeros((360, 640, 3), dtype=np.uint8)
    first = Frame(image=frame_img, ts=time.time(), camera_id=0, frame_idx=1)
    second = Frame(image=frame_img, ts=first.ts + 1.0, camera_id=0, frame_idx=2)

    plugin.detect(first)
    events = plugin.detect(second)
    intrusion_events = [evt for evt in events if evt.type == "intrusion" and evt.region_id == region_id]
    if not intrusion_events:
        raise RuntimeError(f"intrusion event not produced for region_id={region_id}")

    service = AlarmService(cooldown=0)
    payload = service.raise_alarm(intrusion_events[0], frame=frame_img)
    if not payload:
        raise RuntimeError("alarm payload was not persisted")

    session = SessionLocal()
    try:
        record = session.get(AlarmEvent, int(payload["id"]))
        if record is None:
            raise RuntimeError(f"alarm id={payload['id']} not found")
        result = {
            "region_id": region_id,
            "alarm_id": record.id,
            "alarm_type": record.type,
            "camera_id": record.camera_id,
            "status": record.status,
            "snapshot_url": record.snapshot_url,
            "extra": json.loads(record.extra or "{}"),
        }
    finally:
        session.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
