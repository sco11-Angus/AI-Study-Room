"""人脸表情情绪闸门单测 (任务书 D2-A)。

重点验证「优雅降级」：未启用 / 无框 / 模型缺失时返回放行值 1.0，绝不崩。
真实模型推理准确性走端到端素材验证，不在单测里下载模型。
"""
import numpy as np

from app.config import Config
from app.detectors.emotion import FacialEmotion, _NEUTRAL_PASSTHROUGH


def _img(h=100, w=100):
    return np.zeros((h, w, 3), np.uint8)


def test_passthrough_when_disabled(monkeypatch):
    monkeypatch.setattr(Config, "EMOTION_ENABLE", False)
    fe = FacialEmotion()
    assert fe.score(_img(), [(0, 0, 50, 50)]) == _NEUTRAL_PASSTHROUGH


def test_passthrough_when_no_boxes(monkeypatch):
    monkeypatch.setattr(Config, "EMOTION_ENABLE", True)
    fe = FacialEmotion()
    assert fe.score(_img(), []) == _NEUTRAL_PASSTHROUGH


def test_passthrough_when_image_none(monkeypatch):
    monkeypatch.setattr(Config, "EMOTION_ENABLE", True)
    fe = FacialEmotion()
    assert fe.score(None, [(0, 0, 50, 50)]) == _NEUTRAL_PASSTHROUGH


def test_load_failure_degrades_to_passthrough(monkeypatch):
    """模型加载失败 -> 永久降级放行，不抛异常。"""
    monkeypatch.setattr(Config, "EMOTION_ENABLE", True)
    fe = FacialEmotion()
    fe._load_failed = True  # 模拟加载失败
    assert fe.score(_img(), [(0, 0, 50, 50)]) == _NEUTRAL_PASSTHROUGH


def test_returns_float_in_range(monkeypatch):
    """启用且模型可用时返回 [0,1]；不可用则放行。两种情况都不崩。"""
    monkeypatch.setattr(Config, "EMOTION_ENABLE", True)
    fe = FacialEmotion()
    val = fe.score(_img(), [(0, 0, 50, 50)])
    assert isinstance(val, float)
    assert 0.0 <= val <= 1.0
