"""告警服务 — 闭环动作编排 (系统设计说明书 §7.1)。

真实告警产生时：
  ① 现场抓拍 -> 裁剪面部 -> 人脸识别匹配
  ② 看板异动 -> WebSocket 推送前端(绿->红闪+蜂鸣)
  ③ 钉钉逐级上报(见 dingtalk.py)
同防区同类型在冷却窗口内合并去重 (§10.2)。
"""
import time
from datetime import datetime


class AlarmService:
    def __init__(self, cooldown: int = 30):
        self.cooldown = cooldown
        self._last_fired: dict = {}  # (region_id, type) -> ts

    def _dedup(self, region_id: int, type_: str) -> bool:
        key = (region_id, type_)
        now = time.time()
        if now - self._last_fired.get(key, 0) < self.cooldown:
            return False
        self._last_fired[key] = now
        return True

    def raise_alarm(self, region_id: int, type_: str, frame, extra: dict = None):
        """触发告警闭环。"""
        if type_ == "face_recognition":
            # 人脸识别走轻量推送通道（不触发钉钉，不入库告警）
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
            return

        if not self._dedup(region_id, type_):
            return
        # ① 抓拍落盘 + 裁剪面部 -> FaceMatcher.match
        # ② push_to_dashboard(...)  经 WebSocket
        # ③ DingTalkNotifier.notify(alarm)  启动 3min 升级计时
        ...
