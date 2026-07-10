"""Alarm service orchestration for persistence, snapshots, push, and notification."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Callable

import numpy as np

from ..config import Config
from ..detectors.base import AlarmEvent

logger = logging.getLogger(__name__)


class AlarmService:
    """Main alarm-center entry point used by detectors and integration tests."""

    def __init__(
        self,
        cooldown: int = 30,
        notifier=None,
        broadcaster: Callable[[dict], int] | None = None,
        snapshot_dir: str | None = None,
    ):
        self.cooldown = cooldown
        self._last_fired: dict[tuple[int, str], tuple[float, int | None]] = {}
        self._notifier = notifier
        self._broadcaster = broadcaster
        self.snapshot_dir = snapshot_dir or Config.SNAPSHOT_DIR

    def _dedup(self, region_id: int, type_: str) -> bool:
        key = (region_id, type_)
        now = time.time()
        last_ts, _ = self._last_fired.get(key, (0.0, None))
        if now - last_ts < self.cooldown:
            return False
        self._last_fired[key] = (now, None)
        return True

    def raise_alarm(
        self,
        event: AlarmEvent | None = None,
        frame=None,
        region_id: int | None = None,
        type_: str | None = None,
        extra: dict | None = None,
    ) -> dict | None:
        """Trigger the full alarm close loop.

        New code should pass an AlarmEvent. region_id/type_ are kept for older
        callers. face_recognition uses only the lightweight frontend channel.
        """
        if type_ == "face_recognition":
            from ..api.ws import set_face_result

            if extra:
                msg = {"type": "stranger"}
                if extra.get("face_match", "").startswith("member:"):
                    msg = {
                        "type": "member",
                        "member_id": extra.get("member_id"),
                        "name": extra.get("name", "unknown"),
                    }
                set_face_result(msg)
            return None

        event = self._normalize_event(event, region_id, type_, extra)
        if not self._dedup(event.region_id, event.type):
            logger.info("[alarm] dedup region=%s type=%s", event.region_id, event.type)
            return None

        if frame is None:
            frame = event.snapshot
        event.snapshot_url = event.snapshot_url or self._save_snapshot(event, frame)
        event.face_match = event.face_match or self._match_face(event, frame)

        record = self._persist(event)
        self._last_fired[(event.region_id, event.type)] = (time.time(), record.id)
        payload = self._serialize_record(record)

        if event.level >= 1:
            self._broadcast(payload)
            self._notify(record.id)
            self._record_clip(record.id, event)
        else:
            logger.info("[alarm] private level=0 alarm_id=%s", record.id)

        return payload

    def _record_clip(self, alarm_id: int, event: AlarmEvent):
        """触发视频片段录制(任务书G2)。"""
        try:
            from .clip_recorder import get_clip_recorder
            recorder = get_clip_recorder()
            recorder.record(
                camera_id=event.camera_id,
                alarm_id=alarm_id,
                event_ts=event.ts,
                alarm_type=event.type,
            )
            logger.info("[alarm] 已触发片段录制 alarm_id=%d", alarm_id)
        except Exception:
            logger.exception("[alarm] 片段录制触发失败 alarm_id=%d", alarm_id)

    def _normalize_event(
        self,
        event: AlarmEvent | None,
        region_id: int | None,
        type_: str | None,
        extra: dict | None = None,
    ) -> AlarmEvent:
        if event is None:
            if region_id is None or type_ is None:
                raise ValueError("raise_alarm() requires AlarmEvent or region_id/type_")
            event = AlarmEvent(type=type_, region_id=region_id)
        else:
            if region_id is not None:
                event.region_id = region_id
            if type_ is not None:
                event.type = type_

        if event.ts == 0:
            event.ts = time.time()
        if event.extra is None:
            event.extra = {}
        if extra:
            event.extra.update(extra)
        if "level" in event.extra and event.level == 1:
            event.level = int(event.extra["level"])
        return event

    def _save_snapshot(self, event: AlarmEvent, frame) -> str:
        if frame is None:
            return event.snapshot_url or ""

        os.makedirs(self.snapshot_dir, exist_ok=True)
        ts_ms = int((event.ts or time.time()) * 1000)
        filename = f"alarm_{ts_ms}_{event.region_id}_{event.type}.jpg"
        path = os.path.join(self.snapshot_dir, filename)

        saved = False
        if isinstance(frame, np.ndarray):
            try:
                import cv2

                saved = bool(cv2.imwrite(path, frame))
            except Exception:
                logger.exception("[alarm] failed to save snapshot with cv2 path=%s", path)
        if not saved:
            with open(path, "wb") as fh:
                try:
                    fh.write(np.asarray(frame).tobytes())
                except Exception:
                    fh.write(b"")
        return f"/api/alarms/snapshots/{filename}"

    def _match_face(self, event: AlarmEvent, frame) -> str:
        if event.face_match:
            return event.face_match
        if event.extra.get("face_match"):
            return str(event.extra["face_match"])
        if event.type not in {"intrusion", "occupy"}:
            return "stranger"

        face_img = event.face_crop if event.face_crop is not None else frame
        if face_img is None:
            return "stranger"

        try:
            from ..detectors.face import FaceMatcher

            matcher = FaceMatcher()
            feature = matcher.encode(face_img)
            if feature is None:
                return "stranger"
            return matcher.match(feature)
        except Exception:
            logger.exception("[alarm] face matching failed")
            return "stranger"

    def _persist(self, event: AlarmEvent):
        from ..models.database import SessionLocal
        from ..models.entities import AlarmEvent as AlarmRecord

        created_at = (
            datetime.fromtimestamp(event.ts, timezone.utc).replace(tzinfo=None)
            if event.ts
            else datetime.now(timezone.utc).replace(tzinfo=None)
        )
        session = SessionLocal()
        try:
            record = AlarmRecord(
                region_id=event.region_id,
                camera_id=event.camera_id,
                type=event.type,
                snapshot_url=event.snapshot_url or "",
                clip_url="",
                face_match=event.face_match or "stranger",
                message=self._describe_alarm(event),
                level=event.level,
                status="pending",
                extra=json.dumps(event.extra or {}, ensure_ascii=False),
                created_at=created_at,
                confirmed_at=None,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record
        except Exception:
            session.rollback()
            logger.exception("[alarm] failed to persist event=%s", event)
            raise
        finally:
            session.close()

    def _describe_alarm(self, event: AlarmEvent) -> str:
        """生成告警文字描述(任务书G4)。"""
        extra = event.extra or {}
        face_match = event.face_match or extra.get("face_match", "")
        
        if event.type == "fight":
            vis_score = extra.get("vis_score", "")
            aud_score = extra.get("aud_score", "")
            fuse = extra.get("fuse", "")
            return f"检测到肢体冲突：视觉冲突分 {vis_score}，音频冲突分 {aud_score}，融合分 {fuse} 超过阈值"
        
        elif event.type == "intrusion":
            if face_match.startswith("member:"):
                member_name = face_match.split(":")[1] if ":" in face_match else face_match
                return f"会员 {member_name} 闯入危险区域"
            return f"{face_match} 闯入危险区域"
        
        elif event.type == "fire_smoke":
            confidence = extra.get("confidence", "")
            return f"检测到烟火，置信度 {confidence}"
        
        elif event.type == "occupy":
            if face_match.startswith("member:"):
                member_name = face_match.split(":")[1] if ":" in face_match else face_match
                return f"会员 {member_name} 占用座位时间过长"
            return f"{face_match} 占用座位时间过长"
        
        elif event.type == "fatigue":
            ear_score = extra.get("ear_score", "")
            mar_score = extra.get("mar_score", "")
            if ear_score:
                return f"检测到疲劳：眼睛闭合，EAR={ear_score}"
            if mar_score:
                return f"检测到疲劳：打哈欠，MAR={mar_score}"
            return "检测到疲劳状态"
        
        elif event.type == "face_recognition":
            return f"人脸识别：{face_match}"
        
        return f"{event.type} 告警"

    def _serialize_record(self, record) -> dict:
        extra = {}
        if record.extra:
            try:
                extra = json.loads(record.extra)
            except json.JSONDecodeError:
                extra = {}
        return {
            "id": record.id,
            "region_id": record.region_id,
            "camera_id": record.camera_id,
            "type": record.type,
            "snapshot_url": record.snapshot_url or "",
            "clip_url": record.clip_url or "",
            "face_match": record.face_match or "",
            "message": record.message or "",
            "level": record.level,
            "status": record.status,
            "extra": extra,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "confirmed_at": record.confirmed_at.isoformat() if record.confirmed_at else None,
        }

    def _broadcast(self, payload: dict) -> int:
        if self._broadcaster is not None:
            return self._broadcaster(payload) or 0
        from ..api.ws import broadcast_alarm

        return broadcast_alarm(payload)

    def _notify(self, alarm_id: int) -> None:
        notifier = self._notifier
        if notifier is None:
            from .dingtalk import get_notifier

            notifier = get_notifier()
        notifier.notify(alarm_id)


_default_alarm_service: AlarmService | None = None


def get_alarm_service() -> AlarmService:
    global _default_alarm_service
    if _default_alarm_service is None:
        _default_alarm_service = AlarmService()
    return _default_alarm_service
