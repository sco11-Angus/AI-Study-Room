"""人脸识别 — Dlib 128 维特征匹配（任务书 B9）。

- encode(face_img) -> 128 维向量（Dlib ResNet 模型）
- match(feature) -> "member:<id>" / "stranger"：欧氏距离最近邻，>0.6 判 stranger
- FaceDetector: 实现 Detector 接口，接入推理引擎做端到端人脸识别
- 集成 LivenessDetector 活体检测：防御静态照片/视频回放/AI换脸
"""
import json
import logging
import os
from collections import deque
from typing import Optional

import numpy as np

from ..config import Config
from ..models.entities import Member
from .base import AlarmEvent, Detector, Frame
from .liveness import LivenessDetector

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

    def shape_from_rect(self, image: np.ndarray, rect):
        """从人脸矩形提取 68 点 landmarks。

        Args:
            image: BGR 全帧图像
            rect: dlib rectangle（由 detect_faces() 返回）

        Returns:
            dlib full_object_detection，或 None
        """
        if not self._dlib_loaded:
            return None
        rgb = image[..., ::-1].copy()
        return self._shape_predictor(rgb, rect)

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
        if not getattr(self, "_shape_predictor", None) or not getattr(self, "_face_encoder", None):
            h, w = image.shape[:2]
            x1 = max(0, rect.left())
            y1 = max(0, rect.top())
            x2 = min(w, rect.right())
            y2 = min(h, rect.bottom())
            if x2 <= x1 or y2 <= y1:
                return None
            return self.encode(image[y1:y2, x1:x2])
        rgb = image[..., ::-1].copy()
        shape = self._shape_predictor(rgb, rect)
        descriptor = self._face_encoder.compute_face_descriptor(rgb, shape)
        return np.array(descriptor)

    # ---- 会员匹配 ----

    @staticmethod
    def _load_features(feature_json: str) -> list[np.ndarray]:
        """解析会员 feature JSON，兼容单/多参考特征。

        - 单向量 [0.1, 0.2, ...] → [[0.1, 0.2, ...]]
        - 多向量 [[0.1, ...], [0.2, ...]] → [[0.1, ...], [0.2, ...]]
        """
        data = json.loads(feature_json)
        arr = np.array(data)
        if arr.ndim == 1:
            return [arr]
        return [arr[i] for i in range(arr.shape[0])]

    def match(self, feature: np.ndarray) -> str:
        """与会员特征库比对，返回最近邻结果。

        对每个会员取所有参考特征的最小欧氏距离作为匹配距离。

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
            second_best_dist = float("inf")
            for m in members:
                if not m.feature:
                    continue
                try:
                    refs = FaceMatcher._load_features(m.feature)
                    dist = min(float(np.linalg.norm(feature - ref)) for ref in refs)
                    if dist < best_dist:
                        second_best_dist = best_dist
                        best_dist = dist
                        best_id = m.member_id
                    elif dist < second_best_dist:
                        second_best_dist = dist
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"[face] 会员 {m.member_id} 特征数据损坏，已跳过: {e}")
                    continue

            nrr = best_dist / second_best_dist if second_best_dist < float("inf") else 1.0
            gap = second_best_dist - best_dist if second_best_dist < float("inf") else 0
            if (
                best_id is not None
                and best_dist < self.threshold
                and (nrr < 0.9 or gap > 0.05 or second_best_dist >= float("inf"))
            ):
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
    - detect(frame): 检测人脸 → 活体检测 → 特征提取 → 会员匹配 → AlarmEvent
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
        self._liveness: Optional[LivenessDetector] = None
        self._skip_frames = skip_frames
        self._cooldown = cooldown
        self._frame_count = 0
        self._last_result: Optional[str] = None
        self._last_result_ts: float = 0.0
        # 人脸裁剪历史（供活体检测微动分析）
        self._face_crop_history: deque = deque(maxlen=Config.LIVENESS_HISTORY_SIZE)
        # 滑动窗口投票：去抖动，只有连续 N 帧一致才推送
        self._vote_window: deque = deque(maxlen=3)
        self._stable_result: Optional[str] = None
        # 诊断：记录最近的特征向量前5维 + 距离
        self._last_feature_snapshot: Optional[list] = None

    def setup(self) -> None:
        """加载 dlib 模型（引擎启动时调用一次）。"""
        self._matcher = FaceMatcher()
        if self._matcher.dlib_loaded:
            logger.info("[face] FaceDetector 已就绪")
        else:
            logger.warning("[face] FaceDetector 模型未加载，detect() 将返回空")

        # 初始化活体检测器
        self._liveness = LivenessDetector(
            enabled=Config.LIVENESS_ENABLED,
            threshold=Config.LIVENESS_THRESHOLD,
            history_size=Config.LIVENESS_HISTORY_SIZE,
            ear_blink_thresh=Config.LIVENESS_EAR_BLINK_THRESH,
        )
        if Config.LIVENESS_ENABLED:
            logger.info("[face] 活体检测已启用 (threshold=%.2f)", Config.LIVENESS_THRESHOLD)
        else:
            logger.info("[face] 活体检测已禁用")

    def detect(self, frame: Frame) -> list[AlarmEvent]:
        """对单帧执行人脸识别。

        流程：人脸检测 → 活体检测 → 特征提取 → 会员匹配
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

        # 取第一个人脸
        rect = face_rects[0]

        # 裁剪人脸区域
        h, w = frame.image.shape[:2]
        x1 = max(0, rect.left())
        y1 = max(0, rect.top())
        x2 = min(w, rect.right())
        y2 = min(h, rect.bottom())
        face_crop = frame.image[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else None

        # ---- 活体检测 ----
        if self._liveness is not None and self._liveness.enabled:
            landmarks = self._matcher.shape_from_rect(frame.image, rect)
            if landmarks is not None and face_crop is not None:
                liveness_result = self._liveness.check(face_crop, landmarks)
                score = liveness_result["score"]
                reasons = liveness_result["reasons"]
                logger.info(
                    "[face] 活体分数=%.3f reasons=%s details=%s",
                    score, reasons, liveness_result["details"],
                )

                if score < self._liveness.threshold:
                    logger.warning("[face] 活体检测失败，判定为欺骗攻击！")
                    # 清空投票窗口，防止旧帧结果泄漏
                    self._vote_window.clear()
                    self._stable_result = None
                    # 写入 WebSocket
                    msg = {
                        "type": "face_spoof",
                        "confidence": round(1.0 - score, 3),
                        "reasons": reasons,
                    }
                    try:
                        from ..api.ws import broadcast_face_result
                        broadcast_face_result(msg)
                    except Exception as e:
                        logger.error(f"[face] 写入 face_spoof 失败: {e}")

                    return [
                        AlarmEvent(
                            region_id=0,
                            type="face_spoof",
                            confidence=1.0 - score,
                            snapshot=frame.image,
                            face_crop=face_crop,
                            extra={
                                "liveness_score": score,
                                "reasons": reasons,
                                "details": liveness_result["details"],
                            },
                        )
                    ]

                # 热身期：活体检测需要积累历史才能可靠判定
                frames_cached = liveness_result["details"]["frames_cached"]
                if frames_cached < 5:
                    logger.info(f"[face] 活体热身中 (frames={frames_cached})，跳过匹配")
                    return []

        # ---- 特征提取 ----
        feature = self._matcher.encode_from_rect(frame.image, rect)
        if feature is None:
            logger.warning("[face] encode_from_rect() 特征提取失败")
            return []

        # ---- 诊断：输出特征向量 + 逐一比对距离 ----
        feat_snap = [round(float(feature[i]), 4) for i in range(min(5, len(feature)))]
        result, extra = self._match_with_diag(feature, feat_snap)
        now = time.time()
        if (now - self._last_result_ts) < self._cooldown:
            return []
        self._last_result = result
        self._last_result_ts = now
        self._push_result(result, extra, face_crop, frame)

        return [
            AlarmEvent(
                region_id=0,
                type="face_recognition",
                confidence=1.0,
                snapshot=frame.image,
                face_crop=face_crop,
                extra=extra,
            )
        ]
        logger.info(f"[face] 匹配结果: {result} | feat前5维: {feat_snap}")

        # ---- 滑动窗口投票（去抖动） ----
        self._vote_window.append(result)
        # 窗口满后才做决策
        if len(self._vote_window) == self._vote_window.maxlen:
            unique = set(self._vote_window)
            if len(unique) == 1:
                consensus = list(unique)[0]
                if consensus != self._stable_result:
                    self._stable_result = consensus
                    self._last_result = consensus
                    self._last_result_ts = time.time()
                    self._push_result(consensus, extra, face_crop, frame)
            else:
                logger.info(f"[face] 窗口未一致，跳过: {list(self._vote_window)}")

        return []

    # ------------------------------------------------------------------
    # 诊断 + 推送辅助方法
    # ------------------------------------------------------------------

    def _match_with_diag(self, feature: np.ndarray, feat_snap: list) -> tuple[str, dict]:
        """执行匹配并输出逐一比对诊断日志。

        Returns:
            (result, extra_dict)
        """
        from ..models.database import SessionLocal

        import json as _json
        result = "stranger"
        extra = {"face_match": "stranger", "name": "陌生人"}

        session = SessionLocal()
        try:
            members = session.query(Member).all()
            if not members:
                return result, extra

            best_id = None
            best_dist = float("inf")
            second_best_dist = float("inf")
            all_dists = []

            for m in members:
                if not m.feature:
                    continue
                try:
                    refs = FaceMatcher._load_features(m.feature)
                    dist = min(float(np.linalg.norm(feature - ref)) for ref in refs)
                    all_dists.append((m.member_id, m.name, dist))
                    if dist < best_dist:
                        second_best_dist = best_dist
                        best_dist = dist
                        best_id = m.member_id
                    elif dist < second_best_dist:
                        second_best_dist = dist
                except (_json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"[face] 会员 {m.member_id} 特征数据损坏: {e}")

            # 输出诊断
            nrr = best_dist / second_best_dist if second_best_dist < float("inf") else 1.0
            diag_parts = [f"dist={best_dist:.4f} nrr={nrr:.3f} thr={self._matcher.threshold}"]
            for mid, name, d in sorted(all_dists, key=lambda x: x[2]):
                marker = "*" if mid == best_id else ""
                diag_parts.append(f"m{mid}({name or '?'})={d:.4f}{marker}")
            logger.info(f"[face] feat前5={feat_snap} | {'; '.join(diag_parts)}")

            # NNR 判定：最佳匹配必须显著优于次佳匹配
            gap = second_best_dist - best_dist if second_best_dist < float("inf") else 0
            if (
                best_id is not None
                and best_dist < self._matcher.threshold
                and (nrr < 0.9 or gap > 0.05 or second_best_dist >= float("inf"))
            ):
                result = f"member:{best_id}"
                # 找名字
                member_name = None
                for mid, name, _ in all_dists:
                    if mid == best_id:
                        member_name = name
                        break
                extra = {
                    "face_match": result,
                    "member_id": best_id,
                    "name": member_name or f"member_{best_id}",
                    "distance": round(best_dist, 4),
                }

        except Exception:
            logger.exception("[face] 匹配诊断失败")
        finally:
            session.close()

        return result, extra

    def _push_result(self, result: str, extra: dict, face_crop, frame: Frame) -> None:
        """将匹配结果推送到 WebSocket + 产出 AlarmEvent。"""
        msg = {"type": "stranger"}
        if result.startswith("member:"):
            msg = {
                "type": "member",
                "member_id": extra.get("member_id"),
                "name": extra.get("name"),
            }
        try:
            from ..api.ws import broadcast_face_result
            broadcast_face_result(msg)
            logger.info(f"[face] 投票通过，推送: {msg}")
        except Exception as e:
            logger.error(f"[face] 写入结果失败: {e}")
