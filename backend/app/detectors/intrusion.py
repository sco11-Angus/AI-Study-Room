"""Danger-zone intrusion detection: YOLO person boxes + geometric debounce."""
import json
import logging
import os
import time
from dataclasses import dataclass

import cv2
import numpy as np

from ..config import Config
from ..models.database import SessionLocal
from ..models.entities import Region, SeatStatus
from .face import FaceMatcher
from .base import AlarmEvent, Detector, Frame

logger = logging.getLogger(__name__)

Box = tuple[float, float, float, float]


class IntrusionDetector:
    """Per-region danger timer using bottom-center person point."""

    def __init__(self, polygon: list, x_distance: int, y_stay_time: int):
        self.polygon = np.array(polygon, dtype=np.int32)
        self.x_distance = x_distance
        self.y_stay_time = y_stay_time
        self._danger_since = None

    @staticmethod
    def base_point(box) -> tuple[int, int]:
        x1, _y1, x2, y2 = box
        return int((x1 + x2) / 2), int(y2)

    def judge(self, box, ts: float) -> bool:
        cx, cy = self.base_point(box)
        d = cv2.pointPolygonTest(self.polygon, (cx, cy), True)

        in_danger = d >= 0 or (d < 0 and abs(d) <= self.x_distance)
        if in_danger:
            if self._danger_since is None:
                self._danger_since = ts
            elif ts - self._danger_since >= self.y_stay_time:
                return True
        else:
            self._danger_since = None
        return False


class PersonDetector:
    """Thin YOLOv8 person detector wrapper."""

    def __init__(self, model_path: str | None = None, conf_threshold: float = 0.35):
        self.model_path = model_path or os.path.join(Config.MODEL_DIR, "yolov8n.pt")
        self.conf_threshold = conf_threshold
        self._model = None

    def setup(self) -> None:
        if self._model is not None:
            return
        from ultralytics import YOLO

        self._model = YOLO(self.model_path)

    def detect_people(self, image: np.ndarray) -> list[Box]:
        if self._model is None:
            self.setup()
        results = self._model(image, verbose=False)
        boxes: list[Box] = []
        for result in results:
            for box in getattr(result, "boxes", []) or []:
                cls = int(box.cls[0].item() if hasattr(box.cls[0], "item") else box.cls[0])
                conf = float(box.conf[0].item() if hasattr(box.conf[0], "item") else box.conf[0])
                if cls != 0 or conf <= self.conf_threshold:
                    continue
                xyxy = box.xyxy[0].tolist()
                boxes.append(tuple(float(v) for v in xyxy))
        return boxes


@dataclass
class RegionRuntime:
    id: int
    camera_id: int
    name: str
    detector: IntrusionDetector


@dataclass
class SeatRuntime:
    id: int
    camera_id: int
    name: str
    user_id: int
    detector: IntrusionDetector


