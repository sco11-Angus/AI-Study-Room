"""B9 人脸特征匹配测试。

测试 FaceMatcher.match() 匹配逻辑（不依赖 dlib 模型）：
- 会员库为空 -> stranger
- 最近邻 < 阈值 -> member:id
- 最近邻 > 阈值 -> stranger
- 跳过损坏的特征数据
"""
import json
import os
import sys

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 不导入 face.py（避免触发 dlib import），直接测试 match 逻辑

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_feature(seed: int = 42) -> np.ndarray:
    """构造 128 维测试特征。"""
    rng = np.random.RandomState(seed)
    return rng.rand(128).astype(np.float64)


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

        # 另一个完全不同的特征
        unknown = _make_feature(99)
        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6
        assert matcher.match(unknown) == "stranger"

    def test_nearest_neighbor_wins(self, db):
        """多会员中选最近邻。"""
        from app.models.entities import Member
        from app.detectors.face import FaceMatcher

        # member 1: seed=1 的特征
        f1 = _make_feature(1)
        m1 = Member(member_id=1, name="Alice", feature=json.dumps(f1.tolist()))
        # member 2: seed=2 的特征
        f2 = _make_feature(2)
        m2 = Member(member_id=2, name="Bob", feature=json.dumps(f2.tolist()))
        db.add_all([m1, m2])
        db.commit()

        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6

        # 用 f1 去匹配，期望返回 member:1
        assert matcher.match(f1) == "member:1"
        # 用 f2 去匹配，期望返回 member:2
        assert matcher.match(f2) == "member:2"

    def test_corrupted_feature_skipped(self, db):
        """损坏的特征数据被跳过，仍能匹配到有效会员。"""
        from app.models.entities import Member
        from app.detectors.face import FaceMatcher

        # 坏数据
        m_bad = Member(member_id=99, name="corrupted", feature="not-valid-json")
        # 好数据
        f_good = _make_feature(1)
        m_good = Member(member_id=1, name="Good", feature=json.dumps(f_good.tolist()))
        db.add_all([m_bad, m_good])
        db.commit()

        matcher = FaceMatcher.__new__(FaceMatcher)
        matcher.threshold = 0.6
        assert matcher.match(f_good) == "member:1"
