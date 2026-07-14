"""情绪识别 — 双模态合一模块。

本文件整合两套情绪能力，供打架检测三模态融合使用：

A) FacialEmotion（任务书 D2-A，人脸表情闸门 / HSEmotion ONNX）
   读 B 的人脸框裁脸，识别"愤怒/恐惧"等负面强情绪，作为告警闸门：
   无负面情绪 -> 压制视觉冲突分 -> 滤掉欢乐场景误报。
   约束：复用人脸框、单例加载、模型缺失/异常返回放行值 1.0 绝不崩。

B) EmotionRecognizer（taskA，声学情绪 / SenseVoiceSmall via funasr-onnx）
   音频流情绪识别(ANGRY/SAD/HAPPY/NEUTRAL) + 声学事件(CRY/BGM/...)，
   CPU ONNX 高效运行，供音视频联动与三模态融合。
"""
import logging
import os
import time
from collections import deque

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


# ==================== 以下为 taskA 声学情绪 (SenseVoiceSmall) ====================

_RISKY_EMOTIONS = {"ANGRY", "SAD"}
_RISKY_EVENTS = {"CRY"}
# Known SenseVoiceSmall tag categories
_KNOWN_EMOTIONS = {"NEUTRAL", "ANGRY", "SAD", "HAPPY", "SURPRISED", "FEARFUL", "DISGUSTED"}
_KNOWN_EVENTS = {"Speech", "BGM", "Applause", "Laughter", "Cry", "Cough", "Sneeze", "Scream", "Cheer"}
_SKIP_TAGS = {"withitn", "woitn", "zh", "en", "ko", "ja", "yue", "EMO_UNKNOWN"}


def _parse_sensevoice_tags(text: str) -> tuple[str, str | None, str | None]:
    """Parse SenseVoiceSmall tag-based output format.

    Format: <|lang|><|EMOTION|><|event|><|itn|>transcription

    Returns:
        (emotion, audio_event, transcription)
    """
    import re
    tags = re.findall(r'<\|([^|]+)\|>', text)
    # Remove tag portion to get raw transcription
    transcription = re.sub(r'<\|[^|]+\|>', '', text).strip() or None

    emotion = "NEUTRAL"
    audio_event = None

    for tag in tags:
        upper = tag.upper()
        if upper in _KNOWN_EMOTIONS:
            emotion = upper
        elif tag in _KNOWN_EVENTS:
            # Use last event (most specific typically comes last)
            audio_event = tag
        # skip known meta tags

    return emotion, audio_event, transcription


