"""区域-情绪联动单元测试 (ZoneEmotionRisk).

测试愤怒情绪人员在危险区域中的阈值调整逻辑。
"""
import time
from collections import OrderedDict

import numpy as np

from app.config import Config
from app.detectors.zone_emotion import ZoneEmotionRisk


def test_zone_emotion_init():
    """初始化应创建空的人员和区域状态。"""
    zr = ZoneEmotionRisk()
    assert len(zr._persons) == 0
    assert len(zr._zone_modifiers) == 0


def test_default_threshold_modifier():
    """无愤怒人员时，阈值修正应为1.0（不变）。"""
    zr = ZoneEmotionRisk()
    assert zr.get_zone_threshold_modifier(1) == 1.0
    assert zr.get_zone_threshold_modifier(99) == 1.0


def test_update_emotion_adds_person():
    """更新情绪应添加/更新人员跟踪。"""
    zr = ZoneEmotionRisk()
    zr.update_emotion("face_001", "ANGRY", 0.9)
    assert "face_001" in zr._persons
    assert zr._persons["face_001"]["emotion"] == "ANGRY"
    assert zr._persons["face_001"]["confidence"] == 0.9


def test_update_position_adds_person():
    """更新位置应添加人员（即使没有情绪数据）。"""
    zr = ZoneEmotionRisk()
    zr.update_position("face_002", (100, 100, 200, 300))
    assert "face_002" in zr._persons
    assert zr._persons["face_002"]["person_box"] == (100, 100, 200, 300)


def test_set_zone_risk_modifies_threshold():
    """设置区域风险应降低阈值修正。"""
    zr = ZoneEmotionRisk()
    zr.set_zone_risk(5, 0.5)
    modifier = zr.get_zone_threshold_modifier(5)
    assert modifier < 1.0  # 应低于正常值
    assert modifier >= 0.8  # 不低于0.8


def test_zone_risk_recovery_after_cooldown():
    """冷却时间过后，阈值应恢复。"""
    zr = ZoneEmotionRisk()
    # 设置短暂冷却
    old_cooldown = Config.EMOTION_RISK_COOLDOWN
    try:
        # 手动设置一个已过期的modifier
        zr._zone_modifiers[3] = (0.8, time.time() - 1)
        assert zr.get_zone_threshold_modifier(3) == 1.0
    finally:
        pass  # 恢复原值在teardown


def test_stranger_no_emotion_no_modifier():
    """陌生人无情绪数据时，不应调整任何区域阈值。"""
    zr = ZoneEmotionRisk()
    # 没有任何愤怒人员
    assert zr.get_zone_threshold_modifier(1) == 1.0
    # check_zone_risk对无数据的box也安全
    polygons = {1: [[0, 0], [100, 0], [100, 100], [0, 100]]}
    risk = zr.check_zone_risk((10, 10, 30, 50), polygons)
    assert risk == 0.0


def test_angry_person_removed_after_stale():
    """过期的人员应被清理。"""
    zr = ZoneEmotionRisk()
    zr.update_emotion("stale_face", "ANGRY", 0.8)
    # 设置过期时间戳
    zr._persons["stale_face"]["last_update"] = time.time() - 20.0
    # check_zone_risk应清理过期人员
    risk = zr.check_zone_risk((0, 0, 10, 10), {})
    assert risk == 0.0
    assert "stale_face" not in zr._persons


def test_neutral_emotion_no_zone_risk():
    """NEUTRAL情绪不应触发区域风险。"""
    zr = ZoneEmotionRisk()
    zr.update_emotion("calm_face", "NEUTRAL", 0.9)
    zr.update_position("calm_face", (0, 0, 10, 10))
    polygons = {1: [[0, 0], [100, 0], [100, 100], [0, 100]]}
    risk = zr.check_zone_risk((0, 0, 10, 10), polygons)
    # NEUTRAL不触发风险
    assert risk == 0.0


def test_set_zone_risk_zero_no_effect():
    """risk_score=0不应修改任何区域。"""
    zr = ZoneEmotionRisk()
    zr.set_zone_risk(1, 0.0)
    assert zr.get_zone_threshold_modifier(1) == 1.0


def test_multiple_persons_eviction():
    """超过最大跟踪数应驱逐最旧条目。"""
    zr = ZoneEmotionRisk()
    # 添加超过_MAX_TRACKED(32)个人员
    for i in range(40):
        zr.update_emotion(f"face_{i:03d}", "NEUTRAL", 0.5)
    # 最早添加的应被驱逐
    assert "face_000" not in zr._persons
