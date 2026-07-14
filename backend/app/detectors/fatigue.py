"""Dlib EAR/MAR fatigue detection scoped to explicit study sessions."""
from __future__ import annotations

import json
import logging
import os
from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..config import Config
from .base import AlarmEvent, Detector, Frame

logger = logging.getLogger(__name__)


@dataclass
class FatigueResult:
    kind: str
    ear: float
    mar: float
    closed_duration: float
    yawn_hits: int
    yawn_window: int

    def __eq__(self, other):
        return self.kind == other if isinstance(other, str) else super().__eq__(other)


def eye_aspect_ratio(eye) -> float:
    eye = np.asarray(eye, dtype=np.float32)
    a = np.linalg.norm(eye[1] - eye[5])
    b = np.linalg.norm(eye[2] - eye[4])
    c = np.linalg.norm(eye[0] - eye[3])
    return float((a + b) / (2.0 * c)) if c else 0.0


def mouth_aspect_ratio(mouth) -> float:
    mouth = np.asarray(mouth, dtype=np.float32)
    if len(mouth) < 8:
        raise ValueError("mouth_aspect_ratio expects landmarks 60-67")
    a = np.linalg.norm(mouth[2] - mouth[6])
    b = np.linalg.norm(mouth[3] - mouth[5])
    c = np.linalg.norm(mouth[0] - mouth[4])
    return float((a + b) / (2.0 * c)) if c else 0.0


def _default_session_factory():
    from ..models.database import SessionLocal
    return SessionLocal()


class FatigueDetector:
    """Per-seat EAR/MAR temporal state machine."""

    def __init__(self, ear_thresh=None, ear_duration=None, mar_thresh=None, yawn_window=None, yawn_hits=None):
        self.ear_thresh = Config.EAR_THRESH if ear_thresh is None else ear_thresh
        self.ear_duration = Config.EAR_DURATION if ear_duration is None else ear_duration
        self.mar_thresh = Config.MAR_THRESH if mar_thresh is None else mar_thresh
        self.yawn_window = max(1, int(Config.FATIGUE_YAWN_WINDOW if yawn_window is None else yawn_window))
        self.yawn_hits = max(1, int(Config.FATIGUE_YAWN_HITS if yawn_hits is None else yawn_hits))
        self._closed_since = None
        self._yawn_votes = deque(maxlen=self.yawn_window)
        self.last_metrics = self._metrics(0.0, 0.0, 0.0)

    def reset(self) -> None:
        self._closed_since = None
        self._yawn_votes.clear()
        self.last_metrics = self._metrics(0.0, 0.0, 0.0)

    def detect(self, landmarks, ts: float) -> FatigueResult | None:
        if landmarks is None:
            self.reset()
            return None
        points = np.asarray(landmarks, dtype=np.float32)
        if points.shape[0] < 68:
            self.reset()
            return None
        ear = (eye_aspect_ratio(points[36:42]) + eye_aspect_ratio(points[42:48])) / 2.0
        mar = mouth_aspect_ratio(points[60:68])
        self._yawn_votes.append(mar > self.mar_thresh)
        self.last_metrics = self._metrics(ear, mar, ts)
        if len(self._yawn_votes) >= self.yawn_hits and sum(self._yawn_votes) >= self.yawn_hits:
            self._closed_since = None
            result = FatigueResult(kind="yawn", **self.last_metrics)
            self._yawn_votes.clear()
            return result
        if ear < self.ear_thresh:
            if self._closed_since is None:
                self._closed_since = ts
                if self.ear_duration > 0:
                    return None
            if ts - self._closed_since >= self.ear_duration:
                self.last_metrics = self._metrics(ear, mar, ts)
                return FatigueResult(kind="sleepy", **self.last_metrics)
            return None
        self._closed_since = None
        self.last_metrics = self._metrics(ear, mar, ts)
        return None

    def _metrics(self, ear: float, mar: float, ts: float) -> dict:
        closed_duration = max(0.0, ts - self._closed_since) if self._closed_since is not None and ts else 0.0
        return {
            "ear": round(float(ear), 4), "mar": round(float(mar), 4),
            "closed_duration": round(float(closed_duration), 3),
            "yawn_hits": int(sum(self._yawn_votes)), "yawn_window": int(self.yawn_window),
        }


