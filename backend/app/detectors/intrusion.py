"""防区入侵检测 — YOLOv8n + 几何判定 + 时空防抖 (系统设计说明书 §5.3, §5.4)。"""
import time

import cv2
import numpy as np


class IntrusionDetector:
    """对单个防区维护危险计时状态机 (SAFE / COUNTING / ALARM)。"""

    def __init__(self, polygon: list, x_distance: int, y_stay_time: int):
        self.polygon = np.array(polygon, dtype=np.int32)
        self.x_distance = x_distance
        self.y_stay_time = y_stay_time
        self._danger_since = None  # 危险起始时间戳（无间断累计）

    @staticmethod
    def base_point(box) -> tuple[int, int]:
        """人员检测框底边中心点 (cx, cy) — 近似双脚坐标 (§5.3)。"""
        x1, y1, x2, y2 = box
        return int((x1 + x2) / 2), int(y2)

    def judge(self, box, ts: float) -> bool:
        """返回是否触发告警。"""
        cx, cy = self.base_point(box)
        d = cv2.pointPolygonTest(self.polygon, (cx, cy), True)

        in_danger = d >= 0 or (d < 0 and abs(d) <= self.x_distance)  # ①②
        if in_danger:
            if self._danger_since is None:
                self._danger_since = ts
            elif ts - self._danger_since >= self.y_stay_time:
                return True  # 无间断累计达阈值 -> ALARM (§5.4)
        else:
            self._danger_since = None  # 回到安全立即清零，防抖动
        return False
