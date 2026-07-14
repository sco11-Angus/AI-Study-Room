"""人脸表情情绪识别 — 打架检测的情绪闸门 (任务书 D2-A)。

现状问题：打架检测音频侧只识别"音量"，分不清欢呼与怒吼；只要画面有
"贴身+快速运动"（追逐嬉闹同样满足）就可能误报。本模块引入人脸表情，
读 B 的人脸框裁脸，识别"愤怒/恐惧"等负面强情绪，作为告警**闸门**：
无负面情绪 -> 压制视觉冲突分 -> 滤掉欢乐场景误报。

设计约束（承袭任务书 D 红线）：
    - 复用 B 的人脸框（FaceBoxProvider），不重复做人脸检测。
    - 单例加载 HSEmotion ONNX，不自建线程。
    - 模型缺失 / 未启用 / 异常 -> 返回中性放行值 1.0（等价当前行为），绝不崩。
"""
import logging

import numpy as np

from ..config import Config
from .person_source import Box

logger = logging.getLogger(__name__)

# 驱动打架闸门的负面强情绪（HSEmotion 8 类中的标签，见 idx_to_class）
_NEGATIVE_EMOTIONS = ("Anger", "Fear")

# 无框 / 未启用 / 模型缺失时的返回值：1.0 = 完全放行，闸门不压制（等价原行为）
_NEUTRAL_PASSTHROUGH = 1.0


class FacialEmotion:
    """人脸表情情绪评分器 — 返回该帧「负面强情绪」概率 ∈ [0,1]。

    score(image, boxes): 对每个人脸框裁图 -> HSEmotion 推理 -> 取 anger+fear
    概率，返回全场峰值（最"负面"的那张脸）。

    延迟加载：首次 score() 时才建 recognizer（首帧慢，之后单例复用）；
    加载失败则永久降级为放行，不反复重试拖垮引擎。
    """

    def __init__(self):
        self._recognizer = None
        self._load_failed = False

    def setup(self) -> None:
        """引擎启动时预加载（可选）。失败不抛，留待运行期降级。"""
        if Config.EMOTION_ENABLE:
            self._ensure_recognizer()

    def _ensure_recognizer(self):
        if self._recognizer is not None or self._load_failed:
            return self._recognizer
        try:
            from hsemotion_onnx.facial_emotions import HSEmotionRecognizer

            self._recognizer = HSEmotionRecognizer(model_name=Config.EMOTION_MODEL_NAME)
            self._neg_idx = [
                i for i, name in self._recognizer.idx_to_class.items()
                if name in _NEGATIVE_EMOTIONS
            ]
            logger.info(
                "[emotion] HSEmotion 就绪 model=%s 负面类索引=%s",
                Config.EMOTION_MODEL_NAME, self._neg_idx,
            )
        except Exception:
            self._load_failed = True
            logger.exception("[emotion] HSEmotion 加载失败，情绪闸门降级为放行")
        return self._recognizer

    @staticmethod
    def _softmax(x: np.ndarray) -> np.ndarray:
        e = np.exp(x - np.max(x))
        return e / e.sum()

    def score(self, image: np.ndarray, boxes: list[Box]) -> float:
        """返回该帧负面情绪峰值 ∈ [0,1]；无法判断时返回 1.0（放行）。"""
        if not Config.EMOTION_ENABLE or not boxes or image is None:
            return _NEUTRAL_PASSTHROUGH
        rec = self._ensure_recognizer()
        if rec is None:
            return _NEUTRAL_PASSTHROUGH

        h, w = image.shape[:2]
        peak = 0.0
        seen = False
        for (x1, y1, x2, y2) in boxes:
            # 裁人脸；HSEmotion 期望 RGB，源图为 BGR，转一下
            xa, ya = max(0, int(x1)), max(0, int(y1))
            xb, yb = min(w, int(x2)), min(h, int(y2))
            if xb - xa < 8 or yb - ya < 8:
                continue
            crop = image[ya:yb, xa:xb][:, :, ::-1]  # BGR -> RGB
            try:
                _, scores = rec.predict_emotions(crop, logits=True)
            except Exception:
                logger.exception("[emotion] 单脸推理失败，跳过该框")
                continue
            probs = self._softmax(np.asarray(scores, dtype=np.float64))
            neg = float(sum(probs[i] for i in self._neg_idx))
            peak = max(peak, neg)
            seen = True

        # 有框但全部裁剪失败 -> 放行，避免误压
        return float(np.clip(peak, 0.0, 1.0)) if seen else _NEUTRAL_PASSTHROUGH