@dataclass
class ActiveSeat:
    region_id: int
    user_id: int
    camera_id: int
    polygon: list[list[float]]
    mode: str = "demo"
    member_id: int | None = None
    reservation_member_id: int | None = None


class FatiguePlugin(Detector):
    """Emit fatigue alarms only for an unambiguous eligible seat occupant."""

    name = "fatigue"
    enabled = False

    def __init__(self, session_factory: Callable | None = None, detector_factory=FatigueDetector,
                 shape_predictor_path: str | None = None, face_detector=None, shape_predictor=None,
                 face_matcher=None):
        self._session_factory = session_factory or _default_session_factory
        self._detector_factory = detector_factory
        self._shape_predictor_path = shape_predictor_path or os.path.join(Config.MODEL_DIR, "shape_predictor_68_face_landmarks.dat")
        self._face_detector = face_detector
        self._shape_predictor = shape_predictor
        self._face_matcher = face_matcher
        self._dlib_loaded = bool(face_detector and shape_predictor)
        self._active_seats: dict[int, ActiveSeat] = {}
        self._detectors: dict[int, FatigueDetector] = {}
        self._last_alert_at: dict[tuple[int, str], float] = {}
        self._runtime: dict[int, dict] = {}

    def setup(self) -> None:
        if not self._dlib_loaded:
            self._load_dlib()
        self._reload_active_seats()
        self.enabled = bool(self._active_seats)
        logger.info("[fatigue] active studying seats: %s", sorted(self._active_seats))

    def detect(self, frame: Frame) -> list[AlarmEvent]:
        if not self._dlib_loaded or not self._active_seats:
            return []
        seats = [seat for seat in self._active_seats.values() if seat.camera_id == frame.camera_id]
        if not seats:
            return []
        faces = list(self._face_detector(frame.image[..., ::-1].copy(), 1))
        events = []
        for seat in seats:
            detector = self._detectors.setdefault(seat.region_id, self._detector_factory())
            face, reason = self._select_single_in_seat_face(faces, seat, frame.image)
            if face is None:
                detector.reset()
                self._set_runtime(seat, eligible=False, reason=reason)
                continue
            identity_state, face_match = self._verify_identity(seat, frame.image, face)
            if seat.mode == "verified" and identity_state != "identity_verified":
                detector.reset()
                self._set_runtime(seat, eligible=False, reason=identity_state, face_match=face_match)
                continue
            rgb = frame.image[..., ::-1].copy()
            shape = self._shape_predictor(rgb, face)
            landmarks = np.array([(shape.part(i).x, shape.part(i).y) for i in range(68)], dtype=np.float32)
            self._set_runtime(seat, eligible=True, reason="detecting", face_match=face_match, identity_state=identity_state)
            result = detector.detect(landmarks, frame.ts)
            if not result or self._in_cooldown(seat.region_id, result.kind, frame.ts):
                continue
            self._last_alert_at[(seat.region_id, result.kind)] = frame.ts
            level = int(getattr(Config, "FATIGUE_ALERT_LEVEL", 1))
            events.append(AlarmEvent(
                type="fatigue", region_id=seat.region_id, camera_id=frame.camera_id,
                ts=frame.ts, level=level, confidence=1.0, snapshot=frame.image,
                extra={
                    "kind": result.kind, "user_id": seat.user_id, "member_id": seat.member_id,
                    "mode": seat.mode, "identity_state": identity_state, "presentation": "companion",
                    "level": level, "ear": result.ear, "mar": result.mar,
                    "closed_duration": result.closed_duration, "yawn_hits": result.yawn_hits,
                    "yawn_window": result.yawn_window,
                },
            ))
        return events

    def on_config_changed(self, cfg: dict) -> None:
        region_id = cfg.get("region_id")
        if region_id is not None and cfg.get("status") != "studying":
            region_id = int(region_id)
            detector = self._detectors.pop(region_id, None)
            if detector:
                detector.reset()
            self._active_seats.pop(region_id, None)
            self._runtime[region_id] = {"eligible": False, "reason": "not_studying"}
            self.enabled = bool(self._active_seats)
            return
        self._reload_active_seats()
        self.enabled = bool(self._active_seats)

    def get_runtime_state(self, region_id: int) -> dict:
        return dict(self._runtime.get(region_id, {"eligible": False, "reason": "not_studying"}))

    def _reload_active_seats(self) -> None:
        from ..models.entities import Region, SeatReservation, SeatStatus
        session = self._session_factory()
        try:
            rows = (session.query(SeatStatus, Region, SeatReservation)
                    .join(Region, SeatStatus.region_id == Region.id)
                    .outerjoin(SeatReservation, SeatReservation.region_id == Region.id)
                    .filter(SeatStatus.status == "studying", Region.type == "seat").all())
            seats = {}
            for row in rows:
                seat_status, region, reservation = (list(row) + [None] * 3)[:3]
                seat = self._seat_from_models(seat_status, region, reservation)
                if seat:
                    seats[seat.region_id] = seat
            for region_id in set(self._active_seats) - set(seats):
                self._detectors.pop(region_id, None)
                self._runtime.pop(region_id, None)
            self._active_seats = seats
            for region_id, seat in seats.items():
                self._detectors.setdefault(region_id, self._detector_factory())
                self._set_runtime(seat, eligible=False, reason="waiting_for_face")
        finally:
            session.close()

    def _seat_from_models(self, seat_status, region, reservation) -> ActiveSeat | None:
        try:
            polygon = json.loads(region.polygon or "[]")
        except json.JSONDecodeError:
            return None
        if len(polygon) < 3:
            return None
        mode = getattr(seat_status, "mode", None) or "demo"
        return ActiveSeat(
            region_id=int(region.id), user_id=int(seat_status.user_id), camera_id=int(region.camera_id),
            polygon=polygon, mode=mode, member_id=getattr(seat_status, "member_id", None),
            reservation_member_id=getattr(reservation, "member_id", None) if reservation else None,
        )

    def _select_single_in_seat_face(self, faces, seat: ActiveSeat, image: np.ndarray):
        polygon = np.asarray(_scale_polygon(seat.polygon, image.shape[1], image.shape[0]), dtype=np.float32)
        inside = [face for face in faces if _point_in_polygon(_face_center(face), polygon)]
        if not inside:
            return None, "no_in_seat_face"
        if len(inside) > 1:
            return None, "ambiguous_face"
        return inside[0], None

    def _verify_identity(self, seat: ActiveSeat, image: np.ndarray, face):
        if seat.mode != "verified":
            return "demo_ready", ""
        if seat.member_id is None or seat.member_id != seat.reservation_member_id:
            return "reservation_mismatch", ""
        matcher = self._face_matcher
        if matcher is None:
            from .face import FaceMatcher
            matcher = self._face_matcher = FaceMatcher()
        feature = matcher.encode_from_rect(image, face)
        face_match = matcher.match(feature) if feature is not None else "stranger"
        return ("identity_verified", face_match) if face_match == f"member:{seat.member_id}" else ("identity_mismatch", face_match)

    def _set_runtime(self, seat: ActiveSeat, *, eligible: bool, reason: str, face_match="", identity_state="") -> None:
        self._runtime[seat.region_id] = {
            "eligible": eligible, "reason": reason, "mode": seat.mode,
            "member_id": seat.member_id, "face_match": face_match,
            "identity_state": identity_state or ("demo_ready" if seat.mode == "demo" else reason),
        }

    def _in_cooldown(self, region_id: int, kind: str, ts: float) -> bool:
        last = self._last_alert_at.get((region_id, kind))
        return last is not None and ts - last < max(0.0, float(Config.FATIGUE_ALERT_COOLDOWN))

    def _load_dlib(self) -> None:
        if not os.path.exists(self._shape_predictor_path):
            raise FileNotFoundError(f"Missing Dlib landmark model: {self._shape_predictor_path}")
        import dlib
        self._face_detector = dlib.get_frontal_face_detector()
        self._shape_predictor = dlib.shape_predictor(self._shape_predictor_path)
        self._dlib_loaded = True


def _face_center(face) -> tuple[float, float]:
    return ((face.left() + face.right()) / 2.0, (face.top() + face.bottom()) / 2.0)


def _scale_polygon(points: list[list[float]], width: int, height: int) -> list[list[float]]:
    if max(max(abs(float(x)), abs(float(y))) for x, y in points) <= 1.0:
        return [[float(x) * width, float(y) * height] for x, y in points]
    return [[float(x), float(y)] for x, y in points]


def _point_in_polygon(point: tuple[float, float], polygon: np.ndarray) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            boundary_x = (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            if x < boundary_x:
                inside = not inside
        j = i
    return inside
