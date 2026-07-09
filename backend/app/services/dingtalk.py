"""DingTalk alarm notification and close-loop workflow."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests

from ..config import Config

logger = logging.getLogger(__name__)


ALARM_TYPE_LABELS = {
    "intrusion": "\u5165\u4fb5\u544a\u8b66",
    "fire_smoke": "\u70df\u706b\u544a\u8b66",
    "occupy": "\u5360\u5ea7\u544a\u8b66",
    "fatigue": "\u75b2\u52b3\u63d0\u9192",
    "fight": "\u6253\u67b6\u544a\u8b66",
}

DEFAULT_BEHAVIORS = {
    "intrusion": "\u8fdb\u5165\u6216\u957f\u65f6\u95f4\u505c\u7559\u5728\u9632\u533a",
    "fire_smoke": "\u51fa\u73b0\u7591\u4f3c\u70df\u96fe\u6216\u660e\u706b",
    "occupy": "\u5360\u7528\u5ea7\u4f4d\u6216\u975e\u6cd5\u4f7f\u7528\u5ea7\u4f4d",
    "fatigue": "\u51fa\u73b0\u95ed\u773c\u3001\u6253\u54c8\u6b20\u7b49\u75b2\u52b3\u5b66\u4e60\u884c\u4e3a",
    "fight": "\u51fa\u73b0\u7591\u4f3c\u6253\u67b6\u6216\u80a2\u4f53\u51b2\u7a81\u884c\u4e3a",
}

ACTOR_KEYS = (
    "actor",
    "person",
    "person_name",
    "student",
    "student_name",
    "member_name",
    "nickname",
    "name",
)

BEHAVIOR_KEYS = ("behavior", "action", "reason", "trigger", "description")


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
        payload_title, payload_text = self._build_card_v2(alarm_id, title, text, "primary")
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

        title, text = self._build_card_v2(alarm_id, None, None, "escalated")
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

    def _build_card_v2(
        self,
        alarm_id: int,
        title: str | None,
        text: str | None,
        stage: str,
    ) -> tuple[str, str]:
        from ..models.entities import AlarmEvent, AppUser, Camera, Member, Region

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

            region = session.get(Region, alarm.region_id) if alarm.region_id else None
            camera = session.get(Camera, alarm.camera_id) if alarm.camera_id else None
            app_user = session.get(AppUser, region.user_id) if region and region.user_id else None
            handler = self._select_guard_info(stage)
            actor = self._resolve_actor(session, alarm, extra, app_user, Member)
            behavior = self._resolve_behavior(alarm.type, extra)
            type_label = ALARM_TYPE_LABELS.get(alarm.type, alarm.type)
            stage_text = "\u5347\u7ea7\u544a\u8b66" if stage == "escalated" else "\u5b89\u5168\u544a\u8b66"
            handler_name = handler.get("name") or "\u672a\u914d\u7f6e"
            location = region.name if region and region.name else f"Region {alarm.region_id or '-'}"
            camera_name = camera.name if camera and camera.name else f"Camera {alarm.camera_id or '-'}"
            base_title = title or f"{stage_text}: {type_label}"
            created = alarm.created_at.isoformat() if alarm.created_at else ""

            lines = [
                f"### {base_title}",
                f"- \u544a\u8b66ID: {alarm.id}",
                f"- \u89e6\u53d1\u4eba: {actor}",
                f"- \u89e6\u53d1\u884c\u4e3a: {behavior}",
                f"- \u544a\u8b66\u7c7b\u578b: {type_label}",
                f"- \u5904\u7406\u4eba: {handler_name}",
                f"- \u4f4d\u7f6e: {location}",
                f"- \u6444\u50cf\u5934: {camera_name}",
                f"- \u7ea7\u522b: {alarm.level}",
                f"- \u65f6\u95f4: {created}",
            ]
            if alarm.snapshot_url:
                lines.append(f"- \u6293\u62cd: {self._public_url(alarm.snapshot_url)}")
            if alarm.face_match:
                lines.append(f"- \u4eba\u8138\u5339\u914d: {alarm.face_match}")
            score_text = self._score_summary(extra)
            if score_text:
                lines.append(f"- \u68c0\u6d4b\u4f9d\u636e: {score_text}")
            return base_title, text or "\n".join(lines)
        finally:
            session.close()

    def _send_card(self, alarm_id: int, title: str, text: str, guard_stage: str) -> int | None:
        guard = self._select_guard_info(guard_stage)
        guard_id = guard.get("id")
        payload = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": title,
                "text": text,
                "singleTitle": "确认处理",
                "singleURL": self._public_url(f"/api/alarms/{alarm_id}/confirm"),
            },
        }
        payload["actionCard"]["singleTitle"] = "\u786e\u8ba4\u5904\u7406"
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
        self._send_handler_mention(alarm_id, guard, guard_stage, webhook, secret)
        return guard_id

    def _send_handler_mention(
        self,
        alarm_id: int,
        guard: dict,
        guard_stage: str,
        webhook: str,
        secret: str,
    ) -> None:
        target = (guard.get("dingtalk_id") or "").strip()
        if not webhook or not target:
            return

        handler_name = guard.get("name") or target
        mention_text, at_payload = self._mention_payload(target, handler_name)
        stage_text = "\u5347\u7ea7\u544a\u8b66" if guard_stage == "escalated" else "\u5b89\u5168\u544a\u8b66"
        payload = {
            "msgtype": "text",
            "text": {
                "content": (
                    f"{mention_text} {stage_text}\u9700\u8981\u5904\u7406\uff1a"
                    f"\u8bf7\u67e5\u770b\u4e0a\u65b9\u544a\u8b66\u5361\u7247\uff0c"
                    f"\u5e76\u70b9\u51fb\u786e\u8ba4\u5904\u7406\u3002Alarm ID: {alarm_id}"
                )
            },
            "at": at_payload,
        }
        try:
            self._http_post(self._webhook_url(webhook, secret), json=payload, timeout=5)
        except Exception:
            logger.exception(
                "[dingtalk] failed to send @ mention stage=%s alarm_id=%s guard_id=%s",
                guard_stage,
                alarm_id,
                guard.get("id"),
            )

    def _mention_payload(self, dingtalk_id: str, handler_name: str) -> tuple[str, dict]:
        if re.fullmatch(r"\d{11}", dingtalk_id):
            return f"@{dingtalk_id}", {"atMobiles": [dingtalk_id], "isAtAll": False}
        return f"@{handler_name}", {"atUserIds": [dingtalk_id], "isAtAll": False}

    def _select_guard_id(self, stage: str) -> int | None:
        return self._select_guard_info(stage).get("id")

    def _select_guard_info(self, stage: str) -> dict:
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
            if guard is None:
                return {}
            return {
                "id": guard.id,
                "name": guard.name or "",
                "dingtalk_id": guard.dingtalk_id or "",
                "role": guard.role or role,
            }
        finally:
            session.close()

    def _resolve_actor(self, session, alarm, extra: dict, app_user, member_model) -> str:
        for key in ACTOR_KEYS:
            value = extra.get(key)
            if value:
                return str(value)

        face_match = alarm.face_match or ""
        if face_match.startswith("member:"):
            try:
                member_id = int(face_match.split(":", 1)[1])
            except ValueError:
                member_id = None
            if member_id is not None:
                member = session.get(member_model, member_id)
                if member and member.name:
                    return member.name
            return face_match

        if app_user is not None and app_user.nickname and alarm.type in {"fatigue", "occupy"}:
            return app_user.nickname
        if face_match == "stranger":
            return "\u964c\u751f\u4eba"
        if app_user is not None and app_user.nickname:
            return app_user.nickname
        return "\u672a\u77e5\u4eba\u5458"

    def _resolve_behavior(self, alarm_type: str, extra: dict) -> str:
        for key in BEHAVIOR_KEYS:
            value = extra.get(key)
            if value:
                return str(value)
        return DEFAULT_BEHAVIORS.get(alarm_type, "\u89e6\u53d1\u544a\u8b66\u89c4\u5219")

    def _score_summary(self, extra: dict) -> str:
        keys = (
            "confidence",
            "score",
            "vis_score",
            "aud_score",
            "fuse",
            "stay_seconds",
            "duration",
        )
        parts = [f"{key}={extra[key]}" for key in keys if key in extra]
        return ", ".join(parts)

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
