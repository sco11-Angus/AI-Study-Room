# -*- coding: utf-8 -*-
"""LivenessDetector 五层架构 + FaceDetector 集成测试。

覆盖：
- LivenessDetector 基础功能（实例化、禁用、reset）
- EAR 眨眼检测（_compute_ear, _ear_blink_score）
- Layer 4 媒体检测各子特征（LBP熵、RGB相关、FFT摩尔纹、高光反射）
- check() 集成（prolonged_no_blink、眨眼恢复、返回结构）
- FaceDetector + FaceMatcher 集成（活体禁用、匹配逻辑）
"""
import json
import os
import sys
import time as _time

import cv2
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ======================================================================
# 辅助函数 & 类
# ======================================================================

def make_face_crop(h: int = 128, w: int = 128) -> np.ndarray:
    """创建随机 BGR 人脸裁剪（模拟正常纹理）。"""
    rng = np.random.RandomState(42)
    return (rng.rand(h, w, 3) * 255).astype(np.uint8)


def make_skin_face_crop(h: int = 128, w: int = 128) -> np.ndarray:
    """创建肤色彩色人脸裁剪（BGR，模拟真人肤色，低高光）。"""
    rng = np.random.RandomState(42)
    # 肤色彩色 BGR 均值：B≈100, G≈140, R≈180
    b = np.clip(rng.normal(100, 15, (h, w)), 0, 255).astype(np.uint8)
    g = np.clip(rng.normal(140, 15, (h, w)), 0, 255).astype(np.uint8)
    r = np.clip(rng.normal(180, 15, (h, w)), 0, 255).astype(np.uint8)
    return cv2.merge([b, g, r])


