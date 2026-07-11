"""告警服务 — 闭环动作编排 (系统设计说明书 §7.1)。

真实告警产生时：
  ① 现场抓拍 -> 裁剪面部 -> 人脸识别匹配
  ② 看板异动 -> WebSocket 推送前端(绿->红闪+蜂鸣)
  ③ 钉钉逐级上报(见 dingtalk.py)
同防区同类型在冷却窗口内合并去重 (§10.2)。
"""
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
    """告警中心主入口。

    检测器产出的 AlarmEvent 到这里才真正变成可追踪、可通知、可确认的告警。
    """

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
        """触发告警闭环。

        新代码应传入 AlarmEvent；region_id/type_ 参数保留给旧调用点兼容。
        face_recognition 只走轻量推送通道，不入库、不触发钉钉。
        """
        if type_ == "face_recognition":
            from ..api.ws import set_face_result
            if extra:
                msg = {"type": "stranger"}
                if extra.get("face_match", "").startswith("member:"):
                    msg = {
                        "type": "member",
                        "member_id": extra.get("member_id"),
                        "name": extra.get("name", "未知"),
                    }
                set_face_result(msg)
            return None

        event = self._normalize_event(event, region_id, type_, extra)
        if not self._dedup(event.region_id, event.type):
            logger.info("[alarm] 告警去重 region=%s type=%s", event.region_id, event.type)
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
        else:
            logger.info("[alarm] level=0 弱提醒仅保留私有端/查询记录 alarm_id=%s", record.id)

        return payload

    def _normalize_event(
        self,
        event: AlarmEvent | None,
        region_id: int | None,
        type_: str | None,
        extra: dict | None = None,
    ) -> AlarmEvent:
        if event is None:
            if region_id is None or type_ is None:
                raise ValueError("raise_alarm requires either AlarmEvent or region_id/type_")
            event = AlarmEvent(type=type_, region_id=region_id, extra=extra or {})

        if extra:
            event.extra.update(extra)
        if not event.ts:
            event.ts = time.time()
        if event.camera_id is None:
            event.camera_id = int(event.extra.get("camera_id", 0) or 0)
        if "level" in event.extra and event.level == 1:
            event.level = int(event.extra["level"])
        return event

    def _save_snapshot(self, event: AlarmEvent, frame) -> str:
        if frame is None:
            return ""

        os.makedirs(self.snapshot_dir, exist_ok=True)
        filename = f"alarm_{event.region_id}_{event.type}_{int(event.ts * 1000)}.jpg"
        path = os.path.join(self.snapshot_dir, filename)

        try:
            if isinstance(frame, (bytes, bytearray)):
                with open(path, "wb") as fh:
                    fh.write(frame)
            elif isinstance(frame, np.ndarray):
                import cv2

                ok = cv2.imwrite(path, frame)
                if not ok:
                    raise RuntimeError("cv2.imwrite returned False")
            else:
                logger.warning("[alarm] unsupported snapshot frame type: %s", type(frame).__name__)
                return ""
        except Exception:
            logger.exception("[alarm] failed to save snapshot")
            return ""

        return f"/api/alarms/snapshots/{filename}"

    def _match_face(self, event: AlarmEvent, frame) -> str:
        if event.type not in {"intrusion", "occupy"}:
            return event.face_match or ""

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

        created_at = datetime.fromtimestamp(event.ts, timezone.utc).replace(tzinfo=None)
        session = SessionLocal()
        try:
            record = AlarmRecord(
                region_id=event.region_id,
                camera_id=event.camera_id,
                type=event.type,
                snapshot_url=event.snapshot_url,
                face_match=event.face_match,
                level=event.level,
                status="pending",
                extra=json.dumps(event.extra or {}, ensure_ascii=False),
                created_at=created_at,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record
        except Exception:
            session.rollback()
            logger.exception("[alarm] failed to persist alarm")
            raise
        finally:
            session.close()

    def _broadcast(self, payload: dict) -> None:
        broadcaster = self._broadcaster
        if broadcaster is None:
            from ..api.ws import broadcast_alarm

            broadcaster = broadcast_alarm
        try:
            broadcaster(payload)
        except Exception:
            logger.exception("[alarm] websocket broadcast failed")

    def _notify(self, alarm_id: int) -> None:
        notifier = self._notifier
        if notifier is None:
            from .dingtalk import get_notifier

            notifier = get_notifier()
        try:
            notifier.notify(alarm_id)
        except Exception:
            logger.exception("[alarm] dingtalk notify failed")

    @staticmethod
    def _serialize_record(record) -> dict:
        extra = {}
        if record.extra:
            try:
                extra = json.loads(record.extra)
            except json.JSONDecodeError:
                extra = {}
        return {
            "id": record.id,
            "type": record.type,
            "region_id": record.region_id,
            "camera_id": record.camera_id,
            "ts": AlarmService._to_epoch(record.created_at),
            "level": record.level,
            "snapshot_url": record.snapshot_url or "",
            "face_match": record.face_match or "",
            "status": record.status,
            "extra": extra,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "confirmed_at": record.confirmed_at.isoformat() if record.confirmed_at else None,
        }

    @staticmethod
    def _to_epoch(dt: datetime | None) -> float | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()


_default_service: AlarmService | None = None


def get_alarm_service() -> AlarmService:
    """Return the process-local alarm service so dedup windows survive frames."""
    global _default_service
    if _default_service is None:
        _default_service = AlarmService()
    return _default_service
