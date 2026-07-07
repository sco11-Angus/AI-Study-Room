"""人脸识别 — Dlib 128 维特征匹配（任务书 B9）。

- encode(face_img) -> 128 维向量（Dlib ResNet 模型）
- match(feature) -> "member:<id>" / "stranger"：欧氏距离最近邻，>0.6 判 stranger
- 不是 Detector 插件，是 E 的 AlarmService 抓拍时同步调用的服务。
"""
import json
import logging
import os
from typing import Optional

import numpy as np

from ..config import Config

logger = logging.getLogger(__name__)

# dlib 模型路径
_SHAPE_PREDICTOR = os.path.join(Config.MODEL_DIR, "shape_predictor_68_face_landmarks.dat")
_FACE_REC_MODEL = os.path.join(Config.MODEL_DIR, "dlib_face_recognition_resnet_model_v1.dat")


class FaceMatcher:
    """人脸特征提取与匹配（单例，模型仅加载一次）。"""

    _instance: Optional["FaceMatcher"] = None

    def __new__(cls, threshold: float = 0.6):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, threshold: float = 0.6):
        if self._initialized:
            return
        self.threshold = threshold
        self._detector = None
        self._shape_predictor = None
        self._face_encoder = None
        self._dlib_loaded = False
        self._try_load_models()
        self._initialized = True

    def _try_load_models(self):
        """尝试加载 dlib 模型（生产环境必须存在）。"""
        try:
            import dlib
            self._detector = dlib.get_frontal_face_detector()
            self._shape_predictor = dlib.shape_predictor(_SHAPE_PREDICTOR)
            self._face_encoder = dlib.face_recognition_model_v1(_FACE_REC_MODEL)
            self._dlib_loaded = True
            logger.info("[face] FaceMatcher 已初始化（Dlib 模型加载完成）")
        except Exception as e:
            logger.warning(f"[face] Dlib 模型加载失败，encode() 不可用: {e}")

    # ---- 特征提取 ----

    def encode(self, face_img: np.ndarray) -> Optional[np.ndarray]:
        """提取 128 维人脸特征向量（需要 dlib 模型）。

        Args:
            face_img: BGR 人脸图像（裁剪后）

        Returns:
            128 维 float 向量，若未检测到人脸则返回 None
        """
        if not self._dlib_loaded:
            logger.error("[face] encode() 不可用：dlib 模型未加载")
            return None

        rgb = face_img[..., ::-1]  # BGR → RGB（dlib 要求）
        faces = self._detector(rgb, 1)
        if len(faces) == 0:
            return None
        shape = self._shape_predictor(rgb, faces[0])
        descriptor = self._face_encoder.compute_face_descriptor(rgb, shape)
        return np.array(descriptor)

    # ---- 会员匹配 ----

    def match(self, feature: np.ndarray) -> str:
        """与会员特征库比对，返回最近邻结果。

        Args:
            feature: 128 维人脸特征向量

        Returns:
            "member:<id>" 或 "stranger"
        """
        from ..models.database import SessionLocal
        from ..models.entities import Member

        session = SessionLocal()
        try:
            members = session.query(Member).all()
            if not members:
                return "stranger"

            best_id = None
            best_dist = float("inf")
            for m in members:
                if not m.feature:
                    continue
                try:
                    stored = np.array(json.loads(m.feature))
                    dist = float(np.linalg.norm(feature - stored))
                    if dist < best_dist:
                        best_dist = dist
                        best_id = m.member_id
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"[face] 会员 {m.member_id} 特征数据损坏，已跳过: {e}")
                    continue

            if best_id is not None and best_dist < self.threshold:
                return f"member:{best_id}"
            return "stranger"
        except Exception:
            logger.exception("[face] 人脸匹配查询失败")
            return "stranger"
        finally:
            session.close()
