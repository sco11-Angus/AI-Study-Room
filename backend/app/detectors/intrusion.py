"""Danger-zone intrusion detection: YOLO person boxes + geometric debounce."""
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import NamedTuple

import cv2
import numpy as np

from ..config import Config
from ..models.database import SessionLocal
from ..models.entities import Member, Region, SeatReservation
from .face import FaceMatcher
from .base import AlarmEvent, Detector, Frame
from .zone_emotion import ZoneEmotionRisk

logger = logging.getLogger(__name__)

Box = tuple[float, float, float, float]


class TrackedBox(NamedTuple):
    """Person box plus the local ByteTrack identity for this stream."""

    box: Box
    track_id: int | None = None


def denormalize_polygon(polygon: list, width: int, height: int) -> list:
    """将归一化坐标 [0,1] 的多边形还原为像素坐标。

    前端以归一化坐标入库（与分辨率解耦）。检测器内部按像素判定，
    故加载时 × 帧宽高还原。对所有坐标均 ≤ 1 的点视为归一化；
    若已是像素坐标（存在 > 1 的值），原样返回以兼容历史数据。
    """
    if not polygon:
        return polygon
    if not is_normalized_polygon(polygon):
        return polygon
    return [[pt[0] * width, pt[1] * height] for pt in polygon]


def is_normalized_polygon(polygon: list) -> bool:
    return bool(polygon) and all(
        isinstance(pt, (list, tuple)) and len(pt) == 2
        and abs(pt[0]) <= 1.0 and abs(pt[1]) <= 1.0
        for pt in polygon
    )


class IntrusionDetector:
    """Per-region danger timer using bottom-center person point."""

    def __init__(self, polygon: list, x_distance: int, y_stay_time: int):
        self._source_polygon = polygon
        self._normalized_polygon = is_normalized_polygon(polygon)
        self._frame_size: tuple[int, int] | None = None
        self.polygon = np.array(polygon, dtype=np.int32)
        self.x_distance = x_distance
        self.y_stay_time = y_stay_time
        self._danger_since = None

    def prepare_frame(self, image: np.ndarray) -> None:
        """Scale normalized polygons against the actual decoded frame size.

        Streams can be 640x480 locally and 1280x720 through OBS.  Keeping a
        fixed configured size here shifts the persisted polygon away from the
        YOLO person boxes when a stream resolution changes.
        """
        if not self._normalized_polygon:
            return
        height, width = image.shape[:2]
        frame_size = (width, height)
        if frame_size == self._frame_size:
            return
        self.polygon = np.array(
            denormalize_polygon(self._source_polygon, width, height),
            dtype=np.int32,
        )
        self._frame_size = frame_size

    @staticmethod
    def base_point(box) -> tuple[int, int]:
        x1, _y1, x2, y2 = box
        return int((x1 + x2) / 2), int(y2)

    def judge(self, box, ts: float) -> bool:
        in_danger = self.is_in_danger(box)

        if in_danger:
            if self._danger_since is None:
                self._danger_since = ts
            elif ts - self._danger_since >= self.y_stay_time:
                return True
        else:
            self._danger_since = None
        return False

    def is_in_danger(self, box) -> bool:
        cx, cy = self.base_point(box)
        return self.is_point_in_danger(cx, cy)

    def is_point_in_danger(self, x: float, y: float) -> bool:
        d = cv2.pointPolygonTest(self.polygon, (int(x), int(y)), True)
        return d >= 0 or (d < 0 and abs(d) <= self.x_distance)


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

    def detect_people_tracked(self, image: np.ndarray) -> list[TrackedBox]:
        """Use Ultralytics ByteTrack, falling back to plain YOLO boxes."""
        if self._model is None:
            self.setup()
        try:
            results = self._model.track(
                image, persist=True, tracker="bytetrack.yaml", verbose=False
            )
            tracked: list[TrackedBox] = []
            for result in results:
                boxes = getattr(result, "boxes", None)
                if boxes is None:
                    continue
                ids = getattr(boxes, "id", None)
                for index, box in enumerate(boxes):
                    cls = int(box.cls[0].item() if hasattr(box.cls[0], "item") else box.cls[0])
                    conf = float(box.conf[0].item() if hasattr(box.conf[0], "item") else box.conf[0])
                    if cls != 0 or conf <= self.conf_threshold:
                        continue
                    xyxy = tuple(float(v) for v in box.xyxy[0].tolist())
                    track_id = None
                    if ids is not None and index < len(ids):
                        value = ids[index]
                        track_id = int(value.item() if hasattr(value, "item") else value)
                    tracked.append(TrackedBox(xyxy, track_id))
            return tracked
        except Exception:
            logger.exception("[intrusion] ByteTrack failed; falling back to YOLO boxes")
            return [TrackedBox(box) for box in self.detect_people(image)]


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
    member_id: int
    member_name: str
    detector: IntrusionDetector


