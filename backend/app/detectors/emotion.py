"""SenseVoiceSmall-based emotion recognition for audio streams.

Uses Alibaba's SenseVoiceSmall model via funasr-onnx for:
1. Emotion recognition: ANGRY, SAD, HAPPY, NEUTRAL
2. Audio event detection: CRY (crying), BGM, APPLAUSE, LAUGHTER
3. Optional ASR text output (Chinese)

The model is optimized for Chinese environments and runs efficiently
on CPU via ONNX Runtime. On average, 10s of audio processes in ~70ms.
"""
import logging
import os
import time
from collections import deque

import numpy as np

from ..config import Config

logger = logging.getLogger(__name__)

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
