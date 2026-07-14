"""YAMNet-based semantic audio event detection for abnormal sound events.

Uses torch-vggish-yamnet — a ready-to-use PyTorch port of YAMNet with
pretrained weights (~14MB, auto-downloaded on first use). No TensorFlow.
Detects screams, crying, glass breaking, shouting, gunshots, explosions,
and thud/impact sounds. Falls back to DSP features when YAMNet unavailable.
"""
import logging
import time
from collections import deque

import numpy as np

from ..config import Config

logger = logging.getLogger(__name__)


def _load_class_names() -> list[str]:
    """Load YAMNet AudioSet 521 class names from bundled CSV."""
    import csv
    import os
    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "yamnet_class_map.csv")
    names = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and row[0].isdigit():
                    names.append(row[2])
        logger.info("[audio_event] loaded %d class names from %s", len(names), csv_path)
    except Exception:
        logger.exception("[audio_event] failed to load class names from CSV")
    return names

# AudioSet class names → our simplified event labels
_ABNORMAL_CLASSES = {
    "Shout": "Shout",
    "Scream": "Scream",
    "Yell": "Yell",
    "Crying, sobbing": "Crying",
    "Crying": "Crying",
    "Groan": "Groan",
    "Glass": "Glass",
    "Shatter": "Shatter",
    "Gunshot, gunfire": "Gunshot",
    "Explosion": "Explosion",
    "Thump, thud": "Thump",
    "Bang": "Bang",
    "Crash": "Crash",
    "Howl": "Howl",
}


class AudioEventDetector:
    """YAMNet semantic audio event classifier via torch-vggish-yamnet.

    Detects abnormal sounds from 16kHz mono PCM. Falls back to DSP features
    if the torch-vggish-yamnet package or model cannot be loaded.
    """

    def __init__(self):
        self._model = None
        self._converter = None
        self._class_names: list[str] = []
        self._yamnet_loaded = False
        self._fallback = YamnetFallbackDetector()
        self._last_event: str | None = None
        self._last_confidence: float = 0.0
        self._last_embedding: np.ndarray | None = None
        self._abnormal_indices: dict[int, str] = {}

    def setup(self) -> None:
        """Load YAMNet from torch-vggish-yamnet (auto-downloads weights)."""
        if not Config.YAMNET_ENABLED:
            logger.info("[audio_event] YAMNet disabled by config")
            return
        try:
            import torch
            from torch_vggish_yamnet import yamnet
            from torch_vggish_yamnet.input_proc import WaveformToInput

            self._model = yamnet.yamnet(pretrained=True)
            self._model.eval()
            self._converter = WaveformToInput()
            self._class_names = _load_class_names()  # 521 AudioSet class names

            # Build abnormal class index map
            class_lower = [c.lower() for c in self._class_names]
            for ab_name, our_name in _ABNORMAL_CLASSES.items():
                key = ab_name.lower()
                for i, cls_lower in enumerate(class_lower):
                    if key == cls_lower or key in cls_lower:
                        self._abnormal_indices[i] = our_name
                        break

            # Warm-up: need at least ~1s audio for STFT to work (256 padding)
            # 0.2.1 WaveformToInput 需 2D [channels, time]
            dummy_wav = torch.zeros((1, 48000), dtype=torch.float32)
            dummy_mel = self._converter(dummy_wav, 16000)
            with torch.no_grad():
                self._model(dummy_mel)
            self._yamnet_loaded = True
            logger.info("[audio_event] torch-vggish-yamnet loaded — %d classes, %d abnormal mapped",
                       len(self._class_names), len(self._abnormal_indices))
        except ImportError as e:
            logger.warning("[audio_event] %s — YAMNet unavailable, using DSP fallback", e)
        except Exception:
            logger.exception("[audio_event] YAMNet loading failed — using DSP fallback")

    def predict(self, pcm: np.ndarray, sample_rate: int = 16000) -> dict:
        """Run YAMNet inference on PCM audio.

        Returns:
            dict with: event (str|None), confidence (float),
            embedding (np.ndarray|None), all_events (list of {event, confidence}).
        """
        if not self._yamnet_loaded:
            return self._fallback.predict(pcm, sample_rate)

        try:
            import torch

            if sample_rate != 16000:
                pcm = self._resample(pcm, sample_rate, 16000)

            # Convert waveform to log-mel spectrogram
            # torch-vggish-yamnet 0.2.1 的 WaveformToInput 期望 2D [channels, time]，
            # 故给 1D PCM 补一个通道维。
            waveform = torch.from_numpy(pcm.astype(np.float32)).unsqueeze(0)
            mel = self._converter(waveform, 16000)  # (1, 1, 64, T)

            with torch.no_grad():
                embeddings, scores = self._model(mel)
            # torch-vggish-yamnet 0.2.1 输出: scores (num_chunks, 521),
            # embeddings (num_chunks, 1024, 1, 1)。对 chunk 维取均值得整段表示。
            mean_scores = scores.mean(dim=0).numpy()  # (521,)
            mean_embedding = embeddings.reshape(embeddings.shape[0], -1).mean(dim=0).numpy()  # (1024,)

            best_event = None
            best_conf = 0.0
            all_events = []

            for idx, event_name in self._abnormal_indices.items():
                if idx < len(mean_scores):
                    conf = float(mean_scores[idx])
                    if conf > best_conf:
                        best_conf = conf
                        best_event = event_name
                    if conf >= Config.YAMNET_CONF_THRESH:
                        all_events.append({"event": event_name, "confidence": round(conf, 4)})

            all_events.sort(key=lambda x: x["confidence"], reverse=True)

            self._last_event = best_event if best_conf >= Config.YAMNET_CONF_THRESH else None
            self._last_confidence = best_conf
            self._last_embedding = mean_embedding

            return {
                "event": self._last_event,
                "confidence": round(best_conf, 4),
                "embedding": self._last_embedding,
                "all_events": all_events,
            }
        except Exception:
            logger.exception("[audio_event] YAMNet inference failed — using DSP fallback")
            return self._fallback.predict(pcm, sample_rate)

    def is_abnormal(self, event: str | None, confidence: float) -> bool:
        if event is None:
            return False
        return confidence >= Config.ABNORMAL_SOUND_CONF

    @staticmethod
    def _resample(pcm: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        if orig_sr == target_sr:
            return pcm
        from scipy import signal
        target_len = int(len(pcm) / orig_sr * target_sr)
        return signal.resample(pcm, target_len)

    @property
    def last_event(self) -> str | None:
        return self._last_event

    @property
    def last_confidence(self) -> float:
        return self._last_confidence

    @property
    def last_embedding(self) -> np.ndarray | None:
        return self._last_embedding


class YamnetFallbackDetector:
    """DSP-based fallback when YAMNet is unavailable."""

    def __init__(self, hist: int = 5, rms_ref_db: float = -20.0):
        self.rms_ref_db = rms_ref_db
        self._energy_hist: deque = deque(maxlen=hist)

    def predict(self, pcm: np.ndarray, sample_rate: int = 16000) -> dict:
        db = self._rms_dbfs(pcm)
        loud = np.clip((db - (-60.0)) / (self.rms_ref_db - (-60.0)), 0.0, 1.0)

        burst = 0.0
        if self._energy_hist:
            base = float(np.mean(self._energy_hist))
            burst = np.clip((loud - base) / 0.3, 0.0, 1.0)
        self._energy_hist.append(loud)

        is_loud = loud > 0.6
        event = "LoudSound" if (is_loud and burst > 0.3) else None
        confidence = float(loud) if event else 0.0

        return {
            "event": event,
            "confidence": round(confidence, 4),
            "embedding": None,
            "all_events": [{"event": event, "confidence": round(confidence, 4)}] if event else [],
        }

    @staticmethod
    def _rms_dbfs(pcm: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(pcm)))) if pcm.size else 0.0
        if rms <= 1e-8:
            return -120.0
        return 20.0 * np.log10(rms)