class EmotionRecognizer:
    """SenseVoiceSmall emotion + event recognizer.

    Loads SenseVoiceSmall ONNX model via funasr-onnx for efficient CPU
    inference. Outputs emotion label, audio event tags, and optionally
    ASR transcription. Gracefully degrades if the model is unavailable.
    """

    def __init__(self, model_path: str | None = None):
        self._model = None
        self._loaded = False
        self._model_path = model_path or Config.EMOTION_MODEL_PATH or "iic/SenseVoiceSmall"
        # Rolling buffer: accumulate enough audio before inference
        self._audio_buf: list[np.ndarray] = []
        self._buf_duration: float = 0.0
        self._min_duration: float = 2.0     # Minimum audio for reliable emotion inference
        self._infer_interval: float = 2.0    # Run inference every 2 seconds
        self._last_infer_time: float = 0.0
        # Latest results
        self._last_emotion: str = "NEUTRAL"
        self._last_confidence: float = 0.0
        self._last_event: str | None = None
        self._last_text: str | None = None

    def setup(self) -> None:
        """Load SenseVoiceSmall ONNX model."""
        if not Config.EMOTION_ENABLED:
            logger.info("[emotion] Emotion recognition disabled by config")
            return
        try:
            from funasr_onnx import SenseVoiceSmall
            quantize = True  # Use int8 quantization for faster CPU inference
            self._model = SenseVoiceSmall(self._model_path, quantize=quantize)
            self._loaded = True
            logger.info("[emotion] SenseVoiceSmall loaded (model=%s, quantize=%s)", 
                       self._model_path, quantize)
        except ImportError:
            logger.warning("[emotion] funasr-onnx not installed — emotion recognition unavailable")
        except Exception:
            logger.exception("[emotion] SenseVoiceSmall loading failed")

    def feed(self, pcm: np.ndarray, sample_rate: int = 16000) -> None:
        """Accumulate audio for periodic emotion inference."""
        if not self._loaded:
            return
        self._audio_buf.append(pcm.astype(np.float32))
        self._buf_duration += len(pcm) / sample_rate

        # Run inference when we have enough audio and interval has passed
        now = time.time()
        if (self._buf_duration >= self._min_duration and 
            now - self._last_infer_time >= self._infer_interval):
            self._run_inference(sample_rate)

    def _run_inference(self, sample_rate: int) -> None:
        """Concatenate buffered audio and run SenseVoiceSmall."""
        try:
            audio = np.concatenate(self._audio_buf)
            # Keep the most recent 10s max to avoid memory growth
            max_samples = 10 * sample_rate
            if len(audio) > max_samples:
                audio = audio[-max_samples:]

            # Clear buffer, keep last ~1s for overlap
            keep_samples = int(1.0 * sample_rate)
            if len(audio) > keep_samples:
                self._audio_buf = [audio[-keep_samples:]]
            else:
                self._audio_buf = []
            self._buf_duration = len(self._audio_buf[-1]) / sample_rate if self._audio_buf else 0.0

            # Save audio to temp file (funasr-onnx requires file path or raw PCM)
            import tempfile
            import wave
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
                wf.writeframes(audio_int16.tobytes())

            # Run inference
            result = self._model(tmp_path)
            os.unlink(tmp_path)

            if result and len(result) > 0:
                r = result[0]
                # SenseVoiceSmall outputs a tag-based format:
                # <|lang|><|EMOTION|><|event|><|withitn|>text
                self._last_infer_time = time.time()

                if isinstance(r, str):
                    # Parse tag-based output
                    self._last_emotion, self._last_event, self._last_text = _parse_sensevoice_tags(r)
                elif isinstance(r, dict):
                    # Fallback: dict-style output (older funasr-onnx versions)
                    emo_tag = r.get("emo", "NEUTRAL")
                    if isinstance(emo_tag, str):
                        self._last_emotion = emo_tag.upper()
                    events = r.get("event", [])
                    if events:
                        event_tags = [e.get("event") for e in events if e.get("event")]
                        risky = [t for t in event_tags if t in _RISKY_EVENTS]
                        self._last_event = risky[0] if risky else (event_tags[0] if event_tags else None)
                    self._last_text = r.get("text", None)

                if self._last_emotion in _RISKY_EMOTIONS or self._last_event:
                    logger.info("[emotion] emotion=%s event=%s",
                               self._last_emotion, self._last_event)
        except Exception:
            logger.exception("[emotion] inference failed")

    def predict(self) -> dict:
        """Get latest emotion prediction result.

        Returns:
            dict with keys: emotion, emotion_confidence, audio_event, text,
            is_risky (bool).
        """
        return {
            "emotion": self._last_emotion,
            "emotion_confidence": round(self._last_confidence, 4),
            "audio_event": self._last_event,
            "text": self._last_text,
            "is_risky": self.is_risky(self._last_emotion) or self._last_event in _RISKY_EVENTS,
        }

    @staticmethod
    def is_risky(emotion: str) -> bool:
        """Check if emotion is considered risky (ANGRY/SAD)."""
        return emotion.upper() in _RISKY_EMOTIONS

    def get_emotion_risk_score(self) -> float:
        """Convert latest emotion to a [0, 1] risk score for fusion."""
        if not self._loaded:
            return 0.0
        emo = self._last_emotion.upper()
        if emo == "ANGRY":
            return min(1.0, self._last_confidence * 1.0)
        elif emo == "SAD":
            return min(1.0, self._last_confidence * 0.5)
        return 0.0

    @property
    def emotion(self) -> str:
        return self._last_emotion

    @property
    def loaded(self) -> bool:
        return self._loaded
