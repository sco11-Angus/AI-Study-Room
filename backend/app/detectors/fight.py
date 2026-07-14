"""音视频融合语义判断打架 (任务书 D，系统设计说明书 §3/§7)。

本项目技术亮点：把视觉"剧烈肢体冲突"与音频"尖叫/怒吼/打斗声"两条模态融合，
"看到 + 听到"双重确认，显著降低单模态误报。

    视觉侧(D2): 近距离聚集 + 高速肢体运动 -> vis_score
    音频侧(D3): 高能量突发 + 声学特征     -> aud_score
    融合(D4):   fuse = w_v*vis + w_a*aud，双模均非零且 > 阈值，持续 >=N 秒 -> 告警

约束：复用 B 的人员框（不重复加载 YOLO）；禁止自建线程，注册进 A 的引擎。
"""
import logging
import time
from collections import deque

import numpy as np

from ..config import Config
from .audio_event import AudioEventDetector
from .base import AlarmEvent, Detector, Frame
from .emotion import EmotionRecognizer
from .person_source import Box, PersonBoxProvider, build_person_provider

logger = logging.getLogger(__name__)


# ---------------- D2 视觉侧：剧烈冲突动作 ----------------

def _iou(a: Box, b: Box) -> float:
    """两框交并比。"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _proximity_score(boxes: list[Box]) -> float:
    """近距离聚集分：≥2 人贴身（IoU 高 / 中心距小于身宽）时升高。"""
    if len(boxes) < 2:
        return 0.0
    best = 0.0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            iou = _iou(boxes[i], boxes[j])
            (cx1, cy1), (cx2, cy2) = _center(boxes[i]), _center(boxes[j])
            dist = np.hypot(cx1 - cx2, cy1 - cy2)
            w1 = boxes[i][2] - boxes[i][0]
            w2 = boxes[j][2] - boxes[j][0]
            ref = (w1 + w2) / 2 or 1.0
            # 中心距 < 参考身宽 -> 贴身，越近分越高
            near = max(0.0, 1.0 - dist / ref)
            best = max(best, max(iou, near))
    return float(np.clip(best, 0.0, 1.0))


class _MotionTracker:
    """相邻推理帧间人员框位移速度 -> 运动能量（高速肢体运动信号）。

    以框中心归一化位移速度衡量；速度突增映射为 [0,1] 运动分。
    """

    def __init__(self, speed_ref: float = 0.15):
        self.speed_ref = speed_ref            # 归一化速度参考（>此值视为剧烈）
        self._prev: list[Box] = []
        self._prev_ts: float | None = None

    def update(self, boxes: list[Box], ts: float) -> float:
        prev, prev_ts = self._prev, self._prev_ts
        self._prev, self._prev_ts = boxes, ts
        if not prev or not boxes or prev_ts is None:
            return 0.0
        dt = ts - prev_ts
        if dt <= 0:
            return 0.0
        # 每个当前框匹配最近的上一帧框，取归一化位移速度
        speeds = []
        for b in boxes:
            cx, cy = _center(b)
            w = (b[2] - b[0]) or 1.0
            nearest = min(prev, key=lambda p: np.hypot(*(np.subtract(_center(p), (cx, cy)))))
            pcx, pcy = _center(nearest)
            disp = np.hypot(cx - pcx, cy - pcy) / w   # 以身宽归一化，抗尺度
            speeds.append(disp / dt)
        peak = max(speeds) if speeds else 0.0
        return float(np.clip(peak / self.speed_ref, 0.0, 1.0))


class VisualConflict:
    """视觉冲突置信度 = max(近距离聚集, 高速运动)。MVP 先做这两项。"""

    def __init__(self):
        self._motion = _MotionTracker()

    def score(self, boxes: list[Box], ts: float) -> float:
        prox = _proximity_score(boxes)
        motion = self._motion.update(boxes, ts)
        # 贴身且高速才是打斗；两者取几何加权，单一信号不足以拉满
        combined = max(prox * 0.5 + motion * 0.5, min(prox, motion))
        return float(np.clip(combined, 0.0, 1.0))


# ---------------- D3 音频侧：打斗声识别 ----------------

class AudioConflict:
    """音频打架置信度 — YAMNet语义检测 + DSP fallback 双轨。

    优先使用YAMNet语义检测（尖叫/喊叫/哭泣/玻璃破碎等），
    YAMNet不可用时降级到原有DSP特征（能量/过零率/谱质心）。
    """

    def __init__(self, hist: int = 5, rms_ref_db: float = -20.0):
        self.rms_ref_db = rms_ref_db
        self._energy_hist: deque = deque(maxlen=hist)
        self._yamnet: AudioEventDetector | None = None

    def set_yamnet(self, yamnet: AudioEventDetector) -> None:
        """注入YAMNet检测器（由FightPlugin在setup时调用）。"""
        self._yamnet = yamnet

    def _yamnet_score(self, pcm: np.ndarray, sample_rate: int) -> float:
        """使用YAMNet语义检测的音频冲突分 [0,1]。
        
        将YAMNet检测到的异常音频事件置信度映射为冲突分。
        尖叫声权重最高，其次是哭泣/玻璃破碎，最后是其他异常。
        """
        if self._yamnet is None:
            return 0.0
        result = self._yamnet.predict(pcm, sample_rate)
        event = result["event"]
        conf = result["confidence"]
        if event is None or conf < Config.YAMNET_CONF_THRESH:
            return 0.0
        
        # 不同事件类型的风险权重
        event_weights = {
            "Scream": 1.0,    # 尖叫 → 最高风险
            "Shout": 0.8,     # 喊叫
            "Yell": 0.8,      # 呼喊
            "Crying": 0.9,    # 哭泣/呼救
            "Glass": 0.7,     # 玻璃破碎
            "Shatter": 0.8,   # 粉碎声
            "Gunshot": 1.0,   # 枪声 → 最高风险
            "Explosion": 1.0, # 爆炸 → 最高风险
            "Thump": 0.5,     # 撞击声（可能是打架）
            "Crash": 0.6,     # 碰撞
            "Bang": 0.6,      # 猛击
            "Groan": 0.6,     # 呻吟
        }
        weight = event_weights.get(event, 0.5)
        return float(np.clip(conf * weight, 0.0, 1.0))

    @staticmethod
    def _rms_dbfs(pcm: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(pcm)))) if pcm.size else 0.0
        if rms <= 1e-8:
            return -120.0
        return 20.0 * np.log10(rms)

    @staticmethod
    def _zcr(pcm: np.ndarray) -> float:
        if pcm.size < 2:
            return 0.0
        return float(np.mean(np.abs(np.diff(np.sign(pcm))) > 0))

    @staticmethod
    def _spectral_centroid(pcm: np.ndarray, sr: int) -> float:
        if pcm.size == 0:
            return 0.0
        mag = np.abs(np.fft.rfft(pcm))
        freqs = np.fft.rfftfreq(pcm.size, 1.0 / sr)
        total = mag.sum()
        return float((freqs * mag).sum() / total) if total > 0 else 0.0

    def _dsp_score(self, pcm: np.ndarray, sample_rate: int) -> float:
        """原有DSP分析路径（fallback）。"""
        db = self._rms_dbfs(pcm)
        loud = np.clip((db - (-60.0)) / (self.rms_ref_db - (-60.0)), 0.0, 1.0)
        burst = 0.0
        if self._energy_hist:
            base = float(np.mean(self._energy_hist))
            burst = np.clip((loud - base) / 0.3, 0.0, 1.0)
        self._energy_hist.append(loud)
        zcr = self._zcr(pcm)
        centroid = self._spectral_centroid(pcm, sample_rate)
        spectral = np.clip(centroid / (sample_rate / 4), 0.0, 1.0)
        feat = 0.5 * zcr + 0.5 * spectral
        aud = 0.6 * loud + 0.25 * burst + 0.15 * feat
        return float(np.clip(aud, 0.0, 1.0))

    def score(self, pcm: np.ndarray, sample_rate: int) -> float:
        """计算音频冲突分：优先YAMNet语义，不可用时降级到DSP。"""
        if self._yamnet is not None:
            yamnet_score = self._yamnet_score(pcm, sample_rate)
            # 同时维护DSP能量直方图（用于fallback的一致性）
            db = self._rms_dbfs(pcm)
            loud = np.clip((db - (-60.0)) / (self.rms_ref_db - (-60.0)), 0.0, 1.0)
            self._energy_hist.append(loud)
            if yamnet_score > 0:
                return yamnet_score
        # Fallback to DSP
        return self._dsp_score(pcm, sample_rate)


# ---------------- D4 语义融合 + 时空防抖 ----------------

class FusionDebouncer:
    """融合音视频分+情绪风险并做持续性防抖。

    三模态加权：w_vis*vis + w_aud*aud + w_emo*emo_risk
    - 当EmotionRecognizer不可用时，emo_risk=0，权重自动归一化
    - 双模AND：视觉、音频均需非零（情绪可为零）
    - 候选无间断持续 >= FIGHT_DURATION -> 确认打架
    """

    def __init__(self):
        self.w_v = Config.FIGHT_W_VIS
        self.w_a = Config.FIGHT_W_AUD
        self.w_e = Config.FIGHT_W_EMO
        self.thresh = Config.FIGHT_FUSE_THRESH
        self.duration = Config.FIGHT_DURATION
        self._candidate_since: float | None = None
        self._fired = False

    def update(self, vis_score: float, aud_score: float, emo_risk: float = 0.0, ts: float = 0) -> dict | None:
        # 动态归一化权重：emo_risk可用时三模态，否则回退到双模
        if emo_risk > 0:
            total_w = self.w_v + self.w_a + self.w_e
            w_v = self.w_v / total_w
            w_a = self.w_a / total_w
            w_e = self.w_e / total_w
        else:
            total_w = self.w_v + self.w_a
            w_v = self.w_v / total_w
            w_a = self.w_a / total_w
            w_e = 0.0

        fuse = w_v * vis_score + w_a * aud_score + w_e * emo_risk
        
        # 双模AND：视觉、音频均需非零
        is_candidate = fuse > self.thresh and vis_score > 0 and aud_score > 0

        if not is_candidate:
            self._candidate_since = None
            self._fired = False
            return None

        if self._candidate_since is None:
            self._candidate_since = ts
        held = ts - self._candidate_since
        if held >= self.duration and not self._fired:
            self._fired = True
            return {
                "vis_score": round(vis_score, 3),
                "aud_score": round(aud_score, 3),
                "emo_risk": round(emo_risk, 3) if emo_risk > 0 else 0,
                "fuse": round(fuse, 3),
                "duration": round(held, 2),
            }
        return None


# ---------------- D5 打架检测插件 ----------------

class FightPlugin(Detector):
    """音视频融合打架检测器 — 三模态：视觉+音频语义+情绪风险。

    注册进A的引擎，禁止自建线程。
    detect(frame): 取B的人员框算视觉分 -> 融合YAMNet音频分+情绪分 -> 防抖 -> 告警。
    """

    name = "fight"

    def __init__(self, region_id: int = 0, person_provider: PersonBoxProvider | None = None):
        self.region_id = region_id
        self._person = person_provider
        self._visual = VisualConflict()
        self._audio = AudioConflict()
        self._emotion = EmotionRecognizer()
        self._fusion = FusionDebouncer()
        self._last_aud_score = 0.0
        self._last_aud_ts: float | None = None
        self._last_emo_risk = 0.0

    def setup(self) -> None:
        if self._person is None:
            self._person = build_person_provider(Config.FIGHT_PERSON_SOURCE)
        
        # Setup YAMNet for audio semantic detection
        try:
            yamnet = AudioEventDetector()
            yamnet.setup()
            self._audio.set_yamnet(yamnet)
        except Exception:
            logger.warning("[fight] YAMNet setup failed, using DSP-only audio", exc_info=True)
        
        # Setup emotion recognizer
        try:
            self._emotion.setup()
        except Exception:
            logger.warning("[fight] Emotion recognizer setup failed", exc_info=True)
        
        logger.info("[fight] 打架检测器就绪（人员框来源=%s, YAMNet=%s, Emotion=%s）", 
                   type(self._person).__name__,
                   self._audio._yamnet is not None,
                   self._emotion.loaded)

    def feed_audio(self, chunk) -> None:
        """由音轨管线(D1)投递AudioChunk，更新最近音频分+情绪。"""
        self._last_aud_score = self._audio.score(chunk.pcm, chunk.sample_rate)
        self._last_aud_ts = chunk.ts
        # Feed to emotion recognizer
        if self._emotion.loaded:
            self._emotion.feed(chunk.pcm, chunk.sample_rate)
            self._last_emo_risk = self._emotion.get_emotion_risk_score()

    def detect(self, frame: Frame) -> list[AlarmEvent]:
        boxes = self._person.get_boxes(frame) if self._person else []
        vis_score = self._visual.score(boxes, frame.ts)

        # 时间对齐：音频窗口ts与本帧在容差内才配对，过期音频视为0
        aud_score = 0.0
        emo_risk = 0.0
        if self._last_aud_ts is not None and \
                abs(frame.ts - self._last_aud_ts) <= Config.FIGHT_ALIGN_TOL:
            aud_score = self._last_aud_score
            emo_risk = self._last_emo_risk

        hit = self._fusion.update(vis_score, aud_score, emo_risk, frame.ts)
        if hit is None:
            return []

        logger.warning("[fight] 打架告警 region=%s fuse=%.3f vis=%.3f aud=%.3f emo=%.3f",
                      self.region_id, hit["fuse"], hit["vis_score"], 
                      hit["aud_score"], hit.get("emo_risk", 0))

        extra = {
            "level": Config.FIGHT_LEVEL,
            "vis_score": hit["vis_score"],
            "aud_score": hit["aud_score"],
            "fuse": hit["fuse"],
            "duration": hit["duration"],
            "person_boxes": boxes,
            "camera_id": frame.camera_id,
        }
        if hit.get("emo_risk", 0) > 0:
            extra["emo_risk"] = hit["emo_risk"]
            extra["emotion"] = self._emotion.emotion if self._emotion.loaded else "unknown"

        return [AlarmEvent(
            region_id=self.region_id,
            type="fight",
            confidence=hit["fuse"],
            snapshot=frame.image,
            extra=extra,
        )]

    def get_emotion_recognizer(self) -> EmotionRecognizer:
        """暴露情绪识别器，供ZoneEmotionRisk联动使用。"""
        return self._emotion