# ─── AbnormalSoundPlugin ───

class AbnormalSoundPlugin:
    """Detector plugin for standalone abnormal sound alarms."""

    name = "abnormal_sound"
    enabled = True

    def __init__(self, audio_detector: AudioEventDetector | None = None):
        self._audio = audio_detector or AudioEventDetector()
        self._candidate_since: float | None = None
        self._candidate_event: str | None = None
        self._candidate_conf: float = 0.0
        self._detected_events: list[str] = []
        self._last_vis_score: float = 0.0
        self._fired: bool = False
        self._last_chunk_ts: float = 0.0
        self._alarm_raised_ts: float = 0.0

    def setup(self) -> None:
        self._audio.setup()
        logger.info("[abnormal_sound] plugin ready")

    def feed_audio(self, chunk) -> None:
        result = self._audio.predict(chunk.pcm, chunk.sample_rate)
        event = result["event"]
        conf = result["confidence"]

        ts = chunk.ts if hasattr(chunk, "ts") else time.time()
        self._last_chunk_ts = ts

        if event is not None and conf >= Config.ABNORMAL_SOUND_CONF:
            if self._candidate_since is None:
                self._candidate_since = ts
                self._candidate_event = event
                self._candidate_conf = conf
                self._detected_events = [event]
            else:
                if event not in self._detected_events:
                    self._detected_events.append(event)
                if conf > self._candidate_conf:
                    self._candidate_event = event
                    self._candidate_conf = conf
                if ts - self._candidate_since >= Config.ABNORMAL_SOUND_DURATION:
                    if not self._fired:
                        self._fired = True
        else:
            if self._candidate_since is not None and \
                    ts - self._candidate_since > Config.ABNORMAL_SOUND_DURATION * 2:
                self._candidate_since = None
                self._candidate_event = None
                self._candidate_conf = 0.0
                self._detected_events = []
                self._fired = False

    def set_vis_score(self, vis_score: float) -> None:
        self._last_vis_score = vis_score

    def should_alarm(self) -> tuple[bool, str | None, float]:
        if not self._fired:
            return False, None, 0.0
        if self._last_vis_score > 0.5:
            return False, None, 0.0
        return True, self._candidate_event, self._candidate_conf

    def reset(self) -> None:
        self._fired = False
        self._alarm_raised_ts = time.time()
        self._candidate_since = time.time()

    def detect(self, frame) -> list:
        from .base import AlarmEvent

        should_alarm, event_name, conf = self.should_alarm()
        if not should_alarm:
            return []

        if self._alarm_raised_ts > 0 and \
                time.time() - self._alarm_raised_ts < Config.ABNORMAL_SOUND_DURATION * 2:
            return []

        self.reset()

        events_list = self._detected_events[:]
        extra = {
            "audio_event": event_name,
            "audio_confidence": round(conf, 4),
            "detected_events": events_list,
            "camera_id": frame.camera_id if hasattr(frame, "camera_id") else 0,
            "level": 1,
        }

        logger.warning("[abnormal_sound] 异常声音告警 event=%s conf=%.3f events=%s",
                      event_name, conf, events_list)

        return [AlarmEvent(
            region_id=0,
            type="abnormal_sound",
            confidence=conf,
            snapshot=frame.image if hasattr(frame, "image") else None,
            extra=extra,
        )]
