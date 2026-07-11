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
        matcher.threshold = 0.4
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
        matcher.threshold = 0.4
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
        matcher.threshold = 0.4
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
        matcher.threshold = 0.4

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
        matcher.threshold = 0.4
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
        matcher.threshold = 0.4
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

    def test_stranger_returns_event(self, detector_with_db, monkeypatch):
        """人脸存在但未匹配 -> WebSocket 直接推送 stranger（带冷却去重）。"""
        ctx = detector_with_db
        self._mock_detect_faces = lambda img: [_FakeRect(100, 50, 300, 250)]
        ctx["matcher"].detect_faces = lambda img: [_FakeRect(100, 50, 300, 250)]

        # 捕获 WebSocket 推送
        pushed_msgs = []
        monkeypatch.setattr(
            "app.api.ws.broadcast_face_result",
            lambda msg: pushed_msgs.append(msg),
        )

        # 单帧直接推送（无投票窗口）
        events = ctx["detector"].detect(ctx["make_frame"]())
        assert events == []

        assert len(pushed_msgs) >= 1
        assert pushed_msgs[0]["type"] == "stranger"

    # ---- 场景 3: 会员匹配成功 ----

    def test_member_matched_returns_event(self, detector_with_db, monkeypatch):
        """人脸匹配到会员 -> WebSocket 推送 member 含 member_id 和 name。"""
        ctx = detector_with_db
        from app.models.entities import Member

        # 插入测试会员
        feature = _make_feature(1)
        m = Member(member_id=1, name="张三", feature=json.dumps(feature.tolist()))
        ctx["session"].add(m)
        ctx["session"].commit()

        ctx["matcher"].detect_faces = lambda img: [_FakeRect(100, 50, 300, 250)]

        # 捕获 WebSocket 推送
        pushed_msgs = []
        monkeypatch.setattr(
            "app.api.ws.broadcast_face_result",
            lambda msg: pushed_msgs.append(msg),
        )

        # 单帧直接推送（无投票窗口）
        events = ctx["detector"].detect(ctx["make_frame"]())
        assert events == []

        assert len(pushed_msgs) >= 1
        assert pushed_msgs[0]["type"] == "member"
        assert pushed_msgs[0]["member_id"] == 1
        assert pushed_msgs[0]["name"] == "张三"

    # ---- 场景 4: 冷却去重 ----

    def test_cooldown_dedup(self, detector_with_db, monkeypatch):
        """冷却期内相同结果不重复推送。"""
        ctx = detector_with_db

        ctx["matcher"].detect_faces = lambda img: [_FakeRect(100, 50, 300, 250)]

        # 捕获 WebSocket 推送
        pushed_msgs = []
        monkeypatch.setattr(
            "app.api.ws.broadcast_face_result",
            lambda msg: pushed_msgs.append(msg),
        )

        # 重新创建带冷却的 detector
        from app.detectors.face import FaceDetector
        detector = FaceDetector(skip_frames=1, cooldown=10.0)
        detector._matcher = ctx["matcher"]

        # 单帧 → 第一次推送
        events = detector.detect(ctx["make_frame"]())
        assert events == []
        assert len(pushed_msgs) == 1

        # 冷却期内：相同结果不重复推送
        events2 = detector.detect(ctx["make_frame"]())
        assert events2 == []
        assert len(pushed_msgs) == 1  # 仍是 1 次

    def test_single_low_liveness_frame_does_not_spoof(self, detector_with_db, monkeypatch):
        """单帧低分不触发欺骗（需要连续 2 帧低分）。"""
        ctx = detector_with_db

        pushed_msgs = []
        monkeypatch.setattr(
            "app.api.ws.broadcast_face_result",
            lambda msg: pushed_msgs.append(msg),
        )

        class _LiveStub:
            enabled = True
            threshold = 0.5

            def __init__(self):
                self.calls = 0

            def check(self, face_crop, landmarks, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    # 第一帧：正常通过
                    return {
                        "score": 0.75,
                        "is_spoof": False,
                        "reasons": [],
                        "details": {"frames_cached": 5},
                    }
                if self.calls == 2:
                    # 第二帧：单帧低分（不足以触发）
                    return {
                        "score": 0.15,
                        "is_spoof": False,  # LivenessDetector内部streak=1，仍不触发is_spoof
                        "reasons": ["freq_anomaly"],
                        "details": {"frames_cached": 6},
                    }
                # 第三帧及以后：恢复正常（streak 被 reset）
                return {
                    "score": 0.72,
                    "is_spoof": False,
                    "reasons": [],
                    "details": {"frames_cached": 7},
                }

        ctx["detector"]._liveness = _LiveStub()

        # 第1帧：正常 → 无 spoof 事件
        events1 = ctx["detector"].detect(ctx["make_frame"]())
        spoof_events = [e for e in events1 if getattr(e, 'type', '') == "face_spoof"]
        assert spoof_events == []

        # 第2帧：单帧低分 → 不触发 spoof（streak=1）
        events2 = ctx["detector"].detect(ctx["make_frame"]())
        spoof_events2 = [e for e in events2 if getattr(e, 'type', '') == "face_spoof"]
        assert spoof_events2 == []

        # 第3帧：恢复正常 → 无 spoof 事件
        events3 = ctx["detector"].detect(ctx["make_frame"]())
        spoof_events3 = [e for e in events3 if getattr(e, 'type', '') == "face_spoof"]
        assert spoof_events3 == []

    def test_three_stable_low_frames_trigger_spoof(self, detector_with_db, monkeypatch):
        """连续 2 帧低分应触发 face_spoof。"""
        ctx = detector_with_db

        pushed_msgs = []
        monkeypatch.setattr(
            "app.api.ws.broadcast_face_result",
            lambda msg: pushed_msgs.append(msg),
        )

        class _LiveStub:
            enabled = True
            threshold = 0.5

            def __init__(self):
                self.calls = 0

            def check(self, face_crop, landmarks, **kwargs):
                self.calls += 1
                # 连续低分 → 第2帧 is_spoof=True（LivenessDetector内部streak>=2）
                is_spoof = self.calls >= 2
                return {
                    "score": 0.17,
                    "is_spoof": is_spoof,
                    "reasons": ["prolonged_no_blink", "spoof_streak"] if is_spoof else ["prolonged_no_blink"],
                    "details": {"frames_cached": 5 + self.calls},
                }

        ctx["detector"]._liveness = _LiveStub()

        # 第1帧：低分 → streak=1，不触发 spoof
        events = ctx["detector"].detect(ctx["make_frame"]())
        spoof_events = [e for e in events if getattr(e, 'type', '') == "face_spoof"]
        assert spoof_events == []

        # 第2帧：低分 → streak=2 → 触发 face_spoof
        events = ctx["detector"].detect(ctx["make_frame"]())
        spoof_events2 = [e for e in events if getattr(e, 'type', '') == "face_spoof"]
        assert len(spoof_events2) == 1
        assert spoof_events2[0].type == "face_spoof"

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
