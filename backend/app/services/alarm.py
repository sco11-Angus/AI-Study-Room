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
        event_type = type_ if type_ else (event.type if event else None)
        if event_type == "face_recognition":
            from ..api.ws import set_face_result

            msg = {"type": "stranger"}
            if event and event.extra and event.extra.get("face_match", "").startswith("member:"):
                msg = {
                    "type": "member",
                    "member_id": event.extra.get("member_id"),
                    "name": event.extra.get("name", "unknown"),
                }
            elif extra and extra.get("face_match", "").startswith("member:"):
                msg = {
                    "type": "member",
                    "member_id": extra.get("member_id"),
                    "name": extra.get("name", "unknown"),
                }
            set_face_result(msg)
            return None

        if event_type == "face_spoof":
            from ..api.ws import broadcast_face_result

            extra_dict = event.extra if event and event.extra else (extra if isinstance(extra, dict) else {})
            if extra_dict:
                msg = {
                    "type": "face_spoof",
                    "confidence": extra_dict.get("confidence"),
                    "reasons": extra_dict.get("reasons"),
                }
                broadcast_face_result(msg)
            event = self._normalize_event(event, region_id, type_, extra)
            event.level = 2
            frame = frame if frame is not None else event.snapshot
            if frame is not None:
                event.snapshot_url = event.snapshot_url or self._save_snapshot(event, frame)
            record = self._persist(event)
            self._last_fired[(event.region_id, event.type)] = (time.time(), record.id)
            payload = self._serialize_record(record)
            self._broadcast(payload)
            self._notify(record.id)
            self._log_alarm_event(record, event)
            return payload

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
            self._record_clip(record.id, event)
            self._notify(record.id)
        else:
            logger.info("[alarm] private level=0 alarm_id=%s", record.id)

        self._log_alarm_event(record, event)

        return payload

    def _log_alarm_event(self, record, event):
        """记录告警事件到日志文件（任务书G5扩展）。"""
        log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = os.path.join(log_dir, f"alarm_{date_str}.log")
        
        extra = event.extra or {}
        extra_str = json.dumps(extra, ensure_ascii=False, separators=(",", ":"))
        
        actor = extra.get("actor", "")
        behavior = extra.get("behavior", "")
        
        log_entry = (
            f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
            f"ALARM_TRIGGERED "
            f"id={record.id} "
            f"type={event.type} "
            f"level={event.level} "
            f"region={event.region_id} "
            f"camera={event.camera_id} "
            f"face_match={event.face_match} "
            f"actor={actor} "
            f"behavior={behavior} "
            f"message={record.message} "
            f"snapshot_url={event.snapshot_url} "
            f"extra={extra_str}\n"
        )
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
        
        logger.info(
            "[alarm] 日志已记录 alarm_id=%d type=%s level=%d region=%d camera=%d message=%s",
            record.id, event.type, event.level, event.region_id, event.camera_id, record.message
        )

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

                compressed_frame = self._compress_frame(frame)
                saved = bool(cv2.imwrite(path, compressed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60]))
                original_size = frame.size * frame.itemsize
                compressed_size = compressed_frame.size * compressed_frame.itemsize
                logger.info(
                    "[alarm] snapshot saved path=%s original=%d bytes compressed=%d bytes ratio=%.1f%%",
                    filename, original_size, compressed_size, compressed_size / original_size * 100
                )
            except Exception:
                logger.exception("[alarm] failed to save snapshot with cv2 path=%s", path)
        if not saved:
            with open(path, "wb") as fh:
                try:
                    fh.write(np.asarray(frame).tobytes())
                except Exception:
                    fh.write(b"")
        return f"/api/alarms/snapshots/{filename}"

    def _compress_frame(self, frame):
        """压缩帧以减少存储空间占用（分辨率和质量）。"""
        import cv2

        max_width = 1280
        max_height = 720
        
        height, width = frame.shape[:2]
        if width > max_width or height > max_height:
            scale = min(max_width / width, max_height / height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
        
        return frame

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

        # 使用本机本地时间（北京时间），而非 UTC，避免前端显示慢 8 小时
        created_at = (
            datetime.fromtimestamp(event.ts)
            if event.ts
            else datetime.now()
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
        actor = self._first_extra_text(
            extra,
            ("actor", "person", "person_name", "student", "student_name", "member_name", "nickname", "name"),
        )
        behavior = self._first_extra_text(extra, ("behavior", "action", "reason", "trigger", "description"))
        type_label = {
            "intrusion": "入侵告警",
            "fire_smoke": "烟火告警",
            "occupy": "占座告警",
            "fatigue": "疲劳提醒",
            "fight": "打架告警",
            "face_recognition": "人脸识别",
            "face_spoof": "欺骗攻击告警",
        }.get(event.type, f"{event.type}告警")

        if actor and behavior:
            return self._append_score_summary(f"{actor}因{behavior}触发{type_label}", extra)
        if behavior:
            return self._append_score_summary(f"检测到{behavior}，触发{type_label}", extra)
        if actor:
            return self._append_score_summary(f"{actor}触发{type_label}", extra)

        if event.type == "fight":
            parts = ["检测到肢体冲突"]
            vis_score = extra.get("vis_score")
            aud_score = extra.get("aud_score")
            fuse = extra.get("fuse")
            if vis_score is not None:
                parts.append(f"视觉冲突分{vis_score}")
            if aud_score is not None:
                parts.append(f"音频冲突分{aud_score}")
            if fuse is not None:
                parts.append(f"融合分{fuse}")
            return "，".join(parts)
        
        elif event.type == "face_spoof":
            liveness_score = extra.get("liveness_score")
            reasons = extra.get("reasons", [])
            reason_text = "、".join(reasons) if reasons else "未知原因"
            if liveness_score is not None:
                return f"检测到欺骗攻击（活体分数={liveness_score:.3f}），原因：{reason_text}"
            return f"检测到欺骗攻击，原因：{reason_text}"
        
        elif event.type == "intrusion":
            if face_match.startswith("member:"):
                member_name = face_match.split(":")[1] if ":" in face_match else face_match
                return f"会员{member_name}闯入危险区域"
            if face_match and face_match != "stranger":
                return f"{face_match}闯入危险区域"
            return "检测到人员闯入危险区域"
        
        elif event.type == "fire_smoke":
            confidence = extra.get("confidence")
            if confidence:
                return f"检测到烟火，置信度{confidence}"
            return "检测到疑似烟火"
        
        elif event.type == "occupy":
            if extra.get("kind") == "unauthorized_seat":
                seat_name = extra.get("seat_name") or "该座位"
                reserved = extra.get("reserved_member_name") or extra.get("reserved_member_id") or "未知"
                actual = extra.get("actual_face_match") or face_match or "stranger"
                actual_label = "陌生人员" if actual == "stranger" else actual
                return f"非预约人员占用座位 {seat_name}（预约人：{reserved}，实际：{actual_label}）"
            if face_match.startswith("member:"):
                member_name = face_match.split(":")[1] if ":" in face_match else face_match
                return f"会员{member_name}占用座位时间过长"
            if face_match and face_match != "stranger":
                return f"{face_match}占用座位时间过长"
            return "检测到座位占用时间过长"
        
        elif event.type == "fatigue":
            ear_score = extra.get("ear_score")
            mar_score = extra.get("mar_score")
            if ear_score:
                return f"检测到疲劳：眼睛闭合，EAR={ear_score}"
            if mar_score:
                return f"检测到疲劳：打哈欠，MAR={mar_score}"
            return "检测到疲劳学习状态"
        
        elif event.type == "face_recognition":
            return f"人脸识别：{face_match}" if face_match else "人脸识别告警"
        
        return type_label

    def _first_extra_text(self, extra: dict, keys: tuple[str, ...]) -> str:
        for key in keys:
            value = extra.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    def _append_score_summary(self, message: str, extra: dict) -> str:
        score_keys = ("confidence", "score", "vis_score", "aud_score", "fuse", "stay_seconds", "duration")
        parts = [f"{key}={extra[key]}" for key in score_keys if extra.get(key) is not None]
        if not parts:
            return message
        return f"{message}（检测依据：{', '.join(parts)}）"

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
        from ..api.ws import broadcast_alarm, broadcast_companion_alarm

        companion_sent = broadcast_companion_alarm(payload)
        return broadcast_alarm(payload) + companion_sent

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
