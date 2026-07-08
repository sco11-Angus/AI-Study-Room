"""B9 人脸特征匹配 + FaceDetector 端到端测试。

测试 FaceMatcher.match() 匹配逻辑：
- 会员库为空 -> stranger
- 最近邻 < 阈值 -> member:id
- 最近邻 > 阈值 -> stranger
- 跳过损坏的特征数据

测试 FaceDetector.detect() E2E：
- 会员匹配成功 -> AlarmEvent(type=face_recognition, extra.face_match=member:X)
- 陌生人 -> AlarmEvent(extra.face_match=stranger)
- 无人脸 -> 空列表
"""
import json
import os
import sys
import time as _time

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_feature(seed: int = 42) -> np.ndarray:
    """构造 128 维测试特征。"""
    rng = np.random.RandomState(seed)
    return rng.rand(128).astype(np.float64)


# ---- FaceMatcher 单元测试 ----

class TestFaceMatch:
    """测试 match() 核心逻辑（通过 monkey-patch 绕过 dlib）。"""

    @pytest.fixture
    def db(self, monkeypatch):
        """内存 SQLite + 空 Member 表。"""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        from app.models.entities import Base
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        monkeypatch.setattr("app.models.database.SessionLocal", Session)
        yield Session()
        engine.dispose()

    def test_no_members_returns_stranger(self, db):
        """库空 -> stranger。"""
        from app.detectors.face import FaceMatcher
        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6
        assert matcher.match(_make_feature()) == "stranger"

    def test_same_person_matches(self, db):
        """相同特征 -> member:<id>。"""
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
        """不同人 -> stranger。"""
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

    def test_nearest_neighbor_wins(self, db):
        """多会员中选最近邻。"""
        from app.models.entities import Member
        from app.detectors.face import FaceMatcher

        f1 = _make_feature(1)
        m1 = Member(member_id=1, name="Alice", feature=json.dumps(f1.tolist()))
        f2 = _make_feature(2)
        m2 = Member(member_id=2, name="Bob", feature=json.dumps(f2.tolist()))
        db.add_all([m1, m2])
        db.commit()

        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6

        assert matcher.match(f1) == "member:1"
        assert matcher.match(f2) == "member:2"

    def test_corrupted_feature_skipped(self, db):
        """损坏的特征数据被跳过，仍能匹配到有效会员。"""
        from app.models.entities import Member
        from app.detectors.face import FaceMatcher

        m_bad = Member(member_id=99, name="corrupted", feature="not-valid-json")
        f_good = _make_feature(1)
        m_good = Member(member_id=1, name="Good", feature=json.dumps(f_good.tolist()))
        db.add_all([m_bad, m_good])
        db.commit()

        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6
        assert matcher.match(f_good) == "member:1"


# ---- FaceDetector E2E 测试 ----

class _FakeRect:
    """模拟 dlib rectangle。"""
    def __init__(self, left, top, right, bottom):
        self._l, self._t, self._r, self._b = left, top, right, bottom

    def left(self): return self._l
    def top(self): return self._t
    def right(self): return self._r
    def bottom(self): return self._b


