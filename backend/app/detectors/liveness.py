"""活体检测 — 五层反欺骗纵深防御系统。

Layer 1: 三模型静态检测（AMTEN-FC ONNX/PyTorch + MiniFASNetV2）
Layer 2: 深度时序物理分析（光流边界 / 帧差分时空 / 多尺度相干 / 像素频谱 / 屏幕物理）
Layer 3: 3D 活体检测（EAR 眨眼 / head pose solvePnP / 面部光流 3D 运动模式）
Layer 4: 八维物理媒体伪影检测（FFT摩尔纹 / 功率谱 / LBP纹理 / RGB相关 / 高光反射
         + 噪声残差 / 微观方差 / DCT块效应）
Layer 5: 融合决策引擎（加权融合 + EMA 平滑 + 快速判定 + 连续确认）
"""
import logging
import math
from collections import deque
from typing import Optional, Tuple

import cv2
import numpy as np

from ..config import Config
from .antispoof_model import AntiSpoofDetector

logger = logging.getLogger(__name__)


class LivenessDetector:
    """五层融合活体检测器（Layer 4 含 8 个物理/图像子检测器）。

    每个 FaceDetector 实例持有一个 LivenessDetector，维护该人脸的帧历史与会话状态。
    """

    def __init__(
        self,
        enabled: bool = True,
        threshold: Optional[float] = None,
        history_size: int = 30,
        ear_blink_thresh: float = 0.25,
        ema_alpha: float = 0.3,
    ):
        """初始化五层活体检测器。

        Args:
            enabled: 是否启用
            threshold: 融合判定阈值，<threshold 判定为 spoof
            history_size: 帧历史 deque 容量
            ear_blink_thresh: EAR 眨眼判定阈值
            ema_alpha: EMA 平滑系数 (0~1)
        """
        self.enabled = enabled
        self.threshold = threshold if threshold is not None else Config.LIVENESS_THRESHOLD
        self.history_size = history_size if history_size else Config.LIVENESS_HISTORY_SIZE
        self.ear_blink_thresh = ear_blink_thresh if ear_blink_thresh else Config.LIVENESS_EAR_BLINK_THRESH
        self.ema_alpha = ema_alpha if ema_alpha else Config.LIVENESS_EMA_ALPHA

        # ---- 会话级状态 ----
        self._antispoof: Optional[AntiSpoofDetector] = None  # 延迟加载
        self._score_ema: float = 0.5
        self._spoof_streak: int = 0
        self._prev_face_crop: Optional[np.ndarray] = None
        self._prev_landmarks = None
        self._blink_ever_detected: bool = False
        self._frames_no_blink: int = 0

        # ---- deques ----
        self._face_crop_history: deque = deque(maxlen=history_size)
        self._deepfake_scores: deque[float] = deque(maxlen=30)
        self._static_scores: deque[float] = deque(maxlen=30)
        self._lbp_hist_history: list = []   # (histogram, timestamp) for Layer 2.1 / 2.3
        self._diff_means: deque[float] = deque(maxlen=64)
        self._pixel_sequences: deque = deque(maxlen=64)  # each: (100,) brightness
        self._pose_deque: deque = deque(maxlen=30)  # (pitch, yaw, roll)
        self._temporal_score_hist: deque[float] = deque(maxlen=20)

        # ---- Layer 2 内部状态 ----
        self._prev_gray: Optional[np.ndarray] = None
        self._prev_lbp_hist: Optional[np.ndarray] = None  # for 2.3 multi-scale tracking
        self._prev_full_gray: Optional[np.ndarray] = None  # for 2.1 optical flow boundary
        self._face_rect_history: deque = deque(maxlen=20)  # (x1,y1,x2,y2) for 2.1
        self._diff_mean_history: deque[float] = deque(maxlen=64)  # for 2.2 GOP periodicity

        # ---- 静态图片帧差检测 ----
        self._static_frame_streak: int = 0  # 连续静态帧计数

        # ---- 刚性运动检测（手持照片/屏幕晃动） ----
        self._rigid_motion_streak: int = 0  # 连续刚性运动帧计数

        # ---- 媒体伪影连续低分计数（防单帧误判） ----
        self._media_low_streak: int = 0
        self._static_low_streak: int = 0
        self._liveness_low_streak: int = 0
        self._temporal_low_streak: int = 0

        # ---- Layer 3 内部状态 ----
        self._ear_history: deque[float] = deque(maxlen=30)
        self._was_below_thresh: bool = False

    @property
    def _face_history(self):
        """向后兼容属性：返回人脸裁剪历史 deque。"""
        return self._face_crop_history

    # ==================================================================
    # Public API
    # ==================================================================

    def check(
        self, face_crop: np.ndarray, landmarks,
        crop_x: int = 0, crop_y: int = 0,
        full_frame: Optional[np.ndarray] = None,
    ) -> dict:
        """主入口：对单帧执行五层检测+融合决策。

        Args:
            face_crop: BGR 人脸裁剪 (H, W, 3)
            landmarks: dlib full_object_detection (68 点) 或 None
            crop_x, crop_y: 人脸在全帧中的左上角坐标
            full_frame: BGR 全帧图像（可选，用于 Layer 2 光流边界分析）

        Returns:
            {
                "score": float,       # 最终融合分 ∈[0,1], <threshold=spoof
                "is_spoof": bool,
                "reasons": [str],
                "details": {...}
            }
        """
        if not self.enabled:
            return {
                "score": 1.0, "is_spoof": False, "reasons": [],
                "details": self._empty_details(),
            }

        # ================================================================
        # FSD 预检门禁：先判断是否 AI 生成，拦截后才进入活体检测
        # ================================================================
        # 先积累帧历史（无论 FSD 结果如何），避免 frames_cached 永远为 0
        self._face_crop_history.append(face_crop.copy())

        # 注：全帧静态检测已移至 FaceDetector.detect() 前端，
        # 绕开 dlib bbox 抖动，O(1) 开销每帧都跑，无需在这里重复。

        fsd_score = 0.5
        if full_frame is not None:
            if self._antispoof is None:
                self._antispoof = AntiSpoofDetector()
            fsd_score = self._antispoof.detect_fsd_only(full_frame)

        # FSD 检测到强 AI 生成信号 → 直接拦截，不跑后续活体流水线
        if fsd_score < 0.05:
            reasons: list[str] = ["fsd_detected_aigc"]
            return self._spoof_result(0.15, reasons, 0.5, 0.0, 0.40,
                                       0.5, 0.5, 0.5, 0.15, fsd_score)

        # ================================================================
        # FSD 预检通过 → 进入活体检测流水线
        # ================================================================

        # ---- Layer 1: 四模型静态检测 ----
        deepfake, minifas, static_score, _ = self._layer1_static(face_crop, full_frame=full_frame)

        # ---- Layer 2: 深度时序物理分析 (需要全帧) ----
        temporal_score = self._layer2_temporal(
            face_crop, landmarks, crop_x, crop_y, full_frame,
        )

        # ---- Layer 3: 3D 活体检测 ----
        liveness_score = self._layer3_liveness(face_crop, landmarks, crop_x, crop_y)

        # ---- Layer 4: 物理媒体伪影检测 ----
        media_score = self._layer4_media(face_crop)

        self._temporal_score_hist.append(temporal_score)

        # ---- Layer 5: 快速判定 ----
        reasons: list[str] = []

        # 快速判定 1: 深度伪造模型强检测
        if deepfake < 0.15 and len(self._face_crop_history) > 3:
            reasons.append("deepfake_fast_reject")
            return self._spoof_result(0.15, reasons, deepfake, minifas, static_score,
                                       temporal_score, liveness_score, media_score, 0.15, fsd_score)

        # 快速判定 2: 三模型综合静态分过低（需连续 ≥3 帧确认，防单帧噪声误判）
        if static_score < 0.25:
            self._static_low_streak += 1
        else:
            self._static_low_streak = 0
        if self._static_low_streak >= 3:
            reasons.append("static_fast_reject")
            return self._spoof_result(0.20, reasons, deepfake, minifas, static_score,
                                       temporal_score, liveness_score, media_score, 0.20, fsd_score)

        # 快速判定 3: 物理媒体伪影（需连续 ≥3 帧确认，防单帧噪声误判）
        if media_score < 0.30:
            self._media_low_streak += 1
        else:
            self._media_low_streak = 0
        if self._media_low_streak >= 3:
            reasons.append("media_fast_reject")
            return self._spoof_result(0.25, reasons, deepfake, minifas, static_score,
                                       temporal_score, liveness_score, media_score, 0.25, fsd_score)

        # 快速判定 4: 长时间无眨眼（真人可能盯着屏幕，放宽到 60 帧 ~12s）
        if self._frames_no_blink > 50:
            reasons.append("prolonged_no_blink")
            return self._spoof_result(0.25, reasons, deepfake, minifas, static_score,
                                       temporal_score, liveness_score, media_score, 0.25, fsd_score)

        # 快速判定 5: 活体关键拦截（需连续 ≥3 帧确认，防侧脸/暗光误判）
        if liveness_score < 0.35:
            self._liveness_low_streak += 1
        else:
            self._liveness_low_streak = 0
        if self._liveness_low_streak >= 3 and len(self._face_crop_history) > 10:
            reasons.append("liveness_critical")
            return self._spoof_result(0.30, reasons, deepfake, minifas, static_score,
                                       temporal_score, liveness_score, media_score, 0.30, fsd_score)

        # 快速判定 6: 时序异常
        #   score < 0.10 → 零运动（静态照片），需 15 帧累积避免真人静坐误判
        if temporal_score < 0.10 and len(self._face_crop_history) > 15:
            reasons.append("temporal_zero_motion")
            return self._spoof_result(0.10, reasons, deepfake, minifas, static_score,
                                       temporal_score, liveness_score, media_score, 0.10, fsd_score)
        if temporal_score < 0.20:
            self._temporal_low_streak += 1
        else:
            self._temporal_low_streak = 0
        if self._temporal_low_streak >= 3 and len(self._face_crop_history) > 10:
            reasons.append("temporal_critical")
            return self._spoof_result(0.30, reasons, deepfake, minifas, static_score,
                                       temporal_score, liveness_score, media_score, 0.30, fsd_score)

        # 快速判定 8: 刚性运动检测（手持照片/屏幕平移晃动）
        # 人脸区域内帧差空间方差极低 → 整张照片在平移而非真人局部形变
        # 附加条件：时序子特征也必须给出低分（< 0.45），避免真人微动误判
        if self._rigid_motion_streak >= 5 and temporal_score < 0.45:
            reasons.append("temporal_rigid_motion")
            return self._spoof_result(0.20, reasons, deepfake, minifas, static_score,
                                       temporal_score, liveness_score, media_score, 0.20, fsd_score)

        # ---- Layer 5: 综合加权融合 ----
        # 权重: static 30% / temporal 25% / liveness 25% / media 20%
        final_raw = (
            0.30 * static_score
            + 0.25 * temporal_score
            + 0.25 * liveness_score
            + 0.20 * media_score
        )
        final_raw = float(np.clip(final_raw, 0.0, 1.0))

        # EMA 平滑
        self._score_ema = self.ema_alpha * final_raw + (1.0 - self.ema_alpha) * self._score_ema
        final_smoothed = float(np.clip(self._score_ema, 0.0, 1.0))

        # 连续确认
        if final_smoothed < self.threshold:
            self._spoof_streak += 1
            if self._spoof_streak >= 5:
                reasons.append("spoof_streak")
                return self._spoof_result(final_smoothed, reasons, deepfake, minifas, static_score,
                                           temporal_score, liveness_score, media_score, final_raw, fsd_score)
        else:
            self._spoof_streak = 0

        # ---- 更新 prev ----
        self._prev_face_crop = face_crop.copy()
        self._prev_landmarks = landmarks
        self._prev_gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)

        return {
            "score": round(final_smoothed, 3),
            "is_spoof": False,
            "reasons": [],
            "details": {
                "deepfake_score": round(deepfake, 3),
                "minifas_score": round(minifas, 3),
                "static_score": round(static_score, 3),
                "fsd_score": round(fsd_score, 3),
                "temporal_score": round(temporal_score, 3),
                "liveness_score": round(liveness_score, 3),
                "media_score": round(media_score, 3),
                "final_raw": round(final_raw, 3),
                "final_smoothed": round(final_smoothed, 3),
                "frames_cached": len(self._face_crop_history),
            },
        }

    def _check_static_image(self, face_crop: np.ndarray, threshold: float = 0.003,
                              min_streak: int = 3) -> bool:
        """帧差静态图片检测 + 单帧纹理预检。

        1) 单帧 Laplacian 方差：照片/屏幕翻拍纹理远不如真人丰富
        2) 双帧 MSE：连续帧几乎无变化 → 静态图片攻击

        阈值说明：
        - 真正静态照片：nmse < 0.0005（像素几乎完全不变）
        - 真人轻微晃动：nmse 0.005~0.03
        - threshold=0.003 留有足够余量，避免真人误判
        """
        # ---- 单帧纹理预检：Laplacian 方差 ----
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            is_blurry = lap_var < 80  # 真人通常 >150，照片/屏幕 <80
        except Exception:
            lap_var = 999
            is_blurry = False

        # ---- 双帧 MSE 比较 ----
        if self._prev_face_crop is None:
            # 首帧：预种子，纹理异常直接起疑
            self._static_frame_streak = 1 if is_blurry else 0
            if is_blurry:
                logger.info("[static] 单帧纹理异常 lap_var=%.1f streak=%d/%d",
                            lap_var, self._static_frame_streak, min_streak)
            return False

        try:
            target_size = (64, 64)
            prev = cv2.resize(self._prev_face_crop, target_size)
            curr = cv2.resize(face_crop, target_size)

            prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY).astype(np.float32)
            curr_gray = cv2.cvtColor(curr, cv2.COLOR_BGR2GRAY).astype(np.float32)

            mse = float(np.mean((prev_gray - curr_gray) ** 2))
            nmse = mse / (255.0 ** 2)

            if nmse < threshold:
                self._static_frame_streak += 1
            else:
                self._static_frame_streak = max(0, self._static_frame_streak - 1)

            is_static = self._static_frame_streak >= min_streak
            if self._static_frame_streak > 0 or nmse < 0.05:
                logger.info(
                    "[static] nmse=%.6f lap_var=%.1f streak=%d/%d static=%s",
                    nmse, lap_var, self._static_frame_streak, min_streak, is_static,
                )
            return is_static
        except Exception:
            self._static_frame_streak = 0
            return False

    def reset(self) -> None:
        """清空所有历史状态（换人时调用）。"""
        self._score_ema = 0.5
        self._spoof_streak = 0
        self._prev_face_crop = None
        self._prev_landmarks = None
        self._blink_ever_detected = False
        self._frames_no_blink = 0

        self._face_crop_history.clear()
        self._deepfake_scores.clear()
        self._static_scores.clear()
        self._lbp_hist_history.clear()
        self._diff_means.clear()
        self._pixel_sequences.clear()
        self._pose_deque.clear()
        self._temporal_score_hist.clear()

        self._prev_gray = None
        self._prev_lbp_hist = None
        self._prev_full_gray = None
        self._face_rect_history.clear()
        self._diff_mean_history.clear()
        self._static_frame_streak = 0
        self._rigid_motion_streak = 0
        self._media_low_streak = 0
        self._static_low_streak = 0
        self._liveness_low_streak = 0
        self._temporal_low_streak = 0
        self._ear_history.clear()
        self._was_below_thresh = False

    # ==================================================================
    # Layer 1: 三模型静态检测
    # ==================================================================

    def _layer1_static(self, face_crop: np.ndarray, full_frame: np.ndarray = None) -> Tuple[float, float, float, float]:
        """四模型 ensemble 推理：FSD + AMTEN-FC + MiniFASNetV2 → 静态融合分。

        Args:
            face_crop: 人脸裁剪 (128×128)
            full_frame: 全帧图像。FSD 在全帧上分析换脸伪影

        Returns:
            (deepfake_score, minifas_score, static_score, fsd_score)
        """
        try:
            if self._antispoof is None:
                self._antispoof = AntiSpoofDetector()
            deepfake, minifas, static_score, fsd_score = self._antispoof.detect(
                face_crop, full_frame=full_frame,
            )
            self._deepfake_scores.append(deepfake)
            self._static_scores.append(static_score)
            return deepfake, minifas, static_score, fsd_score
        except Exception:
            logger.warning("[liveness] Layer 1 推理异常", exc_info=True)
            return 0.5, 0.5, 0.5, 0.5

    # ==================================================================
    # Layer 2: 深度时序物理分析
    # ==================================================================

    def _layer2_temporal(
        self, face_crop: np.ndarray, landmarks, crop_x: int, crop_y: int,
        full_frame: Optional[np.ndarray] = None,
    ) -> float:
        """五维时序特征融合（同时检测 DeepFake 异常变化 + 静态照片零变化）。

        Returns:
            temporal_score ∈ [0, 1], <0.3 表示可疑
        """
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        except Exception:
            return 0.5

        # ---- 零运动预检：连续帧完全无变化 → 静态照片/视频循环 ----
        if self._prev_gray is not None:
            try:
                # resize 到统一尺寸，避免人脸框大小变化导致广播错误
                prev_r = cv2.resize(self._prev_gray, (64, 64)).astype(np.float32)
                curr_r = cv2.resize(gray, (64, 64)).astype(np.float32)
                mad = float(np.mean(np.abs(curr_r - prev_r)))
                if mad < 2.0:  # avg pixel diff < 2/255 → 几乎完全静止（照片/死循环）
                    return 0.10  # 极低分，直接触发 temporal_zero_motion 快拒
            except Exception:
                pass  # resize 失败则跳过零运动检测，继续常规流程

        # ---- 刚性运动预检：照片/屏幕整体平移 vs 真人局部形变 ----
        # 核心原理：手持照片晃动时整张照片所有像素同方向同速度平移，
        # 帧差空间分布高度均匀。真人面部不同区域运动模式各异（眼/嘴/鼻/颧骨）。
        if self._prev_gray is not None:
            try:
                prev_r = cv2.resize(self._prev_gray, (64, 64)).astype(np.float32)
                curr_r = cv2.resize(gray, (64, 64)).astype(np.float32)
                diff = np.abs(curr_r - prev_r)

                # 4x4 网格，16 个 cell，各 cell 的帧差均值
                cell_size = 16  # 64 / 4 = 16
                cell_means = []
                for i in range(4):
                    for j in range(4):
                        cell = diff[i*cell_size:(i+1)*cell_size,
                                    j*cell_size:(j+1)*cell_size]
                        cell_means.append(float(np.mean(cell)))

                mean_of_cells = float(np.mean(cell_means))
                std_of_cells = float(np.std(cell_means))
                cv_rigidity = std_of_cells / (mean_of_cells + 1e-6)

                # cv_rigidity < 0.5 → 各cell帧差几乎相同 → 刚性平移（照片/屏幕）
                # cv_rigidity > 1.0 → 各cell帧差差异大 → 真人局部运动
                # 同时要求 mean_of_cells > 1.5（确有意义运动，不是静止噪声）
                if mean_of_cells > 1.5 and cv_rigidity < 0.5:
                    self._rigid_motion_streak += 1
                else:
                    self._rigid_motion_streak = max(0, self._rigid_motion_streak - 1)
            except Exception:
                pass  # 检测失败不影响后续流程

        # 子特征 1 (0.25): 全帧光流场边界一致性（检测 AI换脸 人脸"贴图"）
        s1 = self._optical_flow_boundary(face_crop, full_frame, crop_x, crop_y)

        # 子特征 2 (0.25): 帧差分图时空结构（人脸/背景噪声差异 + GOP周期性）
        s2 = self._diff_structure_analysis(gray, face_crop, full_frame, crop_x, crop_y)

        # 子特征 3 (0.20): 多尺度纹理时序相干性（AI换脸尺度脱钩）
        s3 = self._multi_scale_texture_coherence(gray)

        # 子特征 4 (0.15): 像素时序频谱一致性（面部区域生成不均）
        s4 = self._pixel_spectral_consistency(gray)

        # 子特征 5 (0.15): 屏幕物理特征综合检测
        s5 = self._screen_physical_features(gray, face_crop)

        score = 0.25 * s1 + 0.25 * s2 + 0.20 * s3 + 0.15 * s4 + 0.15 * s5
        return float(np.clip(score, 0.0, 1.0))

    # ---- 子特征 1: 全帧光流场边界一致性分析 ----

    def _optical_flow_boundary(
        self, face_crop: np.ndarray, full_frame: Optional[np.ndarray],
        crop_x: int, crop_y: int,
    ) -> float:
        """全帧光流场在人脸边界处的一致性分析。

        核心洞察：AI换脸的人脸区域是逐帧"贴"上去的，人脸边界两侧
        光流矢量方向不连续。真实视频中人脸随头部/背景整体运动，边界平滑。

        Returns:
            score ∈ [0, 1], <0.5 表示检测到光流断裂
        """
        try:
            if full_frame is None or self._prev_full_gray is None:
                if full_frame is not None:
                    self._prev_full_gray = cv2.cvtColor(full_frame, cv2.COLOR_BGR2GRAY)
                return 0.5

            h, w = face_crop.shape[:2]
            fh, fw = full_frame.shape[:2]
            curr_full_gray = cv2.cvtColor(full_frame, cv2.COLOR_BGR2GRAY)

            # 确保上一帧尺寸一致
            if self._prev_full_gray.shape != curr_full_gray.shape:
                self._prev_full_gray = curr_full_gray
                return 0.5

            # Farneback 密集光流
            flow = cv2.calcOpticalFlowFarneback(
                self._prev_full_gray, curr_full_gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
            )

            self._prev_full_gray = curr_full_gray

            # 人脸矩形坐标（裁剪 + 扩展 margin 获取边界带）
            x1, y1 = max(0, crop_x), max(0, crop_y)
            x2, y2 = min(fw, crop_x + w), min(fh, crop_y + h)

            if x2 - x1 < 20 or y2 - y1 < 20:
                return 0.5

            # 边界环形带: 人脸矩形向内和向外各扩 8px 的环
            margin = 8
            inner_x1 = x1 + margin; inner_y1 = y1 + margin
            inner_x2 = x2 - margin; inner_y2 = y2 - margin
            outer_x1 = max(0, x1 - margin); outer_y1 = max(0, y1 - margin)
            outer_x2 = min(fw, x2 + margin); outer_y2 = min(fh, y2 + margin)

            # 环形带内光流 → 人脸侧 vs 背景侧
            # 简化：取边界附近两排像素，比较光流方向余弦相似度
            ring_inner_flows = []
            ring_outer_flows = []

            # 上边界
            if inner_y1 > 0 and outer_y1 >= 0:
                for px in range(max(0, x1 - margin), min(fw, x2 + margin)):
                    ring_inner_flows.append(flow[inner_y1, px])
                    if outer_y1 < fh:
                        ring_outer_flows.append(flow[outer_y1, px])

            # 下边界
            if inner_y2 < fh and outer_y2 <= fh:
                for px in range(max(0, x1 - margin), min(fw, x2 + margin)):
                    if inner_y2 - 1 >= 0:
                        ring_inner_flows.append(flow[inner_y2 - 1, px])
                    if outer_y2 - 1 >= 0 and outer_y2 - 1 < fh:
                        ring_outer_flows.append(flow[outer_y2 - 1, px])

            # 左边界
            if inner_x1 > 0 and outer_x1 >= 0:
                for py in range(max(0, y1 - margin), min(fh, y2 + margin)):
                    ring_inner_flows.append(flow[py, inner_x1])
                    if outer_x1 < fw:
                        ring_outer_flows.append(flow[py, outer_x1])

            # 右边界
            if inner_x2 < fw and outer_x2 <= fw:
                for py in range(max(0, y1 - margin), min(fh, y2 + margin)):
                    if inner_x2 - 1 >= 0:
                        ring_inner_flows.append(flow[py, inner_x2 - 1])
                    if outer_x2 - 1 >= 0 and outer_x2 - 1 < fw:
                        ring_outer_flows.append(flow[py, outer_x2 - 1])

            if len(ring_inner_flows) < 10 or len(ring_outer_flows) < 10:
                return 0.5

            ring_inner = np.array(ring_inner_flows, dtype=np.float32)
            ring_outer = np.array(ring_outer_flows, dtype=np.float32)

            # 计算内外环每个位置的光流方向（角度）
            inner_angles = np.arctan2(ring_inner[:, 1], ring_inner[:, 0])
            outer_angles = np.arctan2(ring_outer[:, 1], ring_outer[:, 0])

            # 配对余弦相似度
            n = min(len(inner_angles), len(outer_angles))
            cos_sims = np.cos(inner_angles[:n] - outer_angles[:n])
            median_cos = float(np.median(cos_sims))

            # 内/外环光流幅值比（人脸区域 vs 背景区域运动量对比）
            inner_mag = np.linalg.norm(ring_inner[:n], axis=1)
            outer_mag = np.linalg.norm(ring_outer[:n], axis=1)
            # 使用中位数比避免极值干扰
            mag_ratio = float(np.median(inner_mag) / (np.median(outer_mag) + 1e-10))
            if mag_ratio < 1.0:
                mag_ratio = 1.0 / max(mag_ratio, 1e-10)
            # 归一化: ratio 1.0→1.0分, ratio >3.0→0.0分
            mag_score = float(np.clip(1.0 - (mag_ratio - 1.0) / 2.0, 0.0, 1.0))

            # 真实人脸: 余弦相似度 > 0.90, 幅值比 ≈ 1.0
            # AI换脸: 余弦相似度 < 0.65, 幅值比偏离 1.0
            if median_cos > 0.90:
                cos_score = 1.0
            elif median_cos > 0.75:
                cos_score = float(0.5 + (median_cos - 0.75) / 0.30)
            elif median_cos > 0.60:
                cos_score = float(0.2 + (median_cos - 0.60) / 0.75)
            else:
                cos_score = 0.0

            score = 0.6 * cos_score + 0.4 * mag_score
            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            return 0.5

    # ---- 子特征 2: 帧差分图时空结构分析（增强版） ----

    def _diff_structure_analysis(
        self, gray: np.ndarray, face_crop: np.ndarray,
        full_frame: Optional[np.ndarray], crop_x: int, crop_y: int,
    ) -> float:
        """帧差分图时空结构：人脸vs背景噪声差异 + 空间自相关 + GOP周期性。

        Returns:
            score ∈ [0, 1]
        """
        try:
            if self._prev_gray is None:
                return 0.5

            if self._prev_gray.shape != gray.shape:
                prev = cv2.resize(self._prev_gray, (gray.shape[1], gray.shape[0]))
            else:
                prev = self._prev_gray

            diff = np.abs(gray.astype(np.float32) - prev.astype(np.float32))
            diff_mean = float(np.mean(diff))
            self._diff_means.append(diff_mean)
            self._diff_mean_history.append(diff_mean)

            # ---- 维度A: 空间自相关 (0.30) ----
            h_face, w_face = diff.shape
            bh, bw = max(1, h_face // 4), max(1, w_face // 4)
            autocorr_total = 0.0
            count = 0
            for y in range(0, h_face - bh, bh):
                for x in range(0, w_face - bw, bw):
                    block = diff[y:y + bh, x:x + bw]
                    if block.size < 4:
                        continue
                    shifted = np.roll(block, shift=1, axis=0)
                    corr = float(np.corrcoef(block.ravel()[:100], shifted.ravel()[:100])[0, 1])
                    if not np.isnan(corr):
                        autocorr_total += corr
                        count += 1
            avg_autocorr = autocorr_total / max(count, 1)

            # ---- 维度B: 人臉vs背景噪声差异 (0.35) ----
            face_bg_score = 0.5
            if full_frame is not None:
                fh, fw = full_frame.shape[:2]
                x1, y1 = max(0, crop_x), max(0, crop_y)
                x2, y2 = min(fw, crop_x + gray.shape[1]), min(fh, crop_y + gray.shape[0])
                full_gray = cv2.cvtColor(full_frame, cv2.COLOR_BGR2GRAY)

                # 背景区域 diff（全帧差分的非人脸部分）
                if self._prev_full_gray is not None:
                    prev_full = self._prev_full_gray
                    if prev_full.shape == full_gray.shape:
                        full_diff = np.abs(full_gray.astype(np.float32) - prev_full.astype(np.float32))
                        # 人脸区域 mask
                        face_mask = np.zeros((fh, fw), dtype=bool)
                        face_mask[y1:y2, x1:x2] = True
                        # 人脸区域 diff 均值
                        face_diff_mean = float(np.mean(full_diff[face_mask])) if face_mask.sum() > 0 else diff_mean
                        # 背景区域 diff 均值
                        bg_mask = ~face_mask
                        bg_diff_mean = float(np.mean(full_diff[bg_mask])) if bg_mask.sum() > 0 else diff_mean
                        # 噪声差异比
                        noise_ratio = face_diff_mean / (bg_diff_mean + 1e-10)
                        if noise_ratio < 1.0:
                            noise_ratio = 1.0 / max(noise_ratio, 1e-10)
                        # 比值为 1.0→正常（整体运动）, >2.0→AI换脸（人脸区域噪声异常）
                        face_bg_score = float(np.clip(1.0 - (noise_ratio - 1.0) / 2.0, 0.0, 1.0))

            # ---- 维度C: diff图熵值 (0.20) ----
            diff_norm = diff / (diff.max() + 1e-10)
            entropy = 0.0
            vals = diff_norm.ravel()
            hist, _ = np.histogram(vals, bins=32, range=(0, 1), density=True)
            for p in hist:
                if p > 0:
                    entropy -= p * math.log(p)
            entropy_norm = entropy / math.log(32)

            # ---- 维度D: GOP周期性检测 (0.15) ----
            gop_score = self._detect_gop_periodicity()

            # 高自相关 + 低熵 + 噪声差异大 → 结构化/异常 → 低分
            struct_score = float(1.0 - avg_autocorr * 0.6)
            ent_score = float(entropy_norm)

            score = (
                0.30 * struct_score
                + 0.35 * face_bg_score
                + 0.20 * ent_score
                + 0.15 * gop_score
            )
            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            return 0.5

    def _detect_gop_periodicity(self) -> float:
        """检测 diff 均值时序的 GOP 周期性（屏幕回放特征）。

        GOP (Group of Pictures) 长度通常为 12/15/30 帧。
        对 diff_mean 序列做自相关，检测 lag 在 GOP 长度处是否出现峰值。

        Returns:
            score ∈ [0, 1], <0.5 表示检测到 GOP 周期性
        """
        try:
            if len(self._diff_mean_history) < 32:
                return 0.5
            diffs = np.array(list(self._diff_mean_history)[-64:], dtype=np.float64)
            if np.std(diffs) < 0.1:
                return 1.0  # 变化太小，无结构

            # 自相关
            mean = np.mean(diffs)
            var = np.var(diffs)
            if var < 1e-10:
                return 1.0
            diffs_centered = diffs - mean
            autocorr = np.correlate(diffs_centered, diffs_centered, mode='full')
            autocorr = autocorr[len(autocorr) // 2:] / (var * len(diffs))

            # 检查常见 GOP 长度 (10~30) 处是否有显著峰值
            max_peak = 0.0
            for lag in range(10, min(31, len(autocorr))):
                peak = float(autocorr[lag])
                if peak > max_peak:
                    max_peak = peak

            # 峰值 > 0.3 → 存在周期性 → 屏幕回放嫌疑
            if max_peak < 0.15:
                return 1.0
            elif max_peak < 0.30:
                return float(1.0 - (max_peak - 0.15) / 0.15)
            else:
                return 0.0
        except Exception:
            return 0.5

    # ---- 子特征 3: 多尺度纹理相干性 ----

    @staticmethod
    def _chi2_distance(h1: np.ndarray, h2: np.ndarray) -> float:
        eps = 1e-10
        return float(0.5 * np.sum((h1 - h2) ** 2 / (h1 + h2 + eps)))

    def _multi_scale_texture_coherence(self, gray: np.ndarray) -> float:
        """高斯金字塔 3 层，各层 LBP 卡方距离变化率相关系数。"""
        try:
            pyr = [gray]
            for _ in range(2):
                next_level = cv2.pyrDown(pyr[-1])
                if next_level is None or min(next_level.shape) < 16:
                    break
                pyr.append(next_level)

            if len(pyr) < 3 or len(self._face_crop_history) < 5:
                return 0.5

            # 各层 LBP 直方图
            lbp_hists = []
            for level_img in pyr:
                lbp = self._compute_lbp_uniform(level_img)
                hist, _ = np.histogram(lbp.ravel(), bins=59, range=(0, 59), density=True)
                lbp_hists.append(hist)

            # 与上一帧各层比较
            if not hasattr(self, '_prev_pyr_lbp_hists') or self._prev_pyr_lbp_hists is None:
                self._prev_pyr_lbp_hists = lbp_hists
                return 0.5

            chi2_rates = []
            for h_curr, h_prev in zip(lbp_hists, self._prev_pyr_lbp_hists):
                d = self._chi2_distance(h_curr, h_prev)
                chi2_rates.append(d)

            self._prev_pyr_lbp_hists = lbp_hists

            if len(chi2_rates) < 3:
                return 0.5

            # 计算三层变化率的相关系数
            rates = np.array(chi2_rates, dtype=np.float64)
            corr = float(np.corrcoef(rates, np.arange(len(rates)))[0, 1])
            if np.isnan(corr):
                corr = 0.0

            # 三层纹理变化高度相关（真人）→ ρ 接近 1 → 高分
            # abs(corr) 大说明各尺度变化有趋势一致
            score = float(np.clip(abs(corr), 0.0, 1.0))
            return score
        except Exception:
            return 0.5

    # ---- 子特征 4: 像素时序频谱一致性 ----

    def _pixel_spectral_consistency(self, gray: np.ndarray) -> float:
        """10×10 采样点 × 64 帧亮度序列 FFT 主频标准差。"""
        try:
            h, w = gray.shape
            step_y = max(1, h // 10)
            step_x = max(1, w // 10)
            samples = []
            for y in range(0, min(h, step_y * 10), step_y):
                for x in range(0, min(w, step_x * 10), step_x):
                    if y < h and x < w:
                        samples.append(float(gray[y, x]))

            # 保证 100 个点
            if len(samples) < 10:
                return 0.5
            samples_arr = np.array(samples[:100], dtype=np.float32)
            self._pixel_sequences.append(samples_arr)

            if len(self._pixel_sequences) < 16:
                return 0.5

            # 转置为 (N_pixels, N_frames)
            seq_matrix = np.array(list(self._pixel_sequences), dtype=np.float32).T  # (N_pix, N_frames)

            dominant_freqs = []
            for i in range(seq_matrix.shape[0]):
                seq = seq_matrix[i]
                if np.std(seq) < 0.5:
                    dominant_freqs.append(0.0)
                    continue
                fft_vals = np.abs(np.fft.rfft(seq))
                freqs = np.fft.rfftfreq(len(seq))
                # 排除 DC 分量
                if len(fft_vals) > 1:
                    peak_idx = np.argmax(fft_vals[1:]) + 1
                    dominant_freqs.append(freqs[peak_idx])
                else:
                    dominant_freqs.append(0.0)

            if len(dominant_freqs) < 5:
                return 0.5

            freq_std = float(np.std(dominant_freqs))
            # 主频标准差小 → 真人（所有像素同步）；标准差大 → AI换脸/屏幕
            thresh = 0.05
            if freq_std < thresh:
                return 1.0
            elif freq_std < thresh * 3:
                return float(1.0 - (freq_std - thresh) / (2 * thresh))
            else:
                return 0.0
        except Exception:
            return 0.5

    # ---- 子特征 5: 屏幕物理特征综合检测 ----

    def _screen_physical_features(
        self, gray: np.ndarray, face_crop: np.ndarray,
    ) -> float:
        """屏幕物理特征综合检测：扫描线 + 子像素色散 + 刷新率混叠。

        任一检测触发 → 得分 < 0.3；全部未触发 → 得分 1.0。

        Returns:
            score ∈ [0, 1]
        """
        try:
            # 子检测A: 扫描线检测
            scan_score = self._detect_scanlines(gray)

            # 子检测B: 子像素色散（RGB三通道帧间高频变化）
            dispersion_score = self._detect_subpixel_dispersion(face_crop)

            # 子检测C: 刷新率混叠频率
            aliasing_score = self._detect_refresh_aliasing(gray)

            # 取最差分（攻击只需一个特征触发）
            score = min(scan_score, dispersion_score, aliasing_score)
            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            return 0.5

    def _detect_scanlines(self, gray: np.ndarray) -> float:
        """相邻行亮度梯度的 FFT 检测扫描线。"""
        try:
            h, w = gray.shape
            if h < 4:
                return 1.0

            row_means = np.mean(gray.astype(np.float32), axis=1)
            row_diff = np.abs(np.diff(row_means))

            if len(row_diff) < 4:
                return 1.0

            fft_vals = np.abs(np.fft.rfft(row_diff))
            if len(fft_vals) < 3:
                return 1.0

            ac_vals = fft_vals[1:]
            if ac_vals.max() < 1e-10:
                return 1.0

            peak_to_mean = float(ac_vals.max() / (ac_vals.mean() + 1e-10))

            if peak_to_mean < 2.0:
                return 1.0
            elif peak_to_mean < 4.0:
                return float(1.0 - (peak_to_mean - 2.0) / 4.0)
            else:
                return 0.0
        except Exception:
            return 1.0

    def _detect_subpixel_dispersion(self, face_crop: np.ndarray) -> float:
        """子像素色散：RGB三通道帧间高频变化。

        LCD的R/G/B子像素物理位置不同，微动时产生色边。
        检测相邻帧各通道边缘密度的不一致性。
        """
        try:
            if self._prev_face_crop is None:
                return 1.0

            prev = self._prev_face_crop
            curr = face_crop

            if prev.shape != curr.shape:
                prev = cv2.resize(prev, (curr.shape[1], curr.shape[0]))

            # 各通道 Sobel 边缘密度
            edge_densities = []
            for ch in range(3):
                prev_edge = cv2.Sobel(prev[:, :, ch], cv2.CV_64F, 1, 1, ksize=3)
                curr_edge = cv2.Sobel(curr[:, :, ch], cv2.CV_64F, 1, 1, ksize=3)
                # 帧间边缘变化量
                edge_diff = np.abs(curr_edge - prev_edge)
                edge_density = float(np.mean(edge_diff))
                edge_densities.append(edge_density)

            # 三通道边缘密度标准差：大 → 各通道变化不均 → 子像素色散
            edge_std = float(np.std(edge_densities))
            edge_mean = float(np.mean(edge_densities)) + 1e-10
            cv = edge_std / edge_mean

            # 变异系数 < 0.2 → 正常；> 0.5 → 色散嫌疑
            if cv < 0.2:
                return 1.0
            elif cv < 0.5:
                return float(1.0 - (cv - 0.2) / 0.3)
            else:
                return 0.0
        except Exception:
            return 1.0

    def _detect_refresh_aliasing(self, gray: np.ndarray) -> float:
        """刷新率混叠频率检测。

        屏幕刷新率(60Hz)与摄像头采样率的差频会在时序FFT中产生混叠峰值。
        对64帧亮度序列做FFT，检测异常频率分量。
        """
        try:
            if len(self._pixel_sequences) < 32:
                return 1.0

            # 取所有像素点的平均亮度序列
            seq_matrix = np.array(list(self._pixel_sequences), dtype=np.float32).T
            avg_seq = np.mean(seq_matrix, axis=0)  # (N_frames,)

            if np.std(avg_seq) < 0.5:
                return 1.0

            fft_vals = np.abs(np.fft.rfft(avg_seq))
            freqs = np.fft.rfftfreq(len(avg_seq))

            # 排除 DC，在非零频率中检测异常高能量分量
            if len(fft_vals) < 3:
                return 1.0

            ac_vals = fft_vals[1:]
            ac_freqs = freqs[1:]
            mean_ac = float(np.mean(ac_vals))
            std_ac = float(np.std(ac_vals))

            if mean_ac < 1e-10:
                return 1.0

            # 检测 > mean + 2*std 的异常峰值
            outlier_mask = ac_vals > mean_ac + 2.0 * std_ac
            outlier_count = int(np.sum(outlier_mask))

            # 总能量中异常峰值的占比
            total_energy = float(np.sum(ac_vals))
            outlier_energy = float(np.sum(ac_vals[outlier_mask]))
            energy_ratio = outlier_energy / (total_energy + 1e-10)

            if energy_ratio < 0.15:
                return 1.0
            elif energy_ratio < 0.30:
                return float(1.0 - (energy_ratio - 0.15) / 0.15)
            else:
                return 0.0
        except Exception:
            return 1.0

    # ==================================================================
    # Layer 3: 3D 活体检测
    # ==================================================================

    def _layer3_liveness(
        self, face_crop: np.ndarray, landmarks, crop_x: int, crop_y: int
    ) -> float:
        """三维活体检测：EAR + head pose + optical flow 3D。

        Returns:
            liveness_score ∈ [0, 1]
        """
        if landmarks is None:
            return 0.5

        try:
            s1 = self._ear_blink_score(landmarks)        # 0.30
            s2 = self._head_pose_score(face_crop, landmarks)  # 0.35
            s3 = self._optical_flow_3d_score(face_crop, landmarks)  # 0.35

            # 更新眨眼追踪
            if s1 > 0.8:
                self._blink_ever_detected = True
                self._frames_no_blink = 0
            else:
                self._frames_no_blink += 1

            score = 0.30 * s1 + 0.35 * s2 + 0.35 * s3
            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            return 0.5

    # ---- 子特征 1: EAR 眨眼检测 ----

    def _ear_blink_score(self, landmarks) -> float:
        """EAR 眨眼检测：上升沿检测 + 持久化追踪。"""
        try:
            left_indices = list(range(36, 42))
            right_indices = list(range(42, 48))

            left_pts = [(landmarks.part(i).x, landmarks.part(i).y) for i in left_indices]
            right_pts = [(landmarks.part(i).x, landmarks.part(i).y) for i in right_indices]

            left_ear = self._compute_ear(left_pts)
            right_ear = self._compute_ear(right_pts)
            avg_ear = (left_ear + right_ear) / 2.0
            self._ear_history.append(avg_ear)

            if len(self._ear_history) < 5:
                return 0.5

            # 上升沿检测
            ear_list = list(self._ear_history)
            blinked_this_frame = False
            for i in range(2, len(ear_list)):
                below = ear_list[i - 2] < self.ear_blink_thresh
                above = ear_list[i] > self.ear_blink_thresh + 0.05
                if below and above:
                    blinked_this_frame = True
                    break

            if blinked_this_frame:
                return 1.0

            if self._blink_ever_detected:
                return 1.0

            # 还没检测到眨眼 → 根据 EAR 值给分
            if avg_ear > 0.30:
                return 0.6  # 睁眼，可能还没眨眼
            else:
                return 0.3  # EAR 偏低，可疑
        except Exception:
            return 0.5

    @staticmethod
    def _compute_ear(eye_points: list) -> float:
        """计算单眼 EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)。"""
        pts = [np.array(p, dtype=np.float64) for p in eye_points]
        a = float(np.linalg.norm(pts[1] - pts[5]))
        b = float(np.linalg.norm(pts[2] - pts[4]))
        c = float(np.linalg.norm(pts[0] - pts[3]))
        if c < 1e-6:
            return 0.0
        return (a + b) / (2.0 * c)

    # ---- 子特征 2: 头部姿态 3D 微动（solvePnP） ----

    # 3D 参考点（归一化坐标系）
    _REF_3D = np.array([
        [0.0, 0.0, 0.0],    # 30: 鼻尖
        [0.0, -3.0, 0.0],   # 8:  下巴
        [-1.0, 1.0, -2.0],  # 36: 左眼角
        [1.0, 1.0, -2.0],   # 45: 右眼角
        [-1.0, -2.0, -1.0], # 48: 左嘴角
        [1.0, -2.0, -1.0],  # 54: 右嘴角
    ], dtype=np.float64)

    _POSE_INDICES = [30, 8, 36, 45, 48, 54]

    def _head_pose_score(self, face_crop: np.ndarray, landmarks) -> float:
        """solvePnP 头部姿态估计，30 帧方差评分。"""
        try:
            h, w = face_crop.shape[:2]
            image_pts = np.array([
                [landmarks.part(i).x, landmarks.part(i).y]
                for i in self._POSE_INDICES
            ], dtype=np.float64)

            # 从原始 landmarks 坐标转为 face_crop 坐标需要减去 crop_x, crop_y，
            # 但 landmarks 是原图坐标，face_crop 是裁剪区域，需要转换
            # 此处 landmarks.part(i).x/y 是原图坐标，但调用方传入 crop_x/crop_y
            # 我们需要手动转换
            # 实际上 face_crop 是由 dlib rect 裁剪的，landmarks 坐标是原图坐标
            # 转换到 face_crop 坐标
            image_pts[:, 0] -= 0  # landmarks 坐标相对于 crop 的偏移由调用方负责

            camera_matrix = np.array([
                [500.0, 0.0, w / 2.0],
                [0.0, 500.0, h / 2.0],
                [0.0, 0.0, 1.0],
            ], dtype=np.float64)

            dist_coeffs = np.zeros((4, 1), dtype=np.float64)

            success, rvec, tvec = cv2.solvePnP(
                self._REF_3D, image_pts, camera_matrix, dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )

            if not success:
                return 0.5

            rmat, _ = cv2.Rodrigues(rvec)
            # 提取 pitch / yaw / roll
            sy = math.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
            singular = sy < 1e-6
            if not singular:
                pitch = math.atan2(-rmat[2, 0], sy)
                yaw = math.atan2(rmat[1, 0], rmat[0, 0])
                roll = math.atan2(rmat[2, 1], rmat[2, 2])
            else:
                pitch = math.atan2(-rmat[2, 0], sy)
                yaw = math.atan2(-rmat[1, 2], rmat[1, 1])
                roll = 0.0

            self._pose_deque.append((pitch, yaw, roll))

            if len(self._pose_deque) < 5:
                return 0.5

            poses = np.array(list(self._pose_deque))
            var_pitch = float(np.var(poses[:, 0]))
            var_yaw = float(np.var(poses[:, 1]))
            var_roll = float(np.var(poses[:, 2]))
            avg_var = (var_pitch + var_yaw + var_roll) / 3.0

            # 方差 < 0.3°(约 0.0052 rad²) → 完全静止（照片）→ 0.0
            # 方差 > 1.5°(约 0.00068 rad²) → 自然微动 → 1.0
            # 注意: var 是弧度²，0.3° = 0.0052 rad, var = (0.0052)² ≈ 2.7e-5
            # 1.5° = 0.026 rad, var = (0.026)² ≈ 6.8e-4
            lo = 2.0e-5   # ~0.26°  std
            hi = 5.0e-4   # ~1.3°  std
            if avg_var < lo:
                score = 0.0
            elif avg_var > hi:
                score = 1.0
            else:
                score = float((avg_var - lo) / (hi - lo))

            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            return 0.5

    # ---- 子特征 3: 面部光流 3D 运动模式 ----

    _EYE_LEFT_IDX = list(range(36, 42))
    _EYE_RIGHT_IDX = list(range(42, 48))
    _NOSE_IDX = list(range(27, 36))
    _MOUTH_IDX = list(range(48, 68))

    def _optical_flow_3d_score(self, face_crop: np.ndarray, landmarks) -> float:
        """5 区域 Farneback 光流方向标准差 → 3D 旋转 vs 2D 平移。"""
        try:
            if self._prev_face_crop is None:
                return 0.5

            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            prev_gray = cv2.cvtColor(self._prev_face_crop, cv2.COLOR_BGR2GRAY)

            if prev_gray.shape != gray.shape:
                prev_gray = cv2.resize(prev_gray, (gray.shape[1], gray.shape[0]))

            # Farneback 光流
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
            )

            h, w = gray.shape

            # 提取 5 区域（基于 landmarks 边界框）
            regions = []
            for idx_set in [self._EYE_LEFT_IDX, self._EYE_RIGHT_IDX,
                             self._NOSE_IDX, self._MOUTH_IDX]:
                pts = np.array([
                    [landmarks.part(i).x, landmarks.part(i).y] for i in idx_set
                ], dtype=np.int32)
                x_min, y_min = pts.min(axis=0)
                x_max, y_max = pts.max(axis=0)
                # 裁剪到图像范围内
                x_min = max(0, int(x_min))
                y_min = max(0, int(y_min))
                x_max = min(w, int(x_max))
                y_max = min(h, int(y_max))
                if x_max > x_min and y_max > y_min:
                    region_flow = flow[y_min:y_max, x_min:x_max]
                    regions.append(region_flow)

            # 第 5 区域: 脸颊（中间偏下）
            mid_y = h // 2
            cheek_region = flow[mid_y:, :]
            regions.append(cheek_region)

            # 各区域平均光流方向
            directions = []
            for region in regions:
                if region.size < 4:
                    continue
                fx = float(np.mean(region[..., 0]))
                fy = float(np.mean(region[..., 1]))
                if abs(fx) > 0.01 or abs(fy) > 0.01:
                    angle = math.degrees(math.atan2(fy, fx))
                    directions.append(angle)

            if len(directions) < 3:
                return 0.5

            # 方向标准差
            # 处理角度环绕问题（circular std）
            dir_rad = np.radians(directions)
            mean_sin = float(np.mean(np.sin(dir_rad)))
            mean_cos = float(np.mean(np.cos(dir_rad)))
            R = math.sqrt(mean_sin ** 2 + mean_cos ** 2)
            circular_std = math.degrees(math.sqrt(-2.0 * math.log(max(R, 1e-10))))

            # 标准差 > 15° → 3D 旋转 → 1.0；< 5° → 2D 平移 → 0.0
            if circular_std > 15.0:
                return 1.0
            elif circular_std < 5.0:
                return 0.0
            else:
                return float((circular_std - 5.0) / 10.0)
        except Exception:
            return 0.5

    # ==================================================================
    # Layer 4: 物理媒体伪影检测
    # ==================================================================

    def _layer4_media(self, face_crop: np.ndarray) -> float:
        """八维物理媒体伪影检测（含屏幕专用检测器）。

        权重设计：
        - 传统图像统计特征（FFT/功率谱/LBP/RGB/反射）：共 45%
        - 物理传感器/显示特征（噪声/微纹理/压缩块）：共 55%

        Returns:
            media_score ∈ [0, 1]
        """
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        except Exception:
            return 0.5

        try:
            # ---- 传统图像统计特征 (45%) ----
            s1 = self._fft_moire_peaks(gray)                  # 15%
            s2 = self._radial_power_spectrum_score(gray)      # 10%
            s3 = self._lbp_entropy_score(gray)                # 10%
            s4 = self._rgb_correlation_score(face_crop)       # 5%
            s5 = self._specular_reflection_score(face_crop)   # 5%

            # ---- 物理传感器/显示特征 (55%) ----
            s6 = self._noise_residual_score(face_crop)        # 25%  噪声残差（传感器 vs 显示）
            s7 = self._local_micro_variance_score(face_crop)  # 20%  微观纹理平坦度
            s8 = self._dct_blocking_score(face_crop)          # 10%  视频压缩块效应

            score = (
                0.15 * s1 + 0.10 * s2 + 0.10 * s3
                + 0.05 * s4 + 0.05 * s5
                + 0.25 * s6 + 0.20 * s7 + 0.10 * s8
            )
            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            return 0.5

    # ---- 子特征 1: FFT 摩尔纹峰值检测 ----

    @staticmethod
    def _fft_moire_peaks(gray: np.ndarray) -> float:
        """2D FFT 中高频区域 5×5 局部最大 + mean+3σ 峰值密度评分。"""
        try:
            f = np.fft.fft2(gray.astype(np.float32))
            fshift = np.fft.fftshift(f)
            magnitude = np.abs(fshift)
            h, w = magnitude.shape
            cy, cx = h // 2, w // 2
            y, x = np.ogrid[:h, :w]
            dist = np.sqrt((y - cy) ** 2 + (x - cx) ** 2)
            max_dist = float(min(cy, cx))

            # 中高频区域 r > 0.3 * max_dist
            mid_high_mask = dist > 0.3 * max_dist
            if mid_high_mask.sum() < 25:
                return 1.0

            roi_vals = magnitude[mid_high_mask]
            local_mean = float(np.mean(roi_vals))
            local_std = float(np.std(roi_vals))

            # 5×5 局部极大值
            kernel = np.ones((5, 5), dtype=np.uint8)
            dilated = cv2.dilate(magnitude, kernel)
            is_peak = (magnitude == dilated) & mid_high_mask

            threshold = local_mean + 3.0 * local_std
            significant = is_peak & (magnitude > threshold)

            peak_count = int(np.sum(significant))
            total = int(mid_high_mask.sum())

            if peak_count == 0 or total == 0:
                return 1.0

            density = peak_count / total

            if density <= 0.005:
                return 1.0
            elif density <= 0.02:
                return float(1.0 - (density - 0.005) / 0.015)
            else:
                return max(0.0, 0.3 - (density - 0.02) * 10.0)
        except Exception:
            return 0.5

    # ---- 子特征 2: 傅里叶径向功率谱分析 ----

    @staticmethod
    def _radial_power_spectrum_score(gray: np.ndarray) -> float:
        """log-log 空间拟合 P(r) ∝ r^(-α)，检查 α 偏离度和 R²。"""
        try:
            f = np.fft.fft2(gray.astype(np.float32))
            fshift = np.fft.fftshift(f)
            magnitude = np.abs(fshift)
            h, w = magnitude.shape
            cy, cx = h // 2, w // 2
            y, x = np.ogrid[:h, :w]
            dist = np.sqrt((y - cy) ** 2 + (x - cx) ** 2)
            max_r = int(min(cy, cx))

            r_vals = np.arange(2, max_r, dtype=np.float64)
            if len(r_vals) < 10:
                return 0.5

            P_vals = np.zeros_like(r_vals)
            for i, r in enumerate(r_vals):
                mask = (dist >= r - 0.5) & (dist < r + 0.5)
                if mask.sum() > 0:
                    P_vals[i] = np.mean(magnitude[mask])

            eps = 1e-10
            valid = P_vals > eps
            if valid.sum() < 5:
                return 0.5

            log_r = np.log(r_vals[valid])
            log_P = np.log(P_vals[valid])

            coeffs = np.polyfit(log_r, log_P, 1)
            slope = coeffs[0]
            alpha = float(abs(slope))
            log_P_pred = slope * log_r + coeffs[1]

            ss_res = np.sum((log_P - log_P_pred) ** 2)
            ss_tot = np.sum((log_P - np.mean(log_P)) ** 2)
            r_sq = max(0.0, min(1.0, float(1.0 - ss_res / (ss_tot + eps))))

            # α 在 [1.5, 2.5] 内且 R² > 0.7 → 高分
            if 1.5 <= alpha <= 2.5:
                dev_score = 1.0
            elif 1.0 <= alpha <= 3.0:
                dev_score = float(1.0 - abs(alpha - 2.0) / 1.5)
            else:
                dev_score = 0.0

            if r_sq < 0.7:
                dev_score *= max(0.3, r_sq / 0.7)

            return float(np.clip(dev_score, 0.0, 1.0))
        except Exception:
            return 0.5

    # ---- 子特征 3: LBP 纹理熵值 ----

    @staticmethod
    def _lbp_entropy_score(gray: np.ndarray) -> float:
        """Uniform LBP (P=8, R=1) 直方图 Shannon 熵，高斯型评分（中心 4.2, sigma=1.5）。"""
        try:
            lbp = LivenessDetector._compute_lbp_uniform(gray)
            hist, _ = np.histogram(lbp.ravel(), bins=256, range=(0, 256))
            hist = hist.astype(np.float64)
            total = hist.sum()
            if total == 0:
                return 0.0
            probs = hist / total
            entropy = 0.0
            for p in probs:
                if p > 0:
                    entropy -= p * math.log(p)

            opt_entropy = 4.2
            sigma = 1.5
            score = math.exp(-((entropy - opt_entropy) ** 2) / (2.0 * sigma * sigma))
            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            return 0.5

    # ---- 子特征 4: RGB 通道相关性 ----

    @staticmethod
    def _rgb_correlation_score(face_crop: np.ndarray) -> float:
        """RGB 三通道 Pearson 相关系数均值评分。"""
        try:
            b, g, r = cv2.split(face_crop)
            rb_flat, g_flat, bb_flat = r.ravel(), g.ravel(), b.ravel()

            step = max(1, len(rb_flat) // 2000)
            rb, gb, bb = rb_flat[::step], g_flat[::step], bb_flat[::step]

            rg = float(np.corrcoef(rb, gb)[0, 1]) if len(rb) > 1 else 0.0
            rb_c = float(np.corrcoef(rb, bb)[0, 1]) if len(rb) > 1 else 0.0
            gb_c = float(np.corrcoef(gb, bb)[0, 1]) if len(gb) > 1 else 0.0

            avg_corr = (rg + rb_c + gb_c) / 3.0

            # 真传感器: 0.85~0.92；打印: >0.95；屏幕: 0.70~0.85
            if 0.82 <= avg_corr <= 0.93:
                return 1.0
            elif avg_corr > 0.95:
                return 0.0
            elif avg_corr < 0.70:
                return 0.1
            elif avg_corr < 0.82:
                return float((avg_corr - 0.70) / 0.12 * 0.8 + 0.1)
            else:
                return float(max(0.0, 1.0 - (avg_corr - 0.93) / 0.02))
        except Exception:
            return 0.5

    # ---- 子特征 5: 高光反射检测 ----

    @staticmethod
    def _specular_reflection_score(face_crop: np.ndarray) -> float:
        """HSV 中 V>200 且 S<50 的像素占比 > 3% → 镜面反射（屏幕/光面照片纸）。"""
        try:
            hsv = cv2.cvtColor(face_crop, cv2.COLOR_BGR2HSV)
            v = hsv[:, :, 2]
            s = hsv[:, :, 1]
            specular_mask = (v > 200) & (s < 50)
            ratio = float(np.sum(specular_mask)) / specular_mask.size

            if ratio < 0.01:
                return 1.0
            elif ratio < 0.03:
                return float(1.0 - (ratio - 0.01) / 0.02)
            else:
                return 0.0
        except Exception:
            return 0.5

    # ---- 子特征 6: 噪声残差分析（屏幕 vs 真实传感器） ----

    @staticmethod
    def _noise_residual_score(face_crop: np.ndarray) -> float:
        """噪声残差分析：真实摄像头传感器噪声 vs 屏幕显示噪声。

        核心原理：
        - 真实人脸：摄像头 CMOS 传感器存在光子散粒噪声 + 读出噪声，
          噪声残差方差较大、空间自相关性低。
        - 手机屏幕：显示屏几乎无噪声，噪声残差极小；且屏幕自身的
          subpixel 排列给噪声残差带来结构化的空间相关性。

        方法：
        1. 中值滤波去噪，提取噪声残差
        2. 残差方差 → 越低越像屏幕
        3. 残差空间自相关 → 越高越像屏幕（屏幕像素网格造成规律性）

        Returns:
            score ∈ [0, 1], <0.5 表示屏幕嫌疑
        """
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY).astype(np.float32)

            # 中值滤波去噪
            denoised = cv2.medianBlur(face_crop, 5)
            denoised_gray = cv2.cvtColor(denoised, cv2.COLOR_BGR2GRAY).astype(np.float32)

            # 噪声残差
            residual = gray - denoised_gray

            # 1) 残差方差
            noise_var = float(np.var(residual))
            # 真人噪声方差 > 3.0 / 屏幕 < 1.0
            if noise_var > 3.5:
                var_score = 1.0
            elif noise_var > 1.5:
                var_score = float((noise_var - 1.5) / 2.0)
            elif noise_var > 0.5:
                var_score = float((noise_var - 0.5) / 1.0 * 0.4)
            else:
                var_score = 0.0

            # 2) 残差空间自相关（检测屏幕 subpixel 网格规律性）
            h, w = residual.shape
            if h > 4 and w > 4:
                # 水平和垂直方向的 1-pixel shift 自相关
                hor_corr = float(np.corrcoef(
                    residual[:, :-1].ravel()[:2000],
                    residual[:, 1:].ravel()[:2000],
                )[0, 1])
                ver_corr = float(np.corrcoef(
                    residual[:-1, :].ravel()[:2000],
                    residual[1:, :].ravel()[:2000],
                )[0, 1])
                avg_ac = (abs(hor_corr) + abs(ver_corr)) / 2.0
                # 真人噪声随机 → 自相关 < 0.15 / 屏幕规律噪声 → > 0.3
                if avg_ac < 0.12:
                    ac_score = 1.0
                elif avg_ac < 0.25:
                    ac_score = float(1.0 - (avg_ac - 0.12) / 0.13)
                else:
                    ac_score = 0.0
            else:
                ac_score = 0.5

            score = 0.5 * var_score + 0.5 * ac_score
            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            return 0.5

    # ---- 子特征 7: 微观局部方差（屏幕像素平坦度） ----

    @staticmethod
    def _local_micro_variance_score(face_crop: np.ndarray) -> float:
        """微观局部方差分析：检测屏幕像素级别平坦度。

        核心原理：
        - 真实人脸：皮肤有毛孔、细纹、汗毛等微观纹理，3×3 局部方差
          分布广泛且有大量高方差区域。
        - 手机屏幕：受限于像素分辨率，微尺度下纹理被平滑化，
          局部方差分布集中且偏低。

        方法：
        1. 计算 3×3 窗口的局部标准差
        2. 分析标准差的分布：均值、峰度、90 分位数
        3. 屏幕回放：均值低 + 分布窄

        Returns:
            score ∈ [0, 1], <0.5 表示屏幕嫌疑
        """
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY).astype(np.float32)

            # 3×3 局部方差（使用均值滤波的平方差技巧加速）
            mean_3x3 = cv2.blur(gray, (3, 3))
            sq_mean_3x3 = cv2.blur(gray ** 2, (3, 3))
            local_var = sq_mean_3x3 - mean_3x3 ** 2
            local_var = np.maximum(local_var, 0)  # 数值精度修正
            local_std = np.sqrt(local_var)

            # 统计分布特征
            std_mean = float(np.mean(local_std))
            std_median = float(np.median(local_std))
            std_p90 = float(np.percentile(local_std, 90))

            # 峰度：测量分布的"厚尾"程度
            # 真人：高方差区域多（皮肤纹理边缘）→ 正偏态
            # 屏幕：分布集中 → 低峰度
            std_centered = local_std - std_mean
            m4 = float(np.mean(std_centered ** 4))
            m2 = float(np.mean(std_centered ** 2)) + 1e-10
            kurtosis = m4 / (m2 ** 2)

            # 评分1: 局部标准差均值。真人 > 6.0，屏幕 < 3.0
            if std_mean > 5.5:
                mean_score = 1.0
            elif std_mean > 3.0:
                mean_score = float((std_mean - 3.0) / 2.5)
            elif std_mean > 1.5:
                mean_score = float((std_mean - 1.5) / 1.5 * 0.3)
            else:
                mean_score = 0.0

            # 评分2: P90 分位数。真人 > 12，屏幕 < 6
            if std_p90 > 10.0:
                p90_score = 1.0
            elif std_p90 > 5.0:
                p90_score = float((std_p90 - 5.0) / 5.0)
            elif std_p90 > 2.5:
                p90_score = float((std_p90 - 2.5) / 2.5 * 0.3)
            else:
                p90_score = 0.0

            # 评分3: 峰度。真人 3~6（正态→厚尾），屏幕 2~4（均匀→正态）
            if kurtosis > 4.5:
                kurt_score = 1.0
            elif kurtosis > 3.0:
                kurt_score = float((kurtosis - 3.0) / 1.5)
            elif kurtosis > 2.0:
                kurt_score = float((kurtosis - 2.0) / 1.0 * 0.4)
            else:
                kurt_score = 0.0

            score = 0.35 * mean_score + 0.35 * p90_score + 0.30 * kurt_score
            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            return 0.5

    # ---- 子特征 8: DCT 块效应检测（视频压缩伪影） ----

    @staticmethod
    def _dct_blocking_score(face_crop: np.ndarray) -> float:
        """DCT 块效应检测：视频压缩的 8×8 块边界不连续性。

        核心原理：
        - 真实摄像头：像素连续，无块边界
        - 手机屏幕播放视频：H.264/H.265 压缩使用 DCT 变换块（4×4~16×16），
          块边界处存在微小灰度跳跃。即便高码率，I 帧仍有可检测的块结构。

        方法：
        1. 对灰度图计算水平和垂直方向的相邻像素差
        2. 在 8 的倍数位置检查差值是否系统性地更大
        3. 块边界位置的平均差值与整体平均差值的比值

        Returns:
            score ∈ [0, 1], <0.5 表示检测到块效应
        """
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
            h, w = gray.shape
            if h < 16 or w < 16:
                return 0.5

            # 水平相邻差
            h_diff = np.abs(np.diff(gray, axis=1))
            # 垂直相邻差
            v_diff = np.abs(np.diff(gray, axis=0))

            # 块大小（视频编码常用 8×8）
            block_size = 8

            # 收集块边界位置的差值和块内部位置的差值
            h_boundary_diffs = []
            h_interior_diffs = []
            for col in range(1, w):
                if col % block_size == 0:
                    h_boundary_diffs.append(float(np.mean(h_diff[:, col - 1])))
                else:
                    h_interior_diffs.append(float(np.mean(h_diff[:, col - 1])))

            v_boundary_diffs = []
            v_interior_diffs = []
            for row in range(1, h):
                if row % block_size == 0:
                    v_boundary_diffs.append(float(np.mean(v_diff[row - 1, :])))
                else:
                    v_interior_diffs.append(float(np.mean(v_diff[row - 1, :])))

            # 计算边界/内部差值比
            h_boundary_mean = np.mean(h_boundary_diffs) if h_boundary_diffs else 0
            h_interior_mean = np.mean(h_interior_diffs) if h_interior_diffs else 1e-10
            v_boundary_mean = np.mean(v_boundary_diffs) if v_boundary_diffs else 0
            v_interior_mean = np.mean(v_interior_diffs) if v_interior_diffs else 1e-10

            h_ratio = h_boundary_mean / (h_interior_mean + 1e-10)
            v_ratio = v_boundary_mean / (v_interior_mean + 1e-10)
            avg_ratio = (h_ratio + v_ratio) / 2.0

            # 块效应比值 > 1.15 → 有明显块边界
            # 真人：ratio ≈ 1.0（边界和内部差值无系统性差异）
            # 压缩视频：ratio > 1.1（8×8 块边界差值系统性地更高）
            if avg_ratio < 1.05:
                return 1.0
            elif avg_ratio < 1.12:
                return float(1.0 - (avg_ratio - 1.05) / 0.07)
            elif avg_ratio < 1.25:
                return float(max(0.0, 1.0 - (avg_ratio - 1.05) / 0.07))
            else:
                return 0.0
        except Exception:
            return 0.5

    # ==================================================================
    # 工具方法
    # ==================================================================

    @staticmethod
    def _compute_lbp_uniform(gray: np.ndarray) -> np.ndarray:
        """向量化 Uniform LBP (P=8, R=1)。"""
        h, w = gray.shape
        padded = np.pad(gray, pad_width=1, mode='edge')
        center = gray

        neighbors = [
            padded[0:h, 0:w],
            padded[0:h, 1:w + 1],
            padded[0:h, 2:w + 2],
            padded[1:h + 1, 2:w + 2],
            padded[2:h + 2, 2:w + 2],
            padded[2:h + 2, 1:w + 1],
            padded[2:h + 2, 0:w],
            padded[1:h + 1, 0:w],
        ]

        code = np.zeros((h, w), dtype=np.uint8)
        for bit_idx, nbr in enumerate(neighbors):
            code |= ((nbr >= center).astype(np.uint8) << bit_idx)

        return code

    def _spoof_result(
        self, score: float, reasons: list[str],
        deepfake: float, minifas: float, static_score: float,
        temporal: float, liveness: float, media: float, final_raw: float,
        fsd: float = 0.5,
    ) -> dict:
        return {
            "score": round(score, 3),
            "is_spoof": True,
            "reasons": reasons,
            "details": {
                "deepfake_score": round(deepfake, 3),
                "minifas_score": round(minifas, 3),
                "static_score": round(static_score, 3),
                "fsd_score": round(fsd, 3),
                "temporal_score": round(temporal, 3),
                "liveness_score": round(liveness, 3),
                "media_score": round(media, 3),
                "final_raw": round(final_raw, 3),
                "final_smoothed": round(score, 3),
                "frames_cached": len(self._face_crop_history),
            },
        }

    def _empty_details(self) -> dict:
        return {
            "deepfake_score": 0.5,
            "minifas_score": 0.5,
            "static_score": 0.5,
            "fsd_score": 0.5,
            "temporal_score": 0.5,
            "liveness_score": 0.5,
            "media_score": 0.5,
            "final_raw": 1.0,
            "final_smoothed": 1.0,
            "frames_cached": 0,
        }
