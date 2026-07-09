"""DingTalk alarm notification and close-loop workflow."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests

from ..config import Config

logger = logging.getLogger(__name__)


class DingTalkNotifier:
    """Send ActionCard messages and maintain confirm/escalation state."""

    def __init__(
        self,
        webhook: str | None = None,
        leader_webhook: str | None = None,
        secret: str | None = None,
        leader_secret: str | None = None,
        public_base_url: str | None = None,
        timeout: int | None = None,
        session_factory=None,
        http_post=None,
    ):
        self.webhook = webhook if webhook is not None else Config.DINGTALK_WEBHOOK
        self.secret = secret if secret is not None else Config.DINGTALK_SECRET

        configured_leader_webhook = (
            leader_webhook if leader_webhook is not None else Config.DINGTALK_LEADER_WEBHOOK
        )
        self.leader_webhook = configured_leader_webhook or self.webhook
        configured_leader_secret = (
            leader_secret if leader_secret is not None else Config.DINGTALK_LEADER_SECRET
        )
        self.leader_secret = configured_leader_secret or (
            self.secret if self.leader_webhook == self.webhook else ""
        )

        base_url = public_base_url if public_base_url is not None else Config.PUBLIC_BASE_URL
        self.public_base_url = base_url.rstrip("/") if base_url else ""
        self.timeout = Config.ESCALATE_TIMEOUT if timeout is None else timeout
        self._session_factory = session_factory
        self._http_post = http_post or requests.post
        self._timers: dict[int, threading.Timer] = {}

    def notify(self, alarm_id: int, title: str | None = None, text: str | None = None):
        """Notify the primary guard and start the escalation timer."""
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
        """Confirm an alarm, cancel its timer, and mark notification logs as acked."""
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
            logger.exception("[dingtalk] failed to confirm alarm_id=%s", alarm_id)
            raise
        finally:
            session.close()

    def _escalate(self, alarm_id: int):
        """Escalate an unconfirmed alarm and notify the leader guard."""
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
            logger.exception("[dingtalk] failed to escalate alarm_id=%s", alarm_id)
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
                base_title = title or f"Alarm {alarm_id}"
                return base_title, text or "Alarm not found or deleted."

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
                f"- Alarm ID: {alarm.id}",
                f"- Type: {alarm.type}",
                f"- Camera: {alarm.camera_id or '-'}",
                f"- Region: {alarm.region_id or '-'}",
                f"- Level: {alarm.level}",
                f"- Time: {created}",
            ]
            if alarm.snapshot_url:
                lines.append(f"- Snapshot: {self._public_url(alarm.snapshot_url)}")
            if alarm.face_match:
                lines.append(f"- Face: {alarm.face_match}")
            if extra:
                lines.append(f"- Extra: `{json.dumps(extra, ensure_ascii=False)}`")
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
                "singleURL": self._public_url(f"/api/alarms/{alarm_id}/confirm"),
            },
        }
        webhook = self.leader_webhook if guard_stage == "escalated" else self.webhook
        secret = self.leader_secret if guard_stage == "escalated" else self.secret
        if webhook:
            try:
                self._http_post(self._webhook_url(webhook, secret), json=payload, timeout=5)
            except Exception:
                logger.exception(
                    "[dingtalk] failed to send ActionCard stage=%s alarm_id=%s",
                    guard_stage,
                    alarm_id,
                )
        else:
            logger.info("[dingtalk] webhook not configured; log only stage=%s alarm_id=%s", guard_stage, alarm_id)
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
            logger.exception("[dingtalk] failed to update alarm status alarm_id=%s", alarm_id)
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
            logger.exception("[dingtalk] failed to write notification log alarm_id=%s stage=%s", alarm_id, stage)
            raise
        finally:
            session.close()

    def _public_url(self, path_or_url: str) -> str:
        if not path_or_url:
            return ""
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        if not self.public_base_url:
            return path_or_url
        path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
        return f"{self.public_base_url}{path}"

    def _webhook_url(self, webhook: str, secret: str) -> str:
        if not secret:
            return webhook
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
        sign = quote_plus(base64.b64encode(digest))
        separator = "&" if "?" in webhook else "?"
        return f"{webhook}{separator}timestamp={timestamp}&sign={sign}"

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from ..models.database import SessionLocal

        return SessionLocal()


_default_notifier: DingTalkNotifier | None = None


def get_notifier() -> DingTalkNotifier:
    """Return the process-local notifier singleton to preserve timers."""
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = DingTalkNotifier()
    return _default_notifier
