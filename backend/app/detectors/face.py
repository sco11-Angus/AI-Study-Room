"""人脸识别 — Dlib 128 维特征匹配（任务书 B9）。

- encode(face_img) -> 128 维向量（Dlib ResNet 模型）
- match(feature) -> "member:<id>" / "stranger"：欧氏距离最近邻，>0.6 判 stranger
- FaceDetector: 实现 Detector 接口，接入推理引擎做端到端人脸识别
"""
import json
import logging
import os
from typing import Optional

import numpy as np

from ..config import Config
from .base import AlarmEvent, Detector, Frame

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

    def __init__(self, threshold: float = 0.35):
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

    @property
    def dlib_loaded(self) -> bool:
        return self._dlib_loaded

    # ---- 人脸检测 ----

    def detect_faces(self, image: np.ndarray) -> list:
        """检测图像中所有人脸矩形。

        Args:
            image: BGR 图像

        Returns:
            dlib rectangle 列表，无人脸时为空列表
        """
        if not self._dlib_loaded:
            return []
        rgb = image[..., ::-1].copy()
        return self._detector(rgb, 1)

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

        rgb = face_img[..., ::-1].copy()  # BGR → RGB（dlib 要求，copy 确保内存连续）
        faces = self._detector(rgb, 1)
        if len(faces) == 0:
            return None
        shape = self._shape_predictor(rgb, faces[0])
        descriptor = self._face_encoder.compute_face_descriptor(rgb, shape)
        return np.array(descriptor)

    def encode_from_rect(self, image: np.ndarray, rect) -> Optional[np.ndarray]:
        """从已检测到的人脸矩形直接提取特征（不重复检测，更稳定）。

        Args:
            image: BGR 全帧图像
            rect: dlib rectangle（由 detect_faces() 返回）

        Returns:
            128 维 float 向量
        """
        if not self._dlib_loaded:
            return None
        rgb = image[..., ::-1].copy()
        shape = self._shape_predictor(rgb, rect)
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

    def get_member_name(self, member_id: int) -> Optional[str]:
        """查询会员姓名。"""
        from ..models.database import SessionLocal
        from ..models.entities import Member

        session = SessionLocal()
        try:
            m = session.query(Member).filter_by(member_id=member_id).first()
            return m.name if m else None
        except Exception:
            return None
        finally:
            session.close()


# ---- Detector 插件 ----

class FaceDetector(Detector):
    """人脸识别检测器 — 接入推理引擎，对每帧进行人脸检测+匹配。

    实现 Detector 接口：
    - setup(): 加载 dlib 模型
    - detect(frame): 检测人脸 → 特征提取 → 会员匹配 → AlarmEvent
    """

    name = "face_recognition"
    enabled = True

    def __init__(self, skip_frames: int = 5, cooldown: float = 2.0):
        """初始化。

        Args:
            skip_frames: 每隔多少帧检测一次（降低算力开销）
            cooldown: 同一结果冷却时间（秒），避免重复推送
        """
        super().__init__()
        self._matcher: Optional[FaceMatcher] = None
        self._skip_frames = skip_frames
        self._cooldown = cooldown
        self._frame_count = 0
        self._last_result: Optional[str] = None
        self._last_result_ts: float = 0.0

    def setup(self) -> None:
        """加载 dlib 模型（引擎启动时调用一次）。"""
        self._matcher = FaceMatcher()
        if self._matcher.dlib_loaded:
            logger.info("[face] FaceDetector 已就绪")
        else:
            logger.warning("[face] FaceDetector 模型未加载，detect() 将返回空")

    def detect(self, frame: Frame) -> list[AlarmEvent]:
        """对单帧执行人脸识别。

        跳帧策略：每 self._skip_frames 帧检测一次 + 结果冷却去重。
        """
        if self._matcher is None or not self._matcher.dlib_loaded:
            return []

        self._frame_count += 1
        if self._frame_count % self._skip_frames != 0:
            return []

        import time

        # 检测人脸
        face_rects = self._matcher.detect_faces(frame.image)
        if not face_rects:
            if self._frame_count % 30 == 0:
                logger.debug("[face] detect() 未检测到人脸")
            return []

        logger.info(f"[face] 检测到 {len(face_rects)} 张人脸")

        # 取第一个人脸，直接用全帧 + 检测矩形提取特征（避免裁剪重检失败）
        rect = face_rects[0]

        # 特征提取
        feature = self._matcher.encode_from_rect(frame.image, rect)
        if feature is None:
            logger.warning("[face] encode_from_rect() 特征提取失败")
            return []

        # 裁剪人脸区域（仅用于 AlarmEvent）
        h, w = frame.image.shape[:2]
        x1 = max(0, rect.left())
        y1 = max(0, rect.top())
        x2 = min(w, rect.right())
        y2 = min(h, rect.bottom())
        face_crop = frame.image[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else None

        # 会员匹配
        result = self._matcher.match(feature)
        logger.info(f"[face] 匹配结果: {result}")

        # 冷却去重：冷却期内不再推送任何结果（避免特征漂移导致结果来回跳变）
        now = time.time()
        if (now - self._last_result_ts) < self._cooldown:
            return []
        self._last_result = result
        self._last_result_ts = now

        # 构造事件
        extra = {"face_match": result}
        if result.startswith("member:"):
            member_id = int(result.split(":")[1])
            name = self._matcher.get_member_name(member_id)
            extra["member_id"] = member_id
            extra["name"] = name or f"member_{member_id}"
        else:
            extra["name"] = "陌生人"

        # 直接写入最新结果（绕过 engine → alarm 链路）
        msg = {"type": "stranger"}
        if result.startswith("member:"):
            msg = {
                "type": "member",
                "member_id": extra["member_id"],
                "name": extra["name"],
            }
        try:
            from ..api.ws import set_face_result
            set_face_result(msg)
            logger.info(f"[face] 结果已写入: {msg}")
        except Exception as e:
            logger.error(f"[face] 写入结果失败: {e}")

        return [
            AlarmEvent(
                region_id=0,  # 人脸识别不绑定防区
                type="face_recognition",
                confidence=1.0,
                snapshot=frame.image,
                face_crop=face_crop,
                extra=extra,
            )
        ]
