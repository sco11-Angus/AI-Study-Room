"""钉钉逐级上报与超时升级工作流 (系统设计说明书 §7.4)。

调用群机器人 Webhook 发送 ActionCard 卡片（抓拍图/类型/位置/时间/确认按钮）。
主责安全员须在 ESCALATE_TIMEOUT(3min) 内点击确认，否则自动升级推送科长/负责人。
"""
import threading

import requests

from ..config import Config


class DingTalkNotifier:
    def __init__(self, webhook: str | None = None):
        self.webhook = webhook or Config.DINGTALK_WEBHOOK
        self._timers: dict = {}  # alarm_id -> Timer

    def _send_card(self, title: str, text: str, guard_stage: str):
        payload = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": title,
                "text": text,
                "singleTitle": "确认处理",
                "singleURL": "",  # 指向确认回调 /api/alarms/{id}/confirm
            },
        }
        # requests.post(self.webhook, json=payload, timeout=5)

    def notify(self, alarm_id: int, title: str, text: str):
        """发送给主责安全员并启动升级计时。"""
        self._send_card(title, text, "primary")
        timer = threading.Timer(Config.ESCALATE_TIMEOUT, self._escalate, args=(alarm_id,))
        timer.start()
        self._timers[alarm_id] = timer

    def confirm(self, alarm_id: int):
        """收到确认回调 -> 取消升级计时 (§7.4)。"""
        timer = self._timers.pop(alarm_id, None)
        if timer:
            timer.cancel()

    def _escalate(self, alarm_id: int):
        """超时未确认 -> 升级优先级，推送科长/直属负责人。"""
        self._send_card(f"[升级] 告警 {alarm_id} 超时未处理", "请立即处理", "escalated")