class IntrusionPlugin(Detector):
    name = "intrusion"
    enabled = True

    def __init__(
        self,
        person_detector: PersonDetector | None = None,
        face_matcher: FaceMatcher | None = None,
        shared_ctx=None,
    ):
        self.person_detector = person_detector or PersonDetector()
        self.face_matcher = face_matcher or FaceMatcher()
        self.shared_ctx = shared_ctx
        self._regions: dict[int, RegionRuntime] = {}
        self._seats: dict[int, SeatRuntime] = {}

    def setup(self) -> None:
        self.person_detector.setup()
        self._reload_regions()

    def _reload_regions(self) -> None:
        session = SessionLocal()
        try:
            rows = (
                session.query(Region)
                .filter(Region.type == "danger_zone")
                .order_by(Region.id.asc())
                .all()
            )
            runtimes: dict[int, RegionRuntime] = {}
            for row in rows:
                try:
                    polygon = json.loads(row.polygon or "[]")
                    if len(polygon) < 3:
                        continue
                    runtimes[int(row.id)] = RegionRuntime(
                        id=int(row.id),
                        camera_id=int(row.camera_id or 0),
                        name=row.name or f"region-{row.id}",
                        detector=IntrusionDetector(
                            polygon=polygon,
                            x_distance=int(row.x_distance or 0),
                            y_stay_time=int(row.y_stay_time or 0),
                        ),
                    )
                except Exception:
                    logger.exception("[intrusion] invalid region skipped id=%s", row.id)
            self._regions = runtimes
            self._seats = self._load_active_seats(session)
            logger.info("[intrusion] active danger zones: %s", sorted(self._regions))
            logger.info("[intrusion] active reserved seats: %s", sorted(self._seats))
        finally:
            session.close()

    def _load_active_seats(self, session) -> dict[int, SeatRuntime]:
        rows = (
            session.query(SeatStatus, Region)
            .join(Region, SeatStatus.region_id == Region.id)
            .filter(SeatStatus.status == "studying", Region.type == "seat")
            .all()
        )
        seats: dict[int, SeatRuntime] = {}
        for status, region in rows:
            try:
                polygon = json.loads(region.polygon or "[]")
                if len(polygon) < 3 or status.user_id is None:
                    continue
                seats[int(region.id)] = SeatRuntime(
                    id=int(region.id),
                    camera_id=int(region.camera_id or 0),
                    name=region.name or f"seat-{region.id}",
                    user_id=int(status.user_id),
                    detector=IntrusionDetector(
                        polygon=polygon,
                        x_distance=int(region.x_distance or 0),
                        y_stay_time=int(region.y_stay_time or 0),
                    ),
                )
            except Exception:
                logger.exception("[intrusion] invalid active seat skipped id=%s", region.id)
        return seats

    def detect(self, frame: Frame) -> list[AlarmEvent]:
        regions = [r for r in self._regions.values() if r.camera_id == frame.camera_id]
        seats = [s for s in self._seats.values() if s.camera_id == frame.camera_id]
        if not regions and not seats:
            return []

        people = self.person_detector.detect_people(frame.image)
        if self.shared_ctx is not None:
            self.shared_ctx.set(frame.camera_id, frame.frame_idx, people)

        events: list[AlarmEvent] = []
        ts = frame.ts or time.time()
        for region in regions:
            for box in people:
                if region.detector.judge(box, ts):
                    events.append(
                        AlarmEvent(
                            type="intrusion",
                            region_id=region.id,
                            camera_id=frame.camera_id,
                            ts=ts,
                            level=1,
                            extra={
                                "region_name": region.name,
                                "person_box": [round(float(v), 2) for v in box],
                            },
                        )
                    )
                    break
        for seat in seats:
            for box in people:
                if not seat.detector.judge(box, ts):
                    continue
                face_match, face_crop = self._match_person(frame.image, box)
                expected = f"member:{seat.user_id}"
                if face_match == expected:
                    break
                events.append(
                    AlarmEvent(
                        type="occupy",
                        region_id=seat.id,
                        camera_id=frame.camera_id,
                        ts=ts,
                        level=1,
                        face_match=face_match,
                        face_crop=face_crop,
                        extra={
                            "kind": "unauthorized_seat",
                            "seat_name": seat.name,
                            "expected_user_id": seat.user_id,
                            "actual_face_match": face_match,
                            "person_box": [round(float(v), 2) for v in box],
                        },
                    )
                )
                break
        return events

    def _match_person(self, image: np.ndarray, box: Box) -> tuple[str, np.ndarray | None]:
        h, w = image.shape[:2]
        x1, y1, x2, y2 = [int(round(v)) for v in box]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        crop = image[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else None
        if crop is None:
            return "stranger", None
        feature = self.face_matcher.encode(crop)
        if feature is None:
            return "stranger", crop
        return self.face_matcher.match(feature), crop

    def on_config_changed(self, cfg: dict) -> None:
        self._reload_regions()