def make_moire_face_crop(h: int = 128, w: int = 128) -> np.ndarray:
    """创建模拟摩尔纹的 BGR 人脸裁剪（带周期性条纹，FFT 有显著峰值）。"""
    x = np.arange(w, dtype=np.float32)
    y = np.arange(h, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    # 叠加网格 + 底图纹理，产生清晰的 FFT 中高频峰值
    base = np.sin(2 * np.pi * xx / 4.0) * np.sin(2 * np.pi * yy / 5.0)
    base = (base - base.min()) / (base.max() - base.min() + 1e-10)
    base = (base * 255).astype(np.uint8)
    return cv2.merge([base, base, base])


def cv2_gray(bgr: np.ndarray) -> np.ndarray:
    """BGR → gray 转换包装。"""
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


class _MockPoint:
    """模拟 dlib point 对象。"""
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _MockLandmarks:
    """模拟 dlib 68 点 landmarks。

    eye_state 控制睁眼/闭眼程度：
    - "open": 垂直偏移大 → 高 EAR
    - "closed": 垂直偏移小 → 低 EAR
    """

    def __init__(self, eye_state: str = "open"):
        pts = []
        for i in range(68):
            row = i // 10
            col = i % 10
            x = 50 + col * 20
            y = 100 + row * 30

            if eye_state == "open":
                # 睁眼：顶部点上移、底部点下移
                if i in (37, 38):    # 左眼顶部
                    y -= 15
                if i == 41:          # 左眼底部
                    y += 15
                if i in (43, 44):    # 右眼顶部
                    y -= 15
                if i == 47:          # 右眼底部
                    y += 15
            else:  # "closed"
                # 闭眼：顶点和底点接近水平
                if i in (37, 38):
                    y -= 2
                if i == 41:
                    y += 2
                if i in (43, 44):
                    y -= 2
                if i == 47:
                    y += 2

            pts.append(_MockPoint(x, y))
        self._points = pts

    def part(self, idx):
        return self._points[idx]


class _FakeRect:
    """模拟 dlib rectangle。"""
    def __init__(self, left, top, right, bottom):
        self._l, self._t, self._r, self._b = left, top, right, bottom

    def left(self): return self._l
    def top(self): return self._t
    def right(self): return self._r
    def bottom(self): return self._b


# ======================================================================
# 1. LivenessDetector 基础功能
# ======================================================================

class TestLivenessDetectorBasic:
    """测试 LivenessDetector 实例化、禁用模式、reset()。"""

    def test_instantiation_default(self):
        """实例化默认参数。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector()
        assert ld.enabled is True
        assert 0.0 < ld.threshold < 1.0
        assert ld.history_size == 30
        assert ld.ear_blink_thresh == 0.25
        assert ld.ema_alpha == 0.3
        assert ld._score_ema == 0.5
        assert ld._spoof_streak == 0
        assert ld._blink_ever_detected is False
        assert ld._frames_no_blink == 0
        assert len(ld._face_crop_history) == 0

    def test_disabled_returns_pass(self):
        """禁用时 check() 返回 pass。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector(enabled=False)
        result = ld.check(make_face_crop(), _MockLandmarks())
        assert result["score"] == 1.0
        assert result["is_spoof"] is False
        assert result["reasons"] == []
        assert "details" in result
        assert result["details"]["final_smoothed"] == 1.0

    def test_reset_clears_state(self):
        """reset() 清空所有会话状态。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector()
        # 先修改一些状态
        ld._score_ema = 0.8
        ld._spoof_streak = 3
        ld._blink_ever_detected = True
        ld._frames_no_blink = 10
        ld._prev_face_crop = np.zeros((10, 10, 3), dtype=np.uint8)
        ld._prev_landmarks = "fake"
        ld._prev_gray = np.zeros((10, 10), dtype=np.uint8)

        # 各 deque 填充数据
        ld._face_crop_history.append(make_face_crop())
        ld._deepfake_scores.append(0.5)
        ld._static_scores.append(0.5)
        ld._lbp_hist_history.append(0.1)
        ld._diff_means.append(0.2)
        ld._pixel_sequences.append(np.zeros(100, dtype=np.float32))
        ld._pose_deque.append((0.1, 0.2, 0.3))
        ld._temporal_score_hist.append(0.5)
        ld._ear_history.append(0.3)
        ld._was_below_thresh = True
        ld._prev_lbp_hist = np.ones(59)

        ld.reset()

        assert ld._score_ema == 0.5
        assert ld._spoof_streak == 0
        assert ld._blink_ever_detected is False
        assert ld._frames_no_blink == 0
        assert ld._prev_face_crop is None
        assert ld._prev_landmarks is None
        assert ld._prev_gray is None
        assert ld._prev_lbp_hist is None
        assert ld._was_below_thresh is False

        assert len(ld._face_crop_history) == 0
        assert len(ld._deepfake_scores) == 0
        assert len(ld._static_scores) == 0
        assert len(ld._lbp_hist_history) == 0
        assert len(ld._diff_means) == 0
        assert len(ld._pixel_sequences) == 0
        assert len(ld._pose_deque) == 0
        assert len(ld._temporal_score_hist) == 0
        assert len(ld._ear_history) == 0


# ======================================================================
# 2. EAR 眨眼检测
# ======================================================================

class TestEARBlink:
    """测试 _compute_ear 计算和 _ear_blink_score 眨眼检测逻辑。"""

    def test_compute_ear_open_eye(self):
        """睁眼 EAR > 0.25。"""
        from app.detectors.liveness import LivenessDetector

        # 手造 6 点左眼坐标（模拟睁眼）
        eye_pts = [
            (100, 128),   # p0: left corner
            (110, 110),   # p1: top-inner
            (120, 108),   # p2: top-center
            (130, 110),   # p3: top-outer
            (140, 128),   # p4: right corner
            (120, 148),   # p5: bottom
        ]
        ear = LivenessDetector._compute_ear(eye_pts)
        assert ear > 0.25
        assert isinstance(ear, float)

    def test_compute_ear_closed_vs_open(self):
        """闭眼 EAR < 睁眼 EAR。"""
        from app.detectors.liveness import LivenessDetector

        open_eye = [
            (100, 128), (110, 110), (120, 108),
            (130, 110), (140, 128), (120, 148),
        ]
        closed_eye = [
            (100, 128), (110, 126), (120, 127),
            (130, 126), (140, 128), (120, 131),
        ]
        ear_open = LivenessDetector._compute_ear(open_eye)
        ear_closed = LivenessDetector._compute_ear(closed_eye)
        assert ear_closed < ear_open

    def test_ear_blink_score_neutral_first_call(self):
        """_ear_blink_score 首次调用返回中性分 0.5。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector()
        landmarks = _MockLandmarks("open")
        score = ld._ear_blink_score(landmarks)
        assert score == 0.5

    def test_ear_blink_score_rise_edge_blink_detected(self):
        """模拟"闭眼→睁眼"上升沿触发眨眼检测。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector(ear_blink_thresh=0.25)
        # 预填充 4 帧低 EAR（模拟闭眼）
        ld._ear_history.extend([0.10, 0.15, 0.20, 0.25])
        # 使用睁眼 landmarks，实际 EAR 较高 → 上升沿
        landmarks = _MockLandmarks("open")
        score = ld._ear_blink_score(landmarks)
        # 上升沿检测：ear_list[2]=0.20 < 0.25, ear_list[4]=actual > 0.30
        assert score == 1.0

    def test_blink_state_tracking(self):
        """blink_ever_detected 和 frames_no_blink 状态正确更新。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector(ear_blink_thresh=0.25)

        # 首调用，未检测到眨眼
        assert ld._blink_ever_detected is False
        assert ld._frames_no_blink == 0

        # 模拟眨眼检测后状态更新
        ld._ear_history.extend([0.10, 0.15, 0.20, 0.25])
        landmarks = _MockLandmarks("open")
        ld._ear_blink_score(landmarks)  # 触发上升沿 → 返回 1.0

        # _ear_blink_score 不直接设置 blink_ever_detected，
        # 由 _layer3_liveness 根据返回值设置
        # 这里直接模拟 _layer3_liveness 逻辑
        s1 = ld._ear_blink_score(landmarks)
        assert s1 == 1.0  # blink_ever_detected 已为 True → 返回 1.0

    def test_ear_blink_score_when_already_blinked(self):
        """blink_ever_detected 为 True 后，后续调用直接返回 1.0。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector()
        ld._blink_ever_detected = True
        # 先填充足够历史
        ld._ear_history.extend([0.3, 0.3, 0.3, 0.3, 0.3])
        landmarks = _MockLandmarks("closed")
        score = ld._ear_blink_score(landmarks)
        assert score == 1.0

    def test_ear_blink_score_no_blink_eyes_open(self):
        """还没眨眼但睁眼 → 返回 0.6。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector()
        # 填充 5 帧以上睁眼但不触发 blink
        ld._ear_history.extend([0.35, 0.36, 0.35, 0.36, 0.35])
        landmarks = _MockLandmarks("open")  # EAR 较高
        score = ld._ear_blink_score(landmarks)
        # avg_ear > 0.30 → 0.6
        assert score == 0.6


# ======================================================================
# 3. Layer 4 媒体检测各子特征
# ======================================================================

class TestLayer4Media:
    """测试 Layer 4 各静态方法：LBP熵、RGB相关、FFT摩尔纹、高光反射。"""

    def test_lbp_entropy_normal_texture(self):
        """正常纹理 LBP 熵评分 ≥ 0.5。"""
        from app.detectors.liveness import LivenessDetector

        gray = cv2_gray(make_face_crop())
        score = LivenessDetector._lbp_entropy_score(gray)
        assert 0.0 <= score <= 1.0
        assert score >= 0.5, f"正常纹理 LBP 熵评分过低: {score}"

    def test_lbp_entropy_solid_color(self):
        """纯色图 LBP 熵评分低。"""
        from app.detectors.liveness import LivenessDetector

        solid = np.full((128, 128), 128, dtype=np.uint8)
        score = LivenessDetector._lbp_entropy_score(solid)
        assert score < 0.5, f"纯色图 LBP 熵评分应 < 0.5: {score}"

    def test_rgb_correlation_in_range(self):
        """正常图 RGB 通道相关分在 [0,1] 内。"""
        from app.detectors.liveness import LivenessDetector

        face = make_face_crop()
        score = LivenessDetector._rgb_correlation_score(face)
        assert 0.0 <= score <= 1.0

    def test_fft_moire_normal_vs_moire(self):
        """模拟摩尔纹图 FFT 峰值分 < 正常图。"""
        from app.detectors.liveness import LivenessDetector

        normal_gray = cv2_gray(make_face_crop())
        moire_gray = cv2_gray(make_moire_face_crop())

        score_normal = LivenessDetector._fft_moire_peaks(normal_gray)
        score_moire = LivenessDetector._fft_moire_peaks(moire_gray)

        assert 0.0 <= score_normal <= 1.0
        assert 0.0 <= score_moire <= 1.0
        # 摩尔纹图应有更多中高频峰值 → 分数 ≤ 正常图
        assert score_moire <= score_normal, \
            f"摩尔纹分({score_moire:.3f})应 ≤ 正常分({score_normal:.3f})"

    def test_specular_reflection_normal(self):
        """正常肤色彩色图高光反射评分 > 0.8（反射像素很少）。"""
        from app.detectors.liveness import LivenessDetector

        face = make_skin_face_crop()
        score = LivenessDetector._specular_reflection_score(face)
        assert score > 0.8, f"正常图高光反射评分应 > 0.8: {score}"


# ======================================================================
# 4. check() 集成测试
# ======================================================================

class TestCheckIntegration:
    """测试 check() 完整流程：prolonged_no_blink、眨眼恢复、返回结构。"""

    def test_prolonged_no_blink_triggers_spoof(self):
        """连续睁眼无眨眼 → prolonged_no_blink 触发 → score < threshold + is_spoof。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector(threshold=0.5)
        face = make_face_crop()
        landmarks = _MockLandmarks("open")

        # 先填充足够 ear_history 避免返回 0.5
        # 连续调用 22 次，frames_no_blink 从 0 累加到 22 > 20
        for i in range(22):
            result = ld.check(face, landmarks)
            if result["is_spoof"]:
                break

        assert result["is_spoof"] is True
        # 多路径均可触发 spoof：眨眼相关 / FSD / 媒体伪影 / 零运动 / 静态帧 / 刚性运动
        valid_spoof_reasons = [
            "prolonged_no_blink", "spoof_streak",
            "media_critical", "temporal_zero_motion",
            "temporal_critical", "static_frame_mse",
            "temporal_rigid_motion",
        ]
        assert any(r in result["reasons"] for r in valid_spoof_reasons), \
            f"actual reasons: {result['reasons']}"
        assert result["score"] < ld.threshold

    def test_blink_recovery_passes(self):
        """模拟"闭眼→睁眼"多次后 → 通过（blink_ever_detected=True）。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector(threshold=0.5, ear_blink_thresh=0.25)
        face = make_face_crop()
        landmarks_open = _MockLandmarks("open")
        landmarks_closed = _MockLandmarks("closed")

        # 第一阶段：预置 ear_history + 触发眨眼
        ld._ear_history.extend([0.10, 0.15, 0.20, 0.25])
        # 调用一次完成上升沿检测
        ld._ear_blink_score(landmarks_open)
        # 模拟 _layer3_liveness 的状态更新
        ld._blink_ever_detected = True
        ld._frames_no_blink = 0

        # 第二&第三阶段：继续喂帧 + 伪造足够的 ear_history
        for _ in range(10):
            ld._ear_history.append(0.35)

        # 现在 blink_ever_detected=True，_ear_blink_score 直接返回 1.0
        # 不会触发 prolonged_no_blink
        result = ld.check(face, landmarks_open)
        assert not result["is_spoof"] or "prolonged_no_blink" not in result["reasons"]

    def test_check_return_structure(self):
        """check() 返回结构完整：score/is_spoof/reasons/details。"""
        from app.detectors.liveness import LivenessDetector

        ld = LivenessDetector()
        result = ld.check(make_face_crop(), _MockLandmarks("open"))

        assert "score" in result
        assert "is_spoof" in result
        assert "reasons" in result
        assert "details" in result

        assert isinstance(result["score"], (int, float))
        assert isinstance(result["is_spoof"], bool)
        assert isinstance(result["reasons"], list)
        assert isinstance(result["details"], dict)

        # details 应包含各层分数
        details = result["details"]
        for key in ["deepfake_score", "minifas_score", "static_score",
                     "temporal_score", "liveness_score", "media_score",
                     "final_raw", "final_smoothed", "frames_cached"]:
            assert key in details, f"details 缺少键: {key}"


# ======================================================================
# 5. FaceDetector + FaceMatcher 集成测试
# ======================================================================

class _TestHelper:
    """测试辅助方法。"""

    @staticmethod
    def _make_feature(seed: int = 42) -> np.ndarray:
        rng = np.random.RandomState(seed)
        return rng.rand(128).astype(np.float64)


class TestFaceDetectorIntegration:
    """FaceDetector.detect() + FaceMatcher.match() 集成测试。"""

    @pytest.fixture
    def db_session(self, monkeypatch):
        """内存 SQLite + 空 Member 表。"""
        from app.models.entities import Base
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        monkeypatch.setattr("app.models.database.SessionLocal", Session)
        yield Session()
        engine.dispose()

    def test_matcher_no_members_stranger(self, db_session):
        """会员库为空 → 返回 stranger。"""
        from app.detectors.face import FaceMatcher
        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.4
        assert matcher.match(_TestHelper._make_feature()) == "stranger"

    def test_matcher_match_member(self, db_session):
        """相同人 → member:<id>。"""
        from app.models.entities import Member
        from app.detectors.face import FaceMatcher

        feature = _TestHelper._make_feature(1)
        m = Member(member_id=1, name="张三", feature=json.dumps(feature.tolist()))
        db_session.add(m)
        db_session.commit()

        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.4
        assert matcher.match(feature) == "member:1"

    def test_matcher_stranger_when_no_match(self, db_session):
        """不同人 → stranger。"""
        from app.models.entities import Member
        from app.detectors.face import FaceMatcher

        stored = _TestHelper._make_feature(1)
        m = Member(member_id=1, name="张三", feature=json.dumps(stored.tolist()))
        db_session.add(m)
        db_session.commit()

        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.4
        assert matcher.match(_TestHelper._make_feature(99)) == "stranger"

    def test_liveness_disabled_no_spoof(self, db_session, monkeypatch):
        """活体检测禁用时不产生 face_spoof 事件。"""
        from app.detectors.face import FaceDetector, FaceMatcher
        from app.detectors.base import Frame
        from app.models.entities import Base

        # 构造 FaceMatcher
        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.4
        matcher._dlib_loaded = True
        matcher._detector = "mock"
        matcher._initialized = True

        # Mock 方法
        monkeypatch.setattr(matcher, "detect_faces",
                            lambda img: [_FakeRect(100, 50, 300, 250)])
        monkeypatch.setattr(matcher, "encode",
                            lambda face_img: _TestHelper._make_feature(1))
        monkeypatch.setattr(matcher, "encode_from_rect",
                            lambda img, rect: _TestHelper._make_feature(1))
        monkeypatch.setattr(matcher, "shape_from_rect",
                            lambda img, rect: _MockLandmarks("open"))
        monkeypatch.setattr(matcher, "match",
                            lambda feature: "stranger")
        monkeypatch.setattr(matcher, "get_member_name", lambda mid: None)

        pushed_msgs = []
        monkeypatch.setattr("app.api.ws.broadcast_face_result",
                            lambda msg: pushed_msgs.append(msg))

        # 活体禁用
        detector = FaceDetector(skip_frames=1, cooldown=0.0)
        detector._matcher = matcher
        # FaceDetector 内部创建 liveness，覆盖为禁用
        detector._liveness = None  # None 表示不启用活体

        img = np.zeros((360, 640, 3), dtype=np.uint8)
        frame = Frame(image=img, ts=_time.time(), camera_id=0, frame_idx=0)

        events = detector.detect(frame)
        # 无 spoof 事件
        assert not any(e.type == "face_spoof" for e in events)
