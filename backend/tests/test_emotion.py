"""情绪模块单测（合并两套）。

A) FacialEmotion（D2-A 人脸表情闸门）：验证优雅降级——未启用/无框/模型缺失返回放行值 1.0。
B) EmotionRecognizer（taskA SenseVoiceSmall 声学情绪）：验证接口契约与优雅降级。
均用 mock/合成数据，不下载真实模型。
"""
import numpy as np

from app.config import Config
from app.detectors.emotion import FacialEmotion, EmotionRecognizer, _NEUTRAL_PASSTHROUGH


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


_SR = Config.AUDIO_SR  # 16000


def test_emotion_model_unavailable_graceful():
    """模型未安装时，EmotionRecognizer应优雅降级（loaded=False）。"""
    rec = EmotionRecognizer()
    # 不调用setup()，模拟模型不可用
    assert rec.loaded is False
    # predict应返回安全默认值
    result = rec.predict()
    assert result["emotion"] == "NEUTRAL"
    assert result["emotion_confidence"] == 0.0
    assert result["audio_event"] is None
    assert result["is_risky"] is False


def test_is_risky_method():
    """is_risky应对ANGRY/SAD返回True。"""
    assert EmotionRecognizer.is_risky("ANGRY") is True
    assert EmotionRecognizer.is_risky("SAD") is True
    assert EmotionRecognizer.is_risky("HAPPY") is False
    assert EmotionRecognizer.is_risky("NEUTRAL") is False


def test_get_emotion_risk_score_unloaded():
    """模型未加载时，risk_score应返回0。"""
    rec = EmotionRecognizer()
    assert rec.get_emotion_risk_score() == 0.0


def test_feed_unloaded_does_not_crash():
    """模型未加载时feed不应崩溃。"""
    rec = EmotionRecognizer()
    pcm = np.random.randn(16000).astype(np.float32) * 0.1
    # 不应抛异常
    rec.feed(pcm, sample_rate=16000)


def test_emotion_property_default():
    """默认情绪应为NEUTRAL。"""
    rec = EmotionRecognizer()
    assert rec.emotion == "NEUTRAL"


def test_predict_returns_valid_structure():
    """predict返回结构应包含所有必要字段。"""
    rec = EmotionRecognizer()
    result = rec.predict()
    assert set(result.keys()) == {"emotion", "emotion_confidence", "audio_event", "text", "is_risky"}
    assert isinstance(result["emotion"], str)
    assert isinstance(result["emotion_confidence"], float)
    assert isinstance(result["is_risky"], bool)


def test_emotion_config_disabled():
    """验证EMOTION_ENABLED配置项存在。"""
    assert hasattr(Config, "EMOTION_ENABLED")
    assert hasattr(Config, "EMOTION_RISK_COOLDOWN")
