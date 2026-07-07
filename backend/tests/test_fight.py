"""音视频融合打架检测单元测试 (对应任务书 D 验收标准)。

用合成数据注入，不依赖 ffmpeg / 真实流：
  - 双模都有信号且持续 >=FIGHT_DURATION -> 出 1 条 fight 告警(level=2)
  - 仅视觉 / 仅音频 -> 不告警(双模 AND 生效)
  - 短暂高分 <FIGHT_DURATION -> 不告警(持续性防抖)
  - 告警 extra 含 vis_score/aud_score/fuse
"""
import numpy as np

from app.config import Config
from app.detectors.base import Frame
from app.detectors.fight import (
    AudioConflict,
    FusionDebouncer,
    VisualConflict,
    FightPlugin,
)
from app.detectors.person_source import PersonBoxProvider
from app.stream.audio import AudioWindower, frame_signal


# ---- 测试替身：可控人员框来源 ----
class FakePersonProvider(PersonBoxProvider):
    def __init__(self):
        self.boxes = []

    def get_boxes(self, frame):
        return self.boxes


def _frame(ts, cam=1, idx=0):
    return Frame(image=np.zeros((4, 4, 3), np.uint8), ts=ts, camera_id=cam, frame_idx=idx)


# ---------------- D2 视觉侧 ----------------

def test_visual_score_rises_when_people_close_and_moving():
    vis = VisualConflict()
    # 两人分离、静止 -> 低分
    far = [(0, 0, 20, 60), (200, 0, 220, 60)]
    vis.score(far, ts=0.0)
    low = vis.score(far, ts=0.1)
    # 两人贴身且快速移动 -> 高分
    close_a = [(0, 0, 20, 60), (15, 0, 35, 60)]
    vis.score(close_a, ts=0.2)
    close_b = [(0, 0, 20, 60), (35, 0, 55, 60)]  # 第二人快速位移
    high = vis.score(close_b, ts=0.3)
    assert high > low


# ---------------- D3 音频侧 ----------------

def test_audio_score_higher_for_loud_signal():
    aud = AudioConflict()
    sr = Config.AUDIO_SR
    quiet = np.zeros(sr, np.float32)
    loud = 0.8 * np.random.randn(sr).astype(np.float32)
    assert aud.score(loud, sr) > aud.score(quiet, sr)


# ---------------- D4 融合 + 防抖 ----------------

def test_fusion_fires_only_when_both_modalities_and_sustained():
    fb = FusionDebouncer()
    dur = Config.FIGHT_DURATION
    # 双模都高，持续到时长阈值才告警
    assert fb.update(0.9, 0.9, ts=0.0) is None
    hit = fb.update(0.9, 0.9, ts=dur)
    assert hit is not None
    assert set(hit) >= {"vis_score", "aud_score", "fuse", "duration"}


def test_fusion_no_alarm_visual_only():
    fb = FusionDebouncer()
    dur = Config.FIGHT_DURATION
    assert fb.update(1.0, 0.0, ts=0.0) is None
    assert fb.update(1.0, 0.0, ts=dur + 1) is None  # 音频为 0，双模 AND 不成立


def test_fusion_no_alarm_audio_only():
    fb = FusionDebouncer()
    dur = Config.FIGHT_DURATION
    assert fb.update(0.0, 1.0, ts=0.0) is None
    assert fb.update(0.0, 1.0, ts=dur + 1) is None


def test_fusion_no_alarm_when_too_brief():
    fb = FusionDebouncer()
    # 高分但持续时间不足 -> 不告警(滤掉击掌/嬉闹)
    assert fb.update(0.9, 0.9, ts=0.0) is None
    assert fb.update(0.9, 0.9, ts=Config.FIGHT_DURATION / 2) is None


def test_fusion_resets_on_dropout():
    fb = FusionDebouncer()
    dur = Config.FIGHT_DURATION
    fb.update(0.9, 0.9, ts=0.0)
    fb.update(0.0, 0.0, ts=1.0)          # 回落 -> 计时清零
    assert fb.update(0.9, 0.9, ts=dur) is None  # 重新计时，未达阈值


# ---------------- D5 插件端到端 ----------------

def test_plugin_emits_fight_alarm_with_extra():
    person = FakePersonProvider()
    plugin = FightPlugin(region_id=7, person_provider=person)
    plugin.setup()
    sr = Config.AUDIO_SR
    dur = Config.FIGHT_DURATION

    # 贴身两人，逐帧快速位移；同时喂高能量音频
    class _Chunk:
        pcm = 0.8 * np.random.randn(sr).astype(np.float32)
        sample_rate = sr
        ts = 0.0

    events = []
    t = 0.0
    step = 0.5
    n = 0
    while t <= dur + 2 * step:
        # 两人持续贴身重叠(近距离聚集) + 逐帧抖动(高速肢体运动)——典型打斗
        jitter = 5 if n % 2 else -5
        person.boxes = [(0, 0, 40, 60), (20 + jitter, 0, 60 + jitter, 60)]
        chunk = _Chunk()
        chunk.ts = t
        plugin.feed_audio(chunk)
        events.extend(plugin.detect(_frame(ts=t)))
        t += step
        n += 1

    assert len(events) == 1
    evt = events[0]
    assert evt.type == "fight"
    assert evt.region_id == 7
    assert evt.extra["level"] == Config.FIGHT_LEVEL
    assert {"vis_score", "aud_score", "fuse"} <= set(evt.extra)


def test_plugin_no_alarm_without_audio():
    person = FakePersonProvider()
    plugin = FightPlugin(region_id=1, person_provider=person)
    plugin.setup()
    events = []
    t = 0.0
    while t <= Config.FIGHT_DURATION + 1:
        person.boxes = [(0, 0, 20, 60), (15 + t * 4, 0, 35 + t * 4, 60)]
        events.extend(plugin.detect(_frame(ts=t)))  # 从不 feed_audio
        t += 0.5
    assert events == []


# ---------------- D1 音轨管线（窗口聚合，不依赖 ffmpeg） ----------------

def test_audio_windower_aggregates_full_windows():
    sr = Config.AUDIO_SR
    win = AudioWindower(camera_id=1, sample_rate=sr, window_s=1.0)
    # 送入 2.5s PCM -> 应吐 2 个 1s 窗口
    chunks = win.feed(np.zeros(int(sr * 2.5), np.float32))
    assert len(chunks) == 2
    assert chunks[0].sample_rate == sr
    assert len(chunks[0].pcm) == sr


def test_frame_signal_shapes():
    sr = Config.AUDIO_SR
    frames = frame_signal(np.zeros(sr, np.float32), sr)
    # 25ms 帧长 / 10ms 帧移 -> 帧长 = 0.025*sr
    assert frames.shape[1] == int(sr * 0.025)
    assert frames.shape[0] > 0
