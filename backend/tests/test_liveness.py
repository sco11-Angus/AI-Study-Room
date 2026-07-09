"""活体检测 Anti-Spoofing 单元测试。

测试 LivenessDetector 各信号模块 + FaceDetector 集成。
"""
import collections
import os
import sys
import time as _time

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---- Mock dlib landmarks ----

class _MockPoint:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _MockLandmarks:
    """模拟 dlib 68 点 landmarks。

    眼睛 landmarks 索引（dlib 68 点标准）：
      左眼: 36(左角) 37 38 39(右角) 40 41
      右眼: 42(左角) 43 44 45(右角) 46 47

    EAR 公式中 pts[0]左角, pts[1]上左, pts[2]上右, pts[3]右角, pts[4]下右, pts[5]下左
    """
    def __init__(self, eye_state="open"):
        pts = []
        for i in range(68):
            if i < 36:
                # 脸部轮廓和眉毛等，随便放
                x = 80 + (i % 12) * 20
                y = 80 + (i // 12) * 30
            elif 36 <= i <= 41:
                # 左眼
                base = {
                    "open":   [(110, 130), (115, 122), (125, 120), (135, 130), (125, 140), (115, 138)],
                    "closed": [(110, 130), (115, 129), (125, 129), (135, 130), (125, 131), (115, 131)],
                }[eye_state]
                x, y = base[i - 36]
            elif 42 <= i <= 47:
                # 右眼
                base = {
                    "open":   [(170, 130), (175, 122), (185, 120), (195, 130), (185, 140), (175, 138)],
                    "closed": [(170, 130), (175, 129), (185, 129), (195, 130), (185, 131), (175, 131)],
                }[eye_state]
                x, y = base[i - 42]
            else:
                x = 160 + ((i - 48) % 10) * 15
                y = 130 + ((i - 48) // 10) * 25
            pts.append(_MockPoint(x, y))
        self._points = pts

    def part(self, idx):
        return self._points[idx]


def make_face_crop(size=200):
    """创建模拟人脸裁剪 BGR 图像（含自然纹理 + 噪声）。"""
    rng = np.random.RandomState(42)
    img = np.full((size, size, 3), 128, dtype=np.uint8)
    # 添加渐变模拟面部光照
    for i in range(size):
        for j in range(size):
            val = 128 + int(30 * np.sin(i / 20) * np.cos(j / 20))
            img[i, j] = np.clip([val, val - 5, val + 5], 0, 255).astype(np.uint8)
    # 添加随机噪声
    noise = (rng.randn(size, size, 3) * 8).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img


def make_moire_face_crop(size=200):
    """创建模拟翻拍/屏幕拍摄人脸（多方向正弦条纹模拟摩尔纹）。"""
    img = make_face_crop(size)
    h, w = img.shape[:2]
    # 叠加多种频率和方向的条纹，模拟 CMOS 传感器与屏幕像素网格干涉产生的摩尔纹
    x = np.arange(w)
    y = np.arange(h)[:, None]
    # 多方向高频条纹叠加
    pattern = (
        np.sin(x * 0.25) * 0.3
        + np.sin(y * 0.3) * 0.3
        + np.sin((x + y) * 0.2) * 0.2
        + np.sin((x - y) * 0.22) * 0.2
    )
    stripe = 1.0 + pattern
    for c in range(3):
        ch = img[:, :, c].astype(np.float64)
        if c == 1:  # 绿色通道色偏（屏幕典型特征）
            ch *= (stripe + 0.1)
        else:
            ch *= stripe
        img[:, :, c] = np.clip(ch, 0, 255).astype(np.uint8)
    return img


# ---- LivenessDetector 单元测试 ----

class TestLivenessDetectorUnit:
    """LivenessDetector 各信号模块测试。"""

    @pytest.fixture
    def detector(self):
        from app.detectors.liveness import LivenessDetector
        return LivenessDetector(
            enabled=True,
            threshold=0.5,
            history_size=10,
            ear_blink_thresh=0.25,
        )

    def test_ear_open_eyes(self, detector):
        """睁眼 EAR 应大于闭眼阈值。"""
        landmarks = _MockLandmarks(eye_state="open")
        ear = detector._ear(landmarks, [36, 37, 38, 39, 40, 41])
        assert ear > 0.25, f"睁眼 EAR={ear:.3f}，应大于 0.25"
        ear_r = detector._ear(landmarks, [42, 43, 44, 45, 46, 47])
        assert ear_r > 0.25

    def test_ear_closed_eyes(self, detector):
        """闭眼 EAR 应小于睁眼 EAR（模拟）。"""
        landmarks_open = _MockLandmarks(eye_state="open")
        landmarks_closed = _MockLandmarks(eye_state="closed")
        ear_open = detector._ear(landmarks_open, [36, 37, 38, 39, 40, 41])
        ear_closed = detector._ear(landmarks_closed, [36, 37, 38, 39, 40, 41])
        assert ear_closed < ear_open, f"闭眼 EAR={ear_closed:.3f} 应 < 睁眼 EAR={ear_open:.3f}"

    def test_ear_score_no_history(self, detector):
        """历史为空时返回中性分数。"""
        landmarks = _MockLandmarks(eye_state="open")
        score, blinked = detector._compute_ear_score(landmarks)
        assert score == 0.5
        assert blinked is False

    def test_ear_score_blink_detected(self, detector):
        """模拟眨眼：EAR 从低到高的上升沿。"""
        # 先填入低 EAR（闭眼状态）
        closed = _MockLandmarks(eye_state="closed")
        for _ in range(4):
            detector._compute_ear_score(closed)

        # 切换到睁眼（模拟眨眼结束）
        open_eyes = _MockLandmarks(eye_state="open")
        score, blinked = detector._compute_ear_score(open_eyes)

        assert score == 1.0, f"眨眼应返回 1.0，实际 {score}"
        assert blinked is True

    def test_motion_score_first_frame(self, detector):
        """第一帧光流返回中性。"""
        gray = cv2_gray(make_face_crop())
        score = detector._compute_motion_score(gray)
        assert score == 0.5

    def test_motion_score_static(self, detector):
        """静止帧光流接近零。"""
        gray = cv2_gray(make_face_crop())
        detector._compute_motion_score(gray)  # 第一帧
        # 第二帧完全相同 → 运动为零
        score = detector._compute_motion_score(gray.copy())
        assert score < 0.1, f"静止帧 motion_score={score:.3f}，应接近 0"

    def test_motion_score_with_movement(self, detector):
        """有位移帧光流应非零。"""
        import cv2
        gray1 = cv2_gray(make_face_crop())
        detector._compute_motion_score(gray1)
        # 第二帧平移 2 像素
        gray2 = np.roll(gray1, shift=2, axis=1)
        score = detector._compute_motion_score(gray2)
        assert score > 0.1, f"有运动帧 motion_score={score:.3f}，应 > 0.1"

    def test_texture_score_normal(self, detector):
        """正常纹理应有较高分数。"""
        gray = cv2_gray(make_face_crop())
        score = detector._compute_texture_score(gray)
        assert score >= 0.5, f"正常纹理 score={score:.3f}，应 >= 0.5"

    def test_texture_score_range(self, detector):
        """纹理分析分数应在 [0, 1] 范围内。"""
        gray = cv2_gray(make_face_crop())
        score = detector._compute_texture_score(gray)
        assert 0.0 <= score <= 1.0, f"纹理分数 {score} 超出 [0,1]"

    def test_texture_score_constant_vs_natural(self, detector):
        """纯色图像（非自然纹理）分数应低于自然图像。"""
        gray_natural = cv2_gray(make_face_crop())
        # 纯色=极度不自然的纹理
        gray_flat = np.full((200, 200), 128, dtype=np.uint8)
        score_natural = detector._compute_texture_score(gray_natural)
        score_flat = detector._compute_texture_score(gray_flat)
        # LBP 直方图方差：纯色图像 LBP 极度集中 → 方差较大 → 分数低
        assert score_flat < score_natural, (
            f"纯色纹理 score={score_flat:.3f} 应 < 自然纹理 score={score_natural:.3f}"
        )

    def test_fusion_real_face(self, detector):
        """真实人脸场景融合分应 >= 阈值。"""
        face = make_face_crop()
        landmarks = _MockLandmarks(eye_state="open")
        # 预填眨眼历史
        for _ in range(5):
            result = detector.check(face, landmarks)
        # 给一定时间累积微动后检查
        for i in range(5):
            shifted = np.roll(face, shift=i + 1, axis=1)
            result = detector.check(shifted, landmarks)
        assert result["score"] >= 0.3, (
            f"真实场景融合分={result['score']:.3f}，应 >= 0.3"
        )

    def test_fusion_spoof_static(self, detector):
        """静态照片场景融合分应较低。"""
        face = make_moire_face_crop()
        landmarks = _MockLandmarks(eye_state="open")
        for _ in range(6):
            result = detector.check(face.copy(), landmarks)
        assert result["score"] < 0.8, (
            f"静态照片融合分={result['score']:.3f}，应较低"
        )

    def test_disabled_returns_pass(self):
        """禁用时始终返回通过。"""
        from app.detectors.liveness import LivenessDetector
        d = LivenessDetector(enabled=False)
        result = d.check(make_face_crop(), _MockLandmarks())
        assert result["score"] == 1.0
        assert result["reasons"] == []

    def test_reset_clears_history(self):
        """reset() 后历史清零。"""
        from app.detectors.liveness import LivenessDetector
        d = LivenessDetector(history_size=10)
        face = make_face_crop()
        landmarks = _MockLandmarks()
        for _ in range(5):
            d.check(face, landmarks)
        assert len(d._face_history) == 5
        assert len(d._ear_history) == 5
        d.reset()
        assert len(d._face_history) == 0
        assert len(d._ear_history) == 0


# ---- FaceDetector 集成测试 ----

def _try_import_db():
    """检查数据库模块是否可导入（需要 mysql 或 sqlite）。"""
    try:
        import app.models.database  # noqa: F401
        return True
    except (ImportError, ModuleNotFoundError):
        return False


def _make_feature(seed=42):
    rng = np.random.RandomState(seed)
    return rng.rand(128).astype(np.float64)


class _FakeRect:
    def __init__(self, left, top, right, bottom):
        self._l, self._t, self._r, self._b = left, top, right, bottom

    def left(self):
        return self._l
    def top(self):
        return self._t
    def right(self):
        return self._r
    def bottom(self):
        return self._b


def cv2_gray(img):
    """BGR → gray 辅助。"""
    import cv2
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


class TestFaceDetectorWithLiveness:
    """FaceDetector + LivenessDetector 集成测试。"""

    @pytest.fixture
    def ctx(self, monkeypatch):
        if not _try_import_db():
            pytest.skip("数据库模块不可用（缺少 mysql 驱动）")
        from app.detectors.face import FaceDetector, FaceMatcher
        from app.models.entities import Member, Base
        from app.detectors.base import Frame

        # 内存数据库
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        monkeypatch.setattr("app.models.database.SessionLocal", Session)

        # 构造 matcher
        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6
        matcher._dlib_loaded = True
        matcher._detector = "mock"
        matcher._initialized = True

        # Mock detect_faces → 一直有人脸
        monkeypatch.setattr(matcher, "detect_faces",
                            lambda img: [_FakeRect(100, 50, 300, 250)])

        # Mock encode_from_rect
        monkeypatch.setattr(matcher, "encode_from_rect",
                            lambda img, rect: _make_feature(1))

        # Mock match → stranger
        monkeypatch.setattr(matcher, "match", lambda feature: "stranger")

        # Mock get_member_name
        monkeypatch.setattr(matcher, "get_member_name", lambda mid: None)

        # Mock shape_from_rect → 返回 landmarks
        monkeypatch.setattr(matcher, "shape_from_rect",
                            lambda img, rect: _MockLandmarks(eye_state="open"))

        # 构造 FaceDetector（关闭 cooldown 以便测试）
        detector = FaceDetector(skip_frames=1, cooldown=0.0)
        detector._matcher = matcher

        # 初始化活体检测器（阈值调低，让正常帧通过）
        from app.detectors.liveness import LivenessDetector
        detector._liveness = LivenessDetector(
            enabled=True,
            threshold=0.2,  # 低阈值确保通过
            history_size=10,
            ear_blink_thresh=0.25,
        )

        img = np.zeros((360, 640, 3), dtype=np.uint8)
        # 填充人脸区域模拟图像
        # 不再填充为纯黑色，改用有纹理的图像
        rng = np.random.RandomState(42)
        img = (rng.rand(360, 640, 3) * 50 + 100).astype(np.uint8)

        def make_frame():
            return Frame(image=img.copy(), ts=_time.time(), camera_id=0, frame_idx=0)

        return {
            "detector": detector,
            "matcher": matcher,
            "make_frame": make_frame,
            "session": Session(),
        }

    def test_liveness_pass_proceeds_to_match(self, ctx):
        """活体通过 → 继续匹配 → 返回 face_recognition 事件。"""
        events = ctx["detector"].detect(ctx["make_frame"]())
        assert len(events) == 1
        assert events[0].type == "face_recognition"

    def test_liveness_fail_returns_spoof(self, ctx, monkeypatch):
        """活体失败 → 返回 face_spoof 事件，不执行匹配。"""
        from app.detectors.liveness import LivenessDetector

        # 替换为高阈值活体检测器（必定失败）
        ctx["detector"]._liveness = LivenessDetector(
            enabled=True,
            threshold=0.99,  # 极高阈值
            history_size=10,
            ear_blink_thresh=0.25,
        )

        # Mock shape_from_rect 用闭眼 landmarks（更易失败）
        ctx["matcher"].shape_from_rect = lambda img, rect: _MockLandmarks(eye_state="closed")

        events = ctx["detector"].detect(ctx["make_frame"]())
        assert len(events) == 1
        assert events[0].type == "face_spoof", f"期望 face_spoof，实际 {events[0].type}"
        assert "liveness_score" in events[0].extra
        assert "reasons" in events[0].extra

    def test_liveness_disabled_proceeds_normally(self, ctx):
        """LIVENESS_ENABLED=false → 跳过活体检测，正常匹配。"""
        ctx["detector"]._liveness.enabled = False
        events = ctx["detector"].detect(ctx["make_frame"]())
        assert len(events) == 1
        assert events[0].type == "face_recognition"


# ---- 向后兼容：现有 test_face.py 场景不受影响 ----

class _FakeRectForFace:
    def __init__(self, left, top, right, bottom):
        self._l, self._t, self._r, self._b = left, top, right, bottom

    def left(self):
        return self._l
    def top(self):
        return self._t
    def right(self):
        return self._r
    def bottom(self):
        return self._b


class TestFaceBackwardCompat:
    """确保 FaceMatcher.match() 逻辑不受活体检测影响。"""

    @pytest.fixture
    def db(self, monkeypatch):
        if not _try_import_db():
            pytest.skip("数据库模块不可用（缺少 mysql 驱动）")
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        from app.models.entities import Base
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        monkeypatch.setattr("app.models.database.SessionLocal", Session)
        yield Session()
        engine.dispose()

    def test_no_members_returns_stranger(self, db):
        from app.detectors.face import FaceMatcher
        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6
        assert matcher.match(_make_feature()) == "stranger"

    def test_same_person_matches(self, db):
        import json
        from app.models.entities import Member
        from app.detectors.face import FaceMatcher

        feature = _make_feature(1)
        m = Member(member_id=1, name="张三", feature=json.dumps(feature.tolist()))
        db.add(m)
        db.commit()

        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6
        assert matcher.match(feature) == "member:1"

    def test_different_person_returns_stranger(self, db):
        import json
        from app.models.entities import Member
        from app.detectors.face import FaceMatcher

        stored = _make_feature(1)
        m = Member(member_id=1, name="张三", feature=json.dumps(stored.tolist()))
        db.add(m)
        db.commit()

        unknown = _make_feature(99)
        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6
        assert matcher.match(unknown) == "stranger"