@dataclass
class SeatTrack:
    box: Box
    entered_at: float
    last_seen_frame: int
    seen_count: int = 1
    missed_inferences: int = 0
    evaluated: bool = False
    alerted: bool = False
    allowed: bool = False
    external_id: int | None = None


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
        self._zone_emotion = ZoneEmotionRisk()
        self._regions: dict[int, RegionRuntime] = {}
        self._seats: dict[int, SeatRuntime] = {}
        self._region_tracks: dict[int, dict[int, SeatTrack]] = {}
        self._seat_tracks: dict[int, dict[int, SeatTrack]] = {}
        self._next_track_id = 1

    def setup(self) -> None:
        self.person_detector.setup()
        self._reload_regions()

    @property
    def zone_emotion(self) -> ZoneEmotionRisk:
        return self._zone_emotion

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
            self._region_tracks.clear()
            self._seat_tracks.clear()
            logger.info("[intrusion] active danger zones: %s", sorted(self._regions))
            logger.info("[intrusion] active reserved seats: %s", sorted(self._seats))
        finally:
            session.close()

    def _load_active_seats(self, session) -> dict[int, SeatRuntime]:
        rows = (
            session.query(SeatReservation, Region, Member)
            .join(Region, SeatReservation.region_id == Region.id)
            .join(Member, SeatReservation.member_id == Member.member_id)
            .filter(SeatReservation.enabled.is_(True), Region.type == "seat")
            .all()
        )
        seats: dict[int, SeatRuntime] = {}
        for reservation, region, member in rows:
            try:
                polygon = json.loads(region.polygon or "[]")
                if len(polygon) < 3 or reservation.member_id is None:
                    continue
                seats[int(region.id)] = SeatRuntime(
                    id=int(region.id),
                    camera_id=int(region.camera_id or 0),
                    name=region.name or f"seat-{region.id}",
                    member_id=int(reservation.member_id),
                    member_name=member.name or f"member-{reservation.member_id}",
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

        track_method = getattr(self.person_detector, "detect_people_tracked", None)
        if callable(track_method):
            tracked_people = track_method(frame.image)
        else:
            # Keep legacy test doubles and integrations source-compatible.
            tracked_people = [TrackedBox(box) for box in self.person_detector.detect_people(frame.image)]
        people = [item.box for item in tracked_people]
        if self.shared_ctx is not None:
            self.shared_ctx.set(frame.camera_id, frame.frame_idx, people)

        events: list[AlarmEvent] = []
        ts = frame.ts if frame.ts is not None else time.time()
        for region in regions:
            region.detector.prepare_frame(frame.image)
            events.extend(self._detect_danger_zone(region, tracked_people, frame, ts))
        for seat in seats:
            seat.detector.prepare_frame(frame.image)
            events.extend(self._detect_reserved_seat(seat, tracked_people, frame, ts))
        return events

    def _detect_danger_zone(
        self,
        region: RegionRuntime,
        people: list[TrackedBox],
        frame: Frame,
        ts: float,
    ) -> list[AlarmEvent]:
        """Advance each danger-zone occupant through enter, dwell, and exit."""
        tracks = self._region_tracks.setdefault(region.id, {})
        raw_people = [item.box for item in people]
        active_boxes = [item for item in people if region.detector.is_in_danger(item.box)]
        if not active_boxes:
            removed = list(tracks.items()) if raw_people else self._expire_unmatched_tracks(
                tracks, raw_people, set(), region
            )
            if raw_people:
                tracks.clear()
            return self._clear_events(region, "intrusion", "danger_zone", frame, ts, removed)

        matched_track_ids: set[int] = set()
        events: list[AlarmEvent] = []
        for item in active_boxes:
            box = item.box
            track_id = self._match_track(tracks, item, frame.frame_idx, matched_track_ids)
            if track_id is None:
                track_id = self._next_track_id
                self._next_track_id += 1
                tracks[track_id] = SeatTrack(box=box, entered_at=ts, last_seen_frame=frame.frame_idx, external_id=item.track_id)
            else:
                track = tracks[track_id]
                track.box = box
                track.last_seen_frame = frame.frame_idx
                track.seen_count += 1
                track.missed_inferences = 0

            matched_track_ids.add(track_id)
            track = tracks[track_id]
            if (
                not track.evaluated
                and track.seen_count >= Config.INTRUSION_MIN_OBSERVATIONS
                and ts - track.entered_at >= region.detector.y_stay_time
            ):
                track.evaluated = True
                track.alerted = True
                zone_modifier = self._zone_emotion.get_zone_threshold_modifier(region.id)
                extra_data = {
                    "kind": "danger_zone",
                    "lifecycle": "active",
                    "region_name": region.name,
                    "person_box": [round(float(v), 2) for v in box],
                    "track_key": f"region-{region.id}-track-{track_id}",
                }
                if zone_modifier < 1.0:
                    extra_data["zone_emotion_risk"] = True
                    extra_data["zone_threshold_modifier"] = round(zone_modifier, 2)
                events.append(
                    AlarmEvent(
                        type="intrusion",
                        region_id=region.id,
                        camera_id=frame.camera_id,
                        ts=ts,
                        level=1,
                        extra=extra_data,
                    )
                )

        removed = self._expire_unmatched_tracks(tracks, raw_people, matched_track_ids, region)
        events.extend(self._clear_events(region, "intrusion", "danger_zone", frame, ts, removed))
        return events

    def _detect_reserved_seat(
        self,
        seat: SeatRuntime,
        people: list[TrackedBox],
        frame: Frame,
        ts: float,
    ) -> list[AlarmEvent]:
        tracks = self._seat_tracks.setdefault(seat.id, {})
        raw_people = [item.box for item in people]
        detect_faces = getattr(self.face_matcher, "detect_faces", None)
        face_rects = detect_faces(frame.image) if callable(detect_faces) else None
        active_boxes = self._active_seat_boxes(seat, people, face_rects)
        if not active_boxes:
            # A person box outside the seat is an explicit exit. When YOLO
            # misses everybody, use the configured inference-miss threshold
            # before clearing the trajectory.
            if raw_people:
                removed = list(tracks.items())
                tracks.clear()
            else:
                removed = self._expire_unmatched_tracks(tracks, people, set(), seat)
            return self._clear_events(seat, "occupy", "unauthorized_seat", frame, ts, removed)
        matched_track_ids: set[int] = set()
        eligible: list[tuple[int, SeatTrack, Box]] = []
        allowed_events: list[AlarmEvent] = []

        for item in active_boxes:
            box = item.box
            track_id = self._match_track(tracks, item, frame.frame_idx, matched_track_ids)
            if track_id is None:
                track_id = self._next_track_id
                self._next_track_id += 1
                tracks[track_id] = SeatTrack(
                    box=box,
                    entered_at=ts,
                    last_seen_frame=frame.frame_idx,
                    external_id=item.track_id,
                )
            else:
                track = tracks[track_id]
                track.box = box
                track.last_seen_frame = frame.frame_idx
                track.seen_count += 1
                track.missed_inferences = 0

            matched_track_ids.add(track_id)
            track = tracks[track_id]
            if not track.allowed:
                face_match, _face_crop = self._match_person_fullframe(frame.image, box, face_rects)
                if face_match == f"member:{seat.member_id}":
                    track.allowed = True
                    track.evaluated = True
                    allowed_events.extend(self._allowed_event(seat, track_id, frame, ts))
                    # The owner can take over a previously alerting track when
                    # recognition becomes available on a later frame.
                    if track.alerted:
                        track.alerted = False
            if (
                not track.evaluated
                and track.seen_count >= Config.INTRUSION_MIN_OBSERVATIONS
                and ts - track.entered_at >= seat.detector.y_stay_time
            ):
                eligible.append((track_id, track, box))

        removed = self._expire_unmatched_tracks(tracks, raw_people, matched_track_ids, seat)

        events = self._clear_events(seat, "occupy", "unauthorized_seat", frame, ts, removed)
        events.extend(allowed_events)
        if not eligible:
            return events
        expected = f"member:{seat.member_id}"
        for track_id, track, box in eligible:
            face_match, face_crop = self._match_person_fullframe(frame.image, box, face_rects)
            track.evaluated = True
            if face_match == expected:
                track.allowed = True
                continue

            track.alerted = True
            logger.info(
                "[intrusion] unauthorized seat: camera_id=%s seat_id=%s reserved=%s actual=%s",
                frame.camera_id,
                seat.id,
                seat.member_id,
                face_match,
            )
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
                        "reserved_member_id": seat.member_id,
                        "reserved_member_name": seat.member_name,
                        "actual_face_match": face_match,
                        "person_box": [round(float(v), 2) for v in box],
                        "track_key": f"seat-{seat.id}-track-{track_id}",
                        "lifecycle": "active",
                    },
                )
            )
        return events

    def _expire_unmatched_tracks(
        self,
        tracks: dict[int, SeatTrack],
        people: list[Box],
        matched_track_ids: set[int],
        runtime: RegionRuntime | SeatRuntime | None = None,
    ) -> list[tuple[int, SeatTrack]]:
        """Expire after configured inference misses, never raw video-frame gaps.

        The scheduler calls intrusion only every ``SKIP_N`` decoded frames.
        Comparing its raw frame indexes made every healthy next inference look
        like more than three misses when ``SKIP_N`` was 5, so a seat track was
        deleted before it could ever reach the two-observation dwell gate.
        """
        removed: list[tuple[int, SeatTrack]] = []
        for track_id, track in list(tracks.items()):
            if track_id in matched_track_ids:
                continue
            exited = runtime is not None and any(
                self._iou(track.box, box) >= 0.3 and not runtime.detector.is_in_danger(box)
                for box in people
            )
            if exited:
                removed.append((track_id, track))
                del tracks[track_id]
                continue
            track.missed_inferences += 1
            if track.missed_inferences >= Config.INTRUSION_EXIT_MISSES:
                removed.append((track_id, track))
                del tracks[track_id]
        return removed

    @staticmethod
    def _allowed_event(seat: SeatRuntime, track_id: int, frame: Frame, ts: float) -> list[AlarmEvent]:
        return [
            AlarmEvent(
                type="occupy",
                region_id=seat.id,
                camera_id=frame.camera_id,
                ts=ts,
                level=0,
                extra={
                    "kind": "authorized_seat",
                    "lifecycle": "allowed",
                    "track_key": f"seat-{seat.id}-track-{track_id}",
                    "seat_name": seat.name,
                    "member_id": seat.member_id,
                    "member_name": seat.member_name,
                },
            )
        ]

    def _clear_events(
        self,
        runtime: RegionRuntime | SeatRuntime,
        alarm_type: str,
        kind: str,
        frame: Frame,
        ts: float,
        removed: list[tuple[int, SeatTrack]],
    ) -> list[AlarmEvent]:
        """Emit non-persistent clear messages for tracks that had alerted."""
        prefix = "seat" if isinstance(runtime, SeatRuntime) else "region"
        events: list[AlarmEvent] = []
        for track_id, track in removed:
            if not track.alerted:
                continue
            events.append(
                AlarmEvent(
                    type=alarm_type,
                    region_id=runtime.id,
                    camera_id=frame.camera_id,
                    ts=ts,
                    level=0,
                    extra={
                        "kind": kind,
                        "lifecycle": "cleared",
                        "track_key": f"{prefix}-{runtime.id}-track-{track_id}",
                    },
                )
            )
        return events

    def get_active_alarm_states(self) -> list[dict]:
        """Return alerting tracks so a reloaded dashboard restores live state."""
        states: list[dict] = []
        for region_id, tracks in self._region_tracks.items():
            region = self._regions.get(region_id)
            if region is None:
                continue
            for track_id, track in tracks.items():
                if track.alerted:
                    states.append({"region_id": region_id, "camera_id": region.camera_id,
                                   "alarm_type": "intrusion", "track_key": f"region-{region_id}-track-{track_id}"})
        for seat_id, tracks in self._seat_tracks.items():
            seat = self._seats.get(seat_id)
            if seat is None:
                continue
            for track_id, track in tracks.items():
                if track.alerted:
                    states.append({"region_id": seat_id, "camera_id": seat.camera_id,
                                   "alarm_type": "occupy", "track_key": f"seat-{seat_id}-track-{track_id}"})
        return states

    @staticmethod
    def _box_contains_point(box: Box, x: float, y: float) -> bool:
        return box[0] <= x <= box[2] and box[1] <= y <= box[3]

    def _active_seat_boxes(self, seat: SeatRuntime, people: list[TrackedBox], face_rects) -> list[TrackedBox]:
        """Treat a seated face in the polygon as occupancy too.

        A seated person's YOLO box often extends below the drawn desk/seat
        area, so its bottom-center can be outside even while the person is
        clearly occupying that seat.  Face-center is an additional geometry
        signal for reserved seats only; ordinary danger zones remain unchanged.
        """
        faces = list(face_rects or [])
        active: list[Box] = []
        for item in people:
            box = item.box
            has_face_in_seat = any(
                seat.detector.is_point_in_danger(
                    (rect.left() + rect.right()) / 2,
                    (rect.top() + rect.bottom()) / 2,
                )
                and self._box_contains_point(
                    box,
                    (rect.left() + rect.right()) / 2,
                    (rect.top() + rect.bottom()) / 2,
                )
                for rect in faces
            )
            if seat.detector.is_in_danger(box) or has_face_in_seat:
                active.append(item)

        # If YOLO misses a seated upper body, an in-seat face still produces a
        # stable pseudo-person track instead of silently disabling the alarm.
        for rect in faces:
            center_x = (rect.left() + rect.right()) / 2
            center_y = (rect.top() + rect.bottom()) / 2
            if not seat.detector.is_point_in_danger(center_x, center_y):
                continue
            if any(self._box_contains_point(item.box, center_x, center_y) for item in people):
                continue
            active.append(TrackedBox((float(rect.left()), float(rect.top()), float(rect.right()), float(rect.bottom()))))
        return active

    @staticmethod
    def _iou(a: Box, b: Box) -> float:
        left, top = max(a[0], b[0]), max(a[1], b[1])
        right, bottom = min(a[2], b[2]), min(a[3], b[3])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        if intersection <= 0:
            return 0.0
        area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
        area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        union = area_a + area_b - intersection
        return intersection / union if union else 0.0

    def _match_track(
        self,
        tracks: dict[int, SeatTrack],
        item: TrackedBox,
        frame_idx: int,
        matched_track_ids: set[int],
    ) -> int | None:
        if item.track_id is not None:
            for track_id, track in tracks.items():
                if track_id not in matched_track_ids and track.external_id == item.track_id:
                    return track_id

        candidates = [
            (self._iou(track.box, item.box), track_id)
            for track_id, track in tracks.items()
            # ``frame_idx`` advances for every decoded frame while this
            # method is called only for inference frames.  Use the explicit
            # inference-miss counter instead of mixing those two clocks.
            if track_id not in matched_track_ids and track.missed_inferences <= 3
        ]
        if not candidates:
            return None
        score, track_id = max(candidates)
        return track_id if score >= 0.3 else None

    def _match_person_fullframe(
        self,
        image: np.ndarray,
        box: Box,
        face_rects,
    ) -> tuple[str, np.ndarray | None]:
        """Associate whole-frame faces with a person box before encoding."""
        if face_rects is not None:
            for rect in face_rects:
                center_x = (rect.left() + rect.right()) / 2
                center_y = (rect.top() + rect.bottom()) / 2
                if box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]:
                    feature = self.face_matcher.encode_from_rect(image, rect)
                    face_crop = self._crop_rect(image, rect)
                    return (
                        self.face_matcher.match(feature) if feature is not None else "stranger",
                        face_crop,
                    )
            return "stranger", None

        # Test doubles and older integrations may expose only encode()/match().
        return self._match_person_legacy(image, box)

    @staticmethod
    def _crop_rect(image: np.ndarray, rect) -> np.ndarray | None:
        h, w = image.shape[:2]
        x1, y1 = max(0, rect.left()), max(0, rect.top())
        x2, y2 = min(w, rect.right()), min(h, rect.bottom())
        return image[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else None

    def _match_person_legacy(self, image: np.ndarray, box: Box) -> tuple[str, np.ndarray | None]:
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
