"""疲劳检测 — Dlib 68 点人脸 EAR/MAR (系统设计说明书 §4.3)。

仅当座位状态为 studying 时激活；resting 时挂起以释放算力 (§4.2)。
弱提醒推送该用户专属屏幕/手机，不拉公用警报。
"""
from ..config import Config


def eye_aspect_ratio(eye) -> float:
    """EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)。"""
    import numpy as np
    a = np.linalg.norm(eye[1] - eye[5])
    b = np.linalg.norm(eye[2] - eye[4])
    c = np.linalg.norm(eye[0] - eye[3])
    return (a + b) / (2.0 * c)


def mouth_aspect_ratio(mouth) -> float:
    """MAR — 打哈欠判定。"""
    import numpy as np
    a = np.linalg.norm(mouth[2] - mouth[10])
    b = np.linalg.norm(mouth[4] - mouth[8])
    c = np.linalg.norm(mouth[0] - mouth[6])
    return (a + b) / (2.0 * c)


class FatigueDetector:
    """按座位维护闭眼持续时间，EAR<阈值持续≥2s 或 MAR 超标 -> 弱提醒。"""

    def __init__(self):
        self._closed_since = None  # 闭眼起始时间戳

    def detect(self, landmarks, ts: float) -> str | None:
        # TODO: 用 dlib 关键点计算 EAR/MAR，累计 EAR_DURATION 判定
        # 返回 "sleepy" / "yawn" / None
        ...
