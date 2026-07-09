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

        event = self._normalize_event(event, region_id, type_)
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