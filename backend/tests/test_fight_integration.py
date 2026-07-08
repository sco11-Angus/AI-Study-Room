"""打架检测联调 — 把 FightPlugin 挂进 A 真实的 InferenceEngine 跑通整链路。

区别于 test_fight.py（纯单元）：这里用**真实引擎**驱动，只对两处"别人还没交付"
的依赖打桩，正是联调要验证的接口契约：

  1. A 侧：引擎共享上下文 shared_ctx（A 的 engine.py 目前还没实现，这里用最小实现模拟）。
  2. B 侧：B 的人员检测器往 shared_ctx.set(cam, idx, boxes) 写框（这里手动写入模拟）。

跑通 = 证明只要 A/B 按 person_source.py 里约定的契约实现，FightPlugin 即插即用，
D 侧一行都不用改。
"""
import numpy as np

from app.config import Config
from app.detectors.base import Frame
from app.detectors.fight import FightPlugin
from app.detectors.person_source import SharedContextProvider
from app.stream.engine import InferenceEngine


class FakeSharedContext:
    """模拟 A 需要在 engine 上提供的共享上下文（协作红线②的载体）。

    仅缓存"当前帧"人员框，按 (camera_id, frame_idx) 命中——与 person_source.py
    里的 SharedContext 协议签名一致。B 写、D 读。
    """

    def __init__(self):
        self._store: dict[tuple[int, int], list] = {}

    # ---- B 侧写入（模拟 B 的 PersonDetector.detect 结尾调用）----
    def set(self, camera_id: int, frame_idx: int, boxes: list) -> None:
        self._store[(camera_id, frame_idx)] = boxes

    # ---- D 侧读取（SharedContextProvider 调用）----
    def get_person_boxes(self, camera_id: int, frame_idx: int) -> list:
        return self._store.get((camera_id, frame_idx), [])


class _Chunk:
    """模拟 D1 音轨管线产出的 AudioChunk。"""

    def __init__(self, ts: float):
        self.pcm = 0.8 * np.random.randn(Config.AUDIO_SR).astype(np.float32)
        self.sample_rate = Config.AUDIO_SR
        self.ts = ts


def _frame(ts, idx, cam=1):
    return Frame(image=np.zeros((360, 640, 3), np.uint8), ts=ts, camera_id=cam, frame_idx=idx)


def _fighting_boxes(step_idx: int) -> list:
    """两人贴身 + 逐帧抖动：典型打斗（近距离聚集 + 高速肢体运动）。"""
    jitter = 5 if step_idx % 2 else -5
    return [(0, 0, 40, 60), (20 + jitter, 0, 60 + jitter, 60)]


def _build_engine():
    """按 A 的真实用法装配引擎：注册 -> 注入 shared_ctx -> setup_all。"""
    engine = InferenceEngine()
    ctx = FakeSharedContext()

    provider = SharedContextProvider()
    provider.bind(ctx)                       # A 装配时把引擎共享上下文注入 D 的 provider
    plugin = FightPlugin(region_id=7, person_provider=provider)

    engine.register(plugin)
    engine.setup_all()
    return engine, ctx, plugin


def test_end_to_end_fight_alarm_via_engine():
    """B 写框 + D 收音 + 引擎 dispatch -> 数秒内出 1 条 fight 告警。"""
    engine, ctx, plugin = _build_engine()

    events = []
    step = 0.5
    t = 0.0
    idx = 0
    while t <= Config.FIGHT_DURATION + 2 * step:
        # 模拟 B：本帧算完人员框写入共享上下文
        ctx.set(camera_id=1, frame_idx=idx, boxes=_fighting_boxes(idx))
        # 模拟 D1：音轨管线投递高能量音频窗口
        plugin.feed_audio(_Chunk(ts=t))
        # A 的引擎串行调度所有 enabled 检测器
        events.extend(engine.dispatch(_frame(ts=t, idx=idx)))
        t += step
        idx += 1

    fights = [e for e in events if e.type == "fight"]
    assert len(fights) == 1, f"期望 1 条打架告警，实际 {len(fights)}"
    evt = fights[0]
    assert evt.region_id == 7
    assert evt.extra["level"] == Config.FIGHT_LEVEL
    assert {"vis_score", "aud_score", "fuse"} <= set(evt.extra)
    assert evt.extra["vis_score"] > 0 and evt.extra["aud_score"] > 0  # 双模都有信号


def test_no_alarm_when_B_not_online():
    """B 尚未接入（shared_ctx 里没框）-> vis=0 -> 不误报、不崩（优雅降级）。"""
    engine, ctx, plugin = _build_engine()

    events = []
    t = 0.0
    idx = 0
    while t <= Config.FIGHT_DURATION + 1:
        # 不写 ctx（模拟 B 未上线），但照常喂音频
        plugin.feed_audio(_Chunk(ts=t))
        events.extend(engine.dispatch(_frame(ts=t, idx=idx)))
        t += 0.5
        idx += 1

    assert [e for e in events if e.type == "fight"] == []


def test_no_alarm_visual_only_no_audio():
    """B 写了打斗框但没有打斗声 -> 双模 AND 不成立 -> 不告警。"""
    engine, ctx, plugin = _build_engine()

    events = []
    t = 0.0
    idx = 0
    while t <= Config.FIGHT_DURATION + 1:
        ctx.set(camera_id=1, frame_idx=idx, boxes=_fighting_boxes(idx))
        # 从不 feed_audio -> aud=0
        events.extend(engine.dispatch(_frame(ts=t, idx=idx)))
        t += 0.5
        idx += 1

    assert [e for e in events if e.type == "fight"] == []
