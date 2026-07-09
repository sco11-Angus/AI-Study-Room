"""Fatigue detection with Dlib 68-point landmarks (SDD section 4.3).

The detector is active only for seats whose status is ``studying``. Fatigue
events are level-0 private reminders and must not trigger public alarms.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..config import Config
from .base import AlarmEvent, Detector, Frame

logger = logging.getLogger(__name__)


def eye_aspect_ratio(eye) -> float:
    """EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)."""
    eye = np.asarray(eye, dtype=np.float32)
    a = np.linalg.norm(eye[1] - eye[5])
    b = np.linalg.norm(eye[2] - eye[4])
    c = np.linalg.norm(eye[0] - eye[3])
    if c == 0:
        return 0.0
    return float((a + b) / (2.0 * c))


def mouth_aspect_ratio(mouth) -> float:
    """MAR for the inner-mouth 8-point slice, landmarks 60-67."""
    mouth = np.asarray(mouth, dtype=np.float32)
    if len(mouth) < 8:
        raise ValueError("mouth_aspect_ratio expects landmarks 60-67")
    a = np.linalg.norm(mouth[2] - mouth[6])
    b = np.linalg.norm(mouth[3] - mouth[5])
    c = np.linalg.norm(mouth[0] - mouth[4])
    if c == 0:
        return 0.0
    return float((a + b) / (2.0 * c))


def _default_session_factory():
    from ..models.database import SessionLocal

    return SessionLocal()


class FatigueDetector:
    """Per-seat EAR/MAR state machine."""

    def __init__(
        self,
        ear_thresh: float | None = None,
        ear_duration: float | None = None,
        mar_thresh: float | None = None,
    ):
        self.ear_thresh = Config.EAR_THRESH if ear_thresh is None else ear_thresh
        self.ear_duration = Config.EAR_DURATION if ear_duration is None else ear_duration
        self.mar_thresh = Config.MAR_THRESH if mar_thresh is None else mar_thresh
        self._closed_since: float | None = None

    def reset(self) -> None:
        """Clear accumulated closed-eye state."""
        self._closed_since = None

    def detect(self, landmarks, ts: float) -> str | None:
        """Return ``sleepy``, ``yawn``, or ``None`` for one landmark set."""
        if landmarks is None:
            self.reset()
            return None

        points = np.asarray(landmarks, dtype=np.float32)
        if points.shape[0] < 68:
            self.reset()
            return None

        left_ear = eye_aspect_ratio(points[36:42])
        right_ear = eye_aspect_ratio(points[42:48])
        ear = (left_ear + right_ear) / 2.0
        mar = mouth_aspect_ratio(points[60:68])

        if mar > self.mar_thresh:
            self.reset()
            return "yawn"

        if ear < self.ear_thresh:
            if self._closed_since is None:
                self._closed_since = ts
                if self.ear_duration <= 0:
                    return "sleepy"
                return None
            if ts - self._closed_since >= self.ear_duration:
                return "sleepy"
            return None

        self.reset()
        return None


@dataclass
class ActiveSeat:
    region_id: int
    user_id: int
    camera_id: int
    polygon: list[list[float]]


class FatiguePlugin(Detector):
    """Detector plugin that emits private fatigue reminders for active seats."""

    name = "fatigue"
    enabled = False

    def __init__(
        self,
        session_factory: Callable | None = None,
        detector_factory: Callable[[], FatigueDetector] = FatigueDetector,
        shape_predictor_path: str | None = None,
        face_detector=None,
        shape_predictor=None,
    ):
        self._session_factory = session_factory or _default_session_factory
        self._detector_factory = detector_factory
        self._shape_predictor_path = shape_predictor_path or os.path.join(
            Config.MODEL_DIR,
            "shape_predictor_68_face_landmarks.dat",
        )
        self._face_detector = face_detector
        self._shape_predictor = shape_predictor
        self._dlib_loaded = bool(face_detector and shape_predictor)
        self._active_seats: dict[int, ActiveSeat] = {}
        self._detectors: dict[int, FatigueDetector] = {}

    def setup(self) -> None:
        """Load Dlib models once and then active studying seats."""
        if not self._dlib_loaded:
            self._load_dlib()
        self._reload_active_seats()
        self.enabled = bool(self._active_seats)
        logger.info("[fatigue] active studying seats: %s", sorted(self._active_seats))

    def detect(self, frame: Frame) -> list[AlarmEvent]:
        """Run fatigue detection for studying seats on the frame camera."""
        if not self._dlib_loaded or not self._active_seats:
            return []

        seats = [
            seat for seat in self._active_seats.values()
            if seat.camera_id in (None, frame.camera_id)
        ]
        if not seats:
            return []

        landmarks_by_seat = self._extract_landmarks(frame.image, seats)
        events: list[AlarmEvent] = []
        for seat in seats:
            detector = self._detectors.setdefault(seat.region_id, self._detector_factory())
            landmarks = landmarks_by_seat.get(seat.region_id)
            kind = detector.detect(landmarks, frame.ts)
            if not kind:
                continue
            events.append(
                AlarmEvent(
                    type="fatigue",
                    region_id=seat.region_id,
                    camera_id=frame.camera_id,
                    ts=frame.ts,
                    level=0,
                    confidence=1.0,
                    snapshot=frame.image,
                    extra={
                        "kind": kind,
                        "user_id": seat.user_id,
                        "level": 0,
                    },
                )
            )
        return events

    def on_config_changed(self, cfg: dict) -> None:
        """Hot update one seat or reload all studying seats."""
        region_id = cfg.get("region_id")
        status = cfg.get("status")

        if region_id is None:
            self._reload_active_seats()
            self.enabled = bool(self._active_seats)
            return

        region_id = int(region_id)
        if status == "studying":
            seat = self._load_active_seat(region_id)
            if seat:
                self._active_seats[region_id] = seat
                self._detectors.setdefault(region_id, self._detector_factory())
        else:
            self._active_seats.pop(region_id, None)
            detector = self._detectors.pop(region_id, None)
            if detector:
                detector.reset()

        self.enabled = bool(self._active_seats)

    def _load_dlib(self) -> None:
        if not os.path.exists(self._shape_predictor_path):
            raise FileNotFoundError(
                "Missing Dlib landmark model: "
                f"{self._shape_predictor_path}. Place shape_predictor_68_face_landmarks.dat "
                "under backend/model_weights or set MODEL_DIR."
            )
        import dlib

        self._face_detector = dlib.get_frontal_face_detector()
        self._shape_predictor = dlib.shape_predictor(self._shape_predictor_path)
        self._dlib_loaded = True

    def _reload_active_seats(self) -> None:
        from ..models.entities import Region, SeatStatus

        session = self._session_factory()
        try:
            rows = (
                session.query(SeatStatus, Region)
                .join(Region, SeatStatus.region_id == Region.id)
                .filter(SeatStatus.status == "studying")
                .all()
            )
            seats: dict[int, ActiveSeat] = {}
            for seat_status, region in rows:
                seat = self._seat_from_models(seat_status, region)
                if seat:
                    seats[seat.region_id] = seat
            disabled = set(self._active_seats) - set(seats)
            for region_id in disabled:
                detector = self._detectors.pop(region_id, None)
                if detector:
                    detector.reset()
            self._active_seats = seats
            for region_id in seats:
                self._detectors.setdefault(region_id, self._detector_factory())
        finally:
            session.close()

    def _load_active_seat(self, region_id: int) -> ActiveSeat | None:
        from ..models.entities import Region, SeatStatus

        session = self._session_factory()
        try:
            row = (
                session.query(SeatStatus, Region)
                .join(Region, SeatStatus.region_id == Region.id)
                .filter(SeatStatus.region_id == region_id, SeatStatus.status == "studying")
                .first()
            )
            if not row:
                return None
            return self._seat_from_models(row[0], row[1])
        finally:
            session.close()

    def _seat_from_models(self, seat_status, region) -> ActiveSeat | None:
        try:
            polygon = json.loads(region.polygon or "[]")
        except json.JSONDecodeError:
            logger.warning("[fatigue] invalid polygon for region_id=%s", region.id)
            return None
        if not polygon:
            return None
        return ActiveSeat(
            region_id=int(region.id),
            user_id=int(seat_status.user_id),
            camera_id=int(region.camera_id or 0),
            polygon=polygon,
        )

    def _extract_landmarks(self, image: np.ndarray, seats: list[ActiveSeat]) -> dict[int, np.ndarray]:
        rgb = image[..., ::-1].copy()
        faces = list(self._face_detector(rgb, 1))
        if not faces:
            for seat in seats:
                detector = self._detectors.get(seat.region_id)
                if detector:
                    detector.reset()
            return {}

        result: dict[int, np.ndarray] = {}
        for seat in seats:
            face = self._select_face_for_seat(faces, seat)
            if face is None:
                detector = self._detectors.get(seat.region_id)
                if detector:
                    detector.reset()
                continue
            shape = self._shape_predictor(rgb, face)
            result[seat.region_id] = np.array(
                [(shape.part(i).x, shape.part(i).y) for i in range(68)],
                dtype=np.float32,
            )
        return result

    def _select_face_for_seat(self, faces, seat: ActiveSeat):
        inside = []
        polygon = np.asarray(seat.polygon, dtype=np.float32)
        for face in faces:
            cx = (face.left() + face.right()) / 2.0
            cy = (face.top() + face.bottom()) / 2.0
            if _point_in_polygon((cx, cy), polygon):
                inside.append(face)
        candidates = inside or faces
        return max(candidates, key=lambda rect: max(0, rect.width()) * max(0, rect.height()))


def _point_in_polygon(point: tuple[float, float], polygon: np.ndarray) -> bool:
    """Ray-casting point-in-polygon check without requiring cv2 in unit tests."""
    x, y = point
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y)
        if intersects:
            x_on_edge = (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            if x < x_on_edge:
                inside = not inside
        j = i
    return inside
