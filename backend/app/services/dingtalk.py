"""钉钉逐级上报与超时升级工作流 (系统设计说明书 §7.4)。"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

import requests

from ..config import Config

logger = logging.getLogger(__name__)


class DingTalkNotifier:
    """发送 ActionCard 并维护确认/升级状态机。"""

    def __init__(
        self,
        webhook: str | None = None,
        leader_webhook: str | None = None,
        timeout: int | None = None,
        session_factory=None,
        http_post=None,
    ):
        self.webhook = webhook if webhook is not None else Config.DINGTALK_WEBHOOK
        self.leader_webhook = leader_webhook or self.webhook
        self.timeout = Config.ESCALATE_TIMEOUT if timeout is None else timeout
        self._session_factory = session_factory
        self._http_post = http_post or requests.post
        self._timers: dict[int, threading.Timer] = {}

    def notify(self, alarm_id: int, title: str | None = None, text: str | None = None):
        """发送给主责安全员并启动升级计时。"""
        payload_title, payload_text = self._build_card(alarm_id, title, text, "primary")
        guard_id = self._send_card(alarm_id, payload_title, payload_text, "primary")
        self._mark_notified(alarm_id, "notified")
        self._write_log(alarm_id, guard_id, "primary")

        if self.timeout > 0:
            timer = threading.Timer(self.timeout, self._escalate, args=(alarm_id,))
            timer.daemon = True
            timer.start()
            self._timers[alarm_id] = timer

    def confirm(self, alarm_id: int) -> bool:
        """收到确认回调 -> 取消升级计时并标记 confirmed (§7.4)。"""
        timer = self._timers.pop(alarm_id, None)
        if timer:
            timer.cancel()

        from ..models.entities import AlarmEvent, NotificationLog

        session = self._session()
        try:
            alarm = session.get(AlarmEvent, alarm_id)
            if alarm is None:
                return False
            alarm.status = "confirmed"
            alarm.confirmed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            for log in session.query(NotificationLog).filter(NotificationLog.alarm_id == alarm_id).all():
                log.ack_at = alarm.confirmed_at
            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("[dingtalk] 确认告警失败 alarm_id=%s", alarm_id)
            raise
        finally:
            session.close()

    def _escalate(self, alarm_id: int):
        """超时未确认 -> 升级优先级，推送科长/直属负责人。"""
        from ..models.entities import AlarmEvent

        session = self._session()
        try:
            alarm = session.get(AlarmEvent, alarm_id)
            if alarm is None or alarm.status == "confirmed":
                return
            alarm.level = (alarm.level or 1) + 1
            alarm.status = "escalated"
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("[dingtalk] 升级状态更新失败 alarm_id=%s", alarm_id)
            raise
        finally:
            session.close()

        title, text = self._build_card(alarm_id, None, None, "escalated")
        guard_id = self._send_card(alarm_id, title, text, "escalated")
        self._write_log(alarm_id, guard_id, "escalated")

    def _build_card(
        self,
        alarm_id: int,
        title: str | None,
        text: str | None,
        stage: str,
    ) -> tuple[str, str]:
        from ..models.entities import AlarmEvent

        session = self._session()
        try:
            alarm = session.get(AlarmEvent, alarm_id)
            if alarm is None:
                base_title = title or f"告警 {alarm_id}"
                return base_title, text or "告警不存在或已删除"

            extra = {}
            if alarm.extra:
                try:
                    extra = json.loads(alarm.extra)
                except json.JSONDecodeError:
                    extra = {}
            stage_text = "升级告警" if stage == "escalated" else "安全告警"
            base_title = title or f"{stage_text}: {alarm.type}"
            created = alarm.created_at.isoformat() if alarm.created_at else ""
            lines = [
                f"### {base_title}",
                f"- 告警 ID: {alarm.id}",
                f"- 类型: {alarm.type}",
                f"- 摄像头: {alarm.camera_id or '-'}",
                f"- 防区: {alarm.region_id or '-'}",
                f"- 级别: {alarm.level}",
                f"- 时间: {created}",
            ]
            if alarm.snapshot_url:
                lines.append(f"- 抓拍: {alarm.snapshot_url}")
            if alarm.face_match:
                lines.append(f"- 人脸: {alarm.face_match}")
            if extra:
                lines.append(f"- 附加信息: `{json.dumps(extra, ensure_ascii=False)}`")
            return base_title, text or "\n".join(lines)
        finally:
            session.close()

    def _send_card(self, alarm_id: int, title: str, text: str, guard_stage: str) -> int | None:
        guard_id = self._select_guard_id(guard_stage)
        payload = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": title,
                "text": text,
                "singleTitle": "确认处理",
                "singleURL": f"/api/alarms/{alarm_id}/confirm",
            },
        }
        webhook = self.leader_webhook if guard_stage == "escalated" else self.webhook
        if webhook:
            try:
                self._http_post(webhook, json=payload, timeout=5)
            except Exception:
                logger.exception("[dingtalk] ActionCard 发送失败 stage=%s alarm_id=%s", guard_stage, alarm_id)
        else:
            logger.info("[dingtalk] 未配置 webhook，仅记录通知 stage=%s alarm_id=%s", guard_stage, alarm_id)
        return guard_id

    def _select_guard_id(self, stage: str) -> int | None:
        from ..models.entities import Guard

        role = "leader" if stage == "escalated" else "primary"
        session = self._session()
        try:
            guard = (
                session.query(Guard)
                .filter(Guard.role == role)
                .order_by(Guard.priority.asc(), Guard.id.asc())
                .first()
            )
            return guard.id if guard else None
        finally:
            session.close()

    def _mark_notified(self, alarm_id: int, status: str) -> None:
        from ..models.entities import AlarmEvent

        session = self._session()
        try:
            alarm = session.get(AlarmEvent, alarm_id)
            if alarm is not None and alarm.status == "pending":
                alarm.status = status
                session.commit()
        except Exception:
            session.rollback()
            logger.exception("[dingtalk] 告警状态更新失败 alarm_id=%s", alarm_id)
            raise
        finally:
            session.close()

    def _write_log(self, alarm_id: int, guard_id: int | None, stage: str) -> None:
        from ..models.entities import NotificationLog

        session = self._session()
        try:
            session.add(NotificationLog(alarm_id=alarm_id, guard_id=guard_id, stage=stage))
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("[dingtalk] 通知日志写入失败 alarm_id=%s stage=%s", alarm_id, stage)
            raise
        finally:
            session.close()

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from ..models.database import SessionLocal
        return SessionLocal()


_default_notifier: DingTalkNotifier | None = None


def get_notifier() -> DingTalkNotifier:
    """返回进程内钉钉通知器单例，保留升级计时器。"""
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = DingTalkNotifier()
    return _default_notifier
