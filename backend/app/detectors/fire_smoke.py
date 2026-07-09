"""烟雾/明火检测 — 连续帧置信度加权防误报 (系统设计说明书 §6)。

连续 FIRE_WINDOW(30) 帧中 fire/smoke 平均置信度 > FIRE_CONF(0.45) 才判定有效灾情。
"""
from collections import deque

from ..config import Config

class FireSmokePlugin(Detector):
    name = "fire_smoke"

    def setup(self):
        # 加载 YOLO 权重

    def detect(self, frame: Frame) -> list[AlarmEvent]:
        # YOLO 推理
        # 找 fire/smoke 最大置信度
        # 送入 self._debouncer.feed(conf)
        # 命中后返回 AlarmEvent(type="fire_smoke")
    def feed(self, conf: float) -> bool:
        """每次有效推理送入本帧 fire/smoke 置信度（未检出送 0）。

        返回是否判定为有效灾情。
        """
        self._window.append(conf)
        if len(self._window) < Config.FIRE_WINDOW:
            return False
        return (sum(self._window) / len(self._window)) > Config.FIRE_CONF