class _MockPoint:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _MockLandmarks:
    """模拟 dlib 68 点 landmarks（睁眼状态）。"""
    def __init__(self):
        pts = []
        for i in range(68):
            x = 100 + (i % 10) * 15
            y = 120 + (i // 10) * 25
            # 左眼 36-41, 右眼 42-47（睁眼坐标）
            if i in (37, 38):
                y -= 8
            if i in (40, 41):
                y += 8
            if i in (43, 44):
                y -= 8
            if i in (46, 47):
                y += 8
            pts.append(_MockPoint(x, y))
        self._points = pts

    def part(self, idx):
        return self._points[idx]


class TestFaceDetectorE2E:
    """FaceDetector.detect() 端到端测试（mock dlib 模型，不加载真实权重）。"""

    @pytest.fixture
    def detector_with_db(self, monkeypatch):
        """Fixture: 创建 FaceDetector + 内存 SQLite + mock dlib 方法。"""
        from app.detectors.face import FaceDetector, FaceMatcher
        from app.models.entities import Member, Base
        from app.detectors.base import Frame

        # 内存数据库
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        monkeypatch.setattr("app.models.database.SessionLocal", Session)

        # 手动构造 FaceMatcher（跳过 dlib 加载）
        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6
        matcher._dlib_loaded = True
        matcher._detector = "mock"
        matcher._initialized = True

        # 注入 mock 方法
        self._setup_matcher_mocks(monkeypatch, matcher)

        # 构造 FaceDetector
        detector = FaceDetector(skip_frames=1, cooldown=0.0)
        detector._matcher = matcher

        # 测试帧（小尺寸 BGR 图像）
        img = np.zeros((360, 640, 3), dtype=np.uint8)

        def make_frame(camera_id=0, frame_idx=0):
            return Frame(image=img.copy(), ts=_time.time(),
                         camera_id=camera_id, frame_idx=frame_idx)

        return {
            "detector": detector,
            "matcher": matcher,
            "make_frame": make_frame,
            "session": Session(),
        }

    def _setup_matcher_mocks(self, monkeypatch, matcher):
        """配置 FaceMatcher 的 mock 行为。"""
        # 默认：检测到人脸
        self._mock_detect_faces = lambda img: [_FakeRect(100, 50, 300, 250)]
        self._mock_encode = lambda face_img: _make_feature(1)
        self._mock_match = lambda feature: "stranger"
        monkeypatch.setattr(matcher, "detect_faces", lambda img: self._mock_detect_faces(img))
        monkeypatch.setattr(matcher, "encode",
                            lambda face_img: self._mock_encode(face_img))
        monkeypatch.setattr(matcher, "encode_from_rect",
                            lambda img, rect: _make_feature(1))
        monkeypatch.setattr(matcher, "shape_from_rect",
                            lambda img, rect: _MockLandmarks())
        monkeypatch.setattr(matcher, "match",
                            lambda feature: self._mock_match(feature))
        monkeypatch.setattr(matcher, "get_member_name", lambda mid: None)

    # ---- 场景 1: 无人脸 ----

    def test_no_face_returns_empty(self, detector_with_db):
        """帧中无人脸 -> 空列表。"""
        ctx = detector_with_db
        self._mock_detect_faces = lambda img: []
        ctx["matcher"].detect_faces = lambda img: []

        events = ctx["detector"].detect(ctx["make_frame"]())
        assert events == []

    # ---- 场景 2: 陌生人 ----

    def test_stranger_returns_event(self, detector_with_db):
        """人脸存在但未匹配 -> AlarmEvent(type=face_recognition, face_match=stranger)。"""
        ctx = detector_with_db
        self._mock_detect_faces = lambda img: [_FakeRect(100, 50, 300, 250)]
        ctx["matcher"].detect_faces = lambda img: [_FakeRect(100, 50, 300, 250)]
        self._mock_match = lambda feature: "stranger"
        ctx["matcher"].match = lambda feature: "stranger"

        events = ctx["detector"].detect(ctx["make_frame"]())
        assert len(events) == 1
        evt = events[0]
        assert evt.type == "face_recognition"
        assert evt.extra["face_match"] == "stranger"
        assert evt.extra["name"] == "陌生人"
        assert evt.face_crop is not None

    # ---- 场景 3: 会员匹配成功 ----

    def test_member_matched_returns_event(self, detector_with_db, monkeypatch):
        """人脸匹配到会员 -> AlarmEvent 含 member_id 和 name。"""
        ctx = detector_with_db
        from app.models.entities import Member

        # 插入测试会员
        feature = _make_feature(1)
        m = Member(member_id=1, name="张三", feature=json.dumps(feature.tolist()))
        ctx["session"].add(m)
        ctx["session"].commit()

        ctx["matcher"].detect_faces = lambda img: [_FakeRect(100, 50, 300, 250)]
        ctx["matcher"].match = lambda feature: "member:1"
        ctx["matcher"].get_member_name = lambda mid: "张三"

        events = ctx["detector"].detect(ctx["make_frame"]())
        assert len(events) == 1
        evt = events[0]
        assert evt.type == "face_recognition"
        assert evt.extra["face_match"] == "member:1"
        assert evt.extra["member_id"] == 1
        assert evt.extra["name"] == "张三"
        assert evt.snapshot is not None
        assert evt.face_crop is not None

    # ---- 场景 4: 冷却去重 ----

    def test_cooldown_dedup(self, detector_with_db, monkeypatch):
        """冷却期内相同结果不重复推送。"""
        ctx = detector_with_db

        ctx["matcher"].detect_faces = lambda img: [_FakeRect(100, 50, 300, 250)]
        ctx["matcher"].match = lambda feature: "member:1"
        ctx["matcher"].get_member_name = lambda mid: "张三"

        # 重新创建带冷却的 detector
        from app.detectors.face import FaceDetector
        detector = FaceDetector(skip_frames=1, cooldown=10.0)
        detector._matcher = ctx["matcher"]

        # 第一次检测 -> 产生事件
        events1 = detector.detect(ctx["make_frame"]())
        assert len(events1) == 1

        # 第二次检测（冷却期内）-> 空
        events2 = detector.detect(ctx["make_frame"]())
        assert events2 == []

    # ---- 场景 5: 模型未加载返回空 ----

    def test_model_not_loaded_returns_empty(self):
        """dlib 模型未加载时 detect() 返回空。"""
        from app.detectors.face import FaceDetector, FaceMatcher
        from app.detectors.base import Frame

        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher._dlib_loaded = False
        matcher._initialized = True

        detector = FaceDetector(skip_frames=1, cooldown=0.0)
        detector._matcher = matcher

        img = np.zeros((360, 640, 3), dtype=np.uint8)
        frame = Frame(image=img, ts=_time.time(), camera_id=0, frame_idx=0)

        events = detector.detect(frame)
        assert events == []
