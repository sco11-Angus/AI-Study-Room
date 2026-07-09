"""活体检测 — 多信号融合 Anti-Spoofing（被动式）。

结合 3 种信号加权融合判定人脸真伪：
1. 眨眼检测（EAR 时序）               — 权重 0.4，防御静态照片
2. 微动分析（Farneback 光流幅值）      — 权重 0.35，防御静态照片/视频回放
3. 纹理分析（LBP 直方图熵值）          — 权重 0.25，防御翻拍/屏幕摩尔纹/AI 伪影

融合分数 < liveness_threshold → 判定为欺骗攻击。
"""
import logging
from collections import deque
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 权重常量
# ------------------------------------------------------------------
W_EAR = 0.4
W_MOTION = 0.35
W_TEXTURE = 0.25


class LivenessDetector:
    """多信号活体检测器。

    每个 FaceDetector 实例持有一个 LivenessDetector，维护该人脸的帧历史。
    """

    def __init__(
        self,
        liveness_threshold: float = 0.5,
        history_size: int = 30,
        ear_blink_thresh: float = 0.25,
        motion_threshold: float = 0.5,
        texture_threshold: float = 0.02,
        # ---- backward compat: face.py FaceDetector 构造参数 ----
        enabled: bool = True,
        threshold: Optional[float] = None,
    ):
        """初始化活体检测器。

        Args:
            liveness_threshold: 活体判定阈值，融合分 >= 该值判为真人
            history_size: EAR 历史 deque 容量（帧数）
            ear_blink_thresh: EAR 眨眼判定阈值（低于此值视为闭眼）
            motion_threshold: 光流幅值归一化阈值（像素/帧）
            texture_threshold: LBP 直方图方差归一化阈值
            enabled: 是否启用活体检测
            threshold: (兼容旧接口) 同 liveness_threshold
        """
        self.enabled = enabled
        self.threshold = threshold if threshold is not None else liveness_threshold
        self.history_size = history_size
        self.ear_blink_thresh = ear_blink_thresh
        self.motion_threshold = motion_threshold
        self.texture_threshold = texture_threshold

        # 帧历史
        self._ear_history: deque[float] = deque(maxlen=history_size)
        self._prev_face_crop: Optional[np.ndarray] = None
        self._face_crops: deque = deque(maxlen=history_size)

        # 眨眼状态机
        self._blink_detected: bool = False
        self._was_below_thresh: bool = False

    @property
    def _face_history(self):
        """兼容测试：返回人脸裁剪历史 deque。"""
        return self._face_crops

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        face_crop: np.ndarray,
        landmarks,
        prev_face_crop: Optional[np.ndarray] = None,
    ) -> tuple[bool, float, list[str]]:
        """执行活体检测，返回融合判定结果。

        Args:
            face_crop: BGR 人脸裁剪图像
            landmarks: dlib full_object_detection（68 点）
            prev_face_crop: 可选，覆盖内部缓存的上一帧人脸（用于测试）

        Returns:
            (is_live, score, reasons)
            - is_live: True 表示判定为真人
            - score: [0, 1] 融合活体分数，越高越像真人
            - reasons: 未通过信号名称列表，如 ["no_blink", "texture_anomaly"]
        """
        if not self.enabled:
            return True, 1.0, []

        # ---- 信号 1: 眨眼检测 ----
        blink_score = self._detect_blink(landmarks)

        # ---- 信号 2: 微动分析 ----
        # 支持外部传入上一帧裁剪
        if prev_face_crop is not None:
            old_prev = self._prev_face_crop
            self._prev_face_crop = prev_face_crop
            motion_score = self._analyze_motion(face_crop)
            self._prev_face_crop = old_prev
        else:
            motion_score = self._analyze_motion(face_crop)

        # ---- 信号 3: 纹理分析 ----
        texture_score = self._analyze_texture(face_crop)

        # ---- 融合 ----
        score = W_EAR * blink_score + W_MOTION * motion_score + W_TEXTURE * texture_score
        score = float(np.clip(score, 0.0, 1.0))

        reasons: list[str] = []
        if blink_score < W_EAR:
            reasons.append("no_blink")
        if motion_score < W_MOTION:
            reasons.append("low_motion")
        if texture_score < W_TEXTURE:
            reasons.append("texture_anomaly")

        is_live = score >= self.threshold

        logger.debug(
            "[liveness] is_live=%s score=%.3f ear=%.3f motion=%.3f texture=%.3f reasons=%s",
            is_live, score, blink_score, motion_score, texture_score, reasons,
        )

        return is_live, score, reasons

    def check(self, face_crop: np.ndarray, landmarks) -> dict:
        """兼容 face.py FaceDetector 的旧接口。

        Args:
            face_crop: BGR 人脸裁剪图像
            landmarks: dlib full_object_detection（68 点）

        Returns:
            {"score": float, "reasons": list[str], "details": dict}
        """
        if not self.enabled:
            return {"score": 1.0, "reasons": [], "details": {}}

        # 保存人脸裁剪到历史队列
        self._face_crops.append(face_crop.copy())

        # 分别获取各信号分数（不重复计算）
        blink_score, blink_detected = self._compute_blink_score(landmarks)
        motion_score = self._analyze_motion(face_crop)
        texture_score = self._analyze_texture(face_crop)

        score = W_EAR * blink_score + W_MOTION * motion_score + W_TEXTURE * texture_score
        score = round(float(np.clip(score, 0.0, 1.0)), 3)

        reasons: list[str] = []
        if blink_score < W_EAR:
            reasons.append("no_blink")
        if motion_score < W_MOTION:
            reasons.append("low_motion")
        if texture_score < W_TEXTURE:
            reasons.append("texture_anomaly")

        details = {
            "ear_score": round(blink_score, 3),
            "motion_score": round(motion_score, 3),
            "texture_score": round(texture_score, 3),
            "blink_detected": blink_detected,
            "frames_cached": len(self._ear_history),
        }

        return {"score": score, "reasons": reasons, "details": details}

    def reset(self) -> None:
        """重置所有历史状态（换人或长时间无人脸后调用）。"""
        self._ear_history.clear()
        self._prev_face_crop = None
        self._face_crops.clear()
        self._blink_detected = False
        self._was_below_thresh = False

    # ------------------------------------------------------------------
    # 测试兼容方法
    # ------------------------------------------------------------------

    @staticmethod
    def _ear(landmarks, indices: list[int]) -> float:
        """计算指定索引对应的眼睛 EAR。

        Args:
            landmarks: dlib full_object_detection
            indices: 6 个 landmark 索引

        Returns:
            EAR 值
        """
        pts = [(landmarks.part(i).x, landmarks.part(i).y) for i in indices]
        return LivenessDetector._compute_ear(pts)

    def _compute_ear_score(self, landmarks) -> tuple[float, bool]:
        """计算眨眼活体分数（兼容测试的命名）。
        
        Returns:
            (score, blinked)
        """
        return self._compute_blink_score(landmarks)

    def _compute_motion_score(self, gray: np.ndarray) -> float:
        """基于灰度图计算光流运动分数（兼容测试）。

        Args:
            gray: 灰度人脸裁剪图像

        Returns:
            归一化运动分数 [0, 1]
        """
        if self._prev_face_crop is None:
            self._prev_face_crop = gray.copy()
            return 0.5

        prev = self._prev_face_crop
        if prev.shape != gray.shape:
            prev = cv2.resize(prev, (gray.shape[1], gray.shape[0]))

        try:
            flow = cv2.calcOpticalFlowFarneback(
                prev, gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
            )
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            avg_mag = float(np.mean(mag))
        except Exception:
            avg_mag = 0.0

        self._prev_face_crop = gray.copy()

        if self.motion_threshold <= 0:
            return 1.0
        score = min(1.0, avg_mag / self.motion_threshold)
        return max(0.0, score)

    def _compute_texture_score(self, gray: np.ndarray) -> float:
        """基于灰度图计算 LBP 纹理自然度分数（使用熵值）。

        熵值高 → 纹理丰富自然；熵值低 → 纹理均匀/失真。

        Args:
            gray: 灰度人脸裁剪图像

        Returns:
            纹理自然度分数 [0, 1]
        """
        import math
        try:
            lbp = self._lbp_vectorized(gray)
            hist, _ = np.histogram(lbp.ravel(), bins=256, range=(0, 256))
            hist = hist.astype(np.float64)
            total = hist.sum()
            if total == 0:
                return 0.0
            probs = hist / total
            # 熵值计算：-sum(p * log(p)) (跳过 p=0)
            entropy = 0.0
            for p in probs:
                if p > 0:
                    entropy -= p * math.log(p)
            # 最大熵 = log(256) ≈ 5.545，归一化到 [0, 1]
            max_entropy = math.log(256)
            if max_entropy <= 0:
                return 1.0
            return min(1.0, entropy / (max_entropy * self.texture_threshold * 5))
        except Exception:
            return 0.5

    # ------------------------------------------------------------------
    # 信号 1: 眨眼检测（EAR）
    # ------------------------------------------------------------------

    def _detect_blink(self, landmarks) -> float:
        """基于 EAR 时序检测眨眼。

        Args:
            landmarks: dlib full_object_detection（68 点）

        Returns:
            blink_liveness score [0, 1]: 1.0 = 检测到眨眼，0.0 = 未检测到
        """
        score, _ = self._compute_blink_score(landmarks)
        return score

    def _compute_blink_score(self, landmarks) -> tuple[float, bool]:
        """计算眨眼活体分数及是否检测到眨眼。

        Returns:
            (score, blinked): score ∈ [0, 1], blinked = True 表示窗口内发生过眨眼
        """
        # 左眼: landmarks 36-41  |  右眼: landmarks 42-47
        left_pts = [(landmarks.part(i).x, landmarks.part(i).y) for i in range(36, 42)]
        right_pts = [(landmarks.part(i).x, landmarks.part(i).y) for i in range(42, 48)]

        left_ear = self._compute_ear(left_pts)
        right_ear = self._compute_ear(right_pts)
        avg_ear = (left_ear + right_ear) / 2.0
        self._ear_history.append(avg_ear)

        if len(self._ear_history) < 5:
            # 数据不足，中性分
            return 0.5, False

        # 眨眼上升沿检测：EAR 低于阈值后回升
        ear_list = list(self._ear_history)
        blinked = False
        for i in range(2, len(ear_list)):
            below = ear_list[i - 2] < self.ear_blink_thresh
            above = ear_list[i] > self.ear_blink_thresh + 0.05
            if below and above:
                blinked = True
                break

        if blinked:
            self._blink_detected = True
            return 1.0, True

        # 已检测到过眨眼 → 保持 1.0
        if self._blink_detected:
            return 1.0, True

        # 无眨眼，返回随时间递减的分数（激励持续观察）
        ratio = len(self._ear_history) / max(self.history_size, 1)
        return max(0.0, 0.5 * (1.0 - ratio)), False

    @staticmethod
    def _compute_ear(eye_points: list[tuple[float, float]]) -> float:
        """计算单只眼睛的 Eye Aspect Ratio。

        EAR = (‖p2−p6‖ + ‖p3−p5‖) / (2 × ‖p1−p4‖)

        Args:
            eye_points: 6 个 (x, y) 坐标，按 dlib 68 点顺序

        Returns:
            EAR 值（正常睁眼约 0.3~0.4，闭眼约 0.15~0.25）
        """
        pts = [np.array(p, dtype=np.float64) for p in eye_points]
        # p1=pts[0], p2=pts[1], p3=pts[2], p4=pts[3], p5=pts[4], p6=pts[5]
        a = float(np.linalg.norm(pts[1] - pts[5]))  # ‖p2-p6‖
        b = float(np.linalg.norm(pts[2] - pts[4]))  # ‖p3-p5‖
        c = float(np.linalg.norm(pts[0] - pts[3]))  # ‖p1-p4‖
        if c < 1e-6:
            return 0.0
        return (a + b) / (2.0 * c)

    # ------------------------------------------------------------------
    # 信号 2: 微动分析（光流幅值）
    # ------------------------------------------------------------------

    def _analyze_motion(self, face_crop: np.ndarray) -> float:
        """基于 Farneback 光流幅值判定面部自然微动。

        真实人脸存在 3D 微动（呼吸、表情等），光流幅值较高；
        照片/屏幕无自然微动，光流幅值接近 0。

        Args:
            face_crop: BGR 人脸裁剪图像

        Returns:
            归一化运动分数 [0, 1]，1.0 = 充分运动
        """
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)

        if self._prev_face_crop is None:
            self._prev_face_crop = gray
            return 0.5  # 第一帧，中性

        prev_gray = self._prev_face_crop

        # 尺寸不一致时 resize prev → current
        if prev_gray.shape != gray.shape:
            prev_gray = cv2.resize(prev_gray, (gray.shape[1], gray.shape[0]))

        try:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
            )
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            avg_mag = float(np.mean(mag))
        except Exception:
            avg_mag = 0.0

        self._prev_face_crop = gray

        # 归一化：avg_mag / motion_threshold → [0, 1]
        if self.motion_threshold <= 0:
            return 1.0
        score = min(1.0, avg_mag / self.motion_threshold)
        return max(0.0, score)

    # ------------------------------------------------------------------
    # 信号 3: 纹理分析（LBP 直方图方差）
    # ------------------------------------------------------------------

    def _analyze_texture(self, face_crop: np.ndarray) -> float:
        """基于 LBP 直方图熵值判别翻拍/打印/AI 伪影。

        真实人脸纹理丰富 → LBP 分布均匀 → 熵值高；
        打印照片/屏幕存在伪影导致纹理均匀化或失真 → 熵值低。

        Args:
            face_crop: BGR 人脸裁剪图像

        Returns:
            纹理自然度分数 [0, 1]，越高越像真人
        """
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        return self._compute_texture_score(gray)

    # ------------------------------------------------------------------
    # LBP 向量化实现
    # ------------------------------------------------------------------

    @staticmethod
    def _lbp_vectorized(gray: np.ndarray) -> np.ndarray:
        """向量化 LBP（Local Binary Patterns），3×3 邻域，8 邻点。

        对每个像素，将其 8 邻域值与中心值比较，生成 8-bit LBP 码。

        Args:
            gray: 灰度图 (H, W)

        Returns:
            LBP 特征图 (H, W)，dtype=uint8
        """
        h, w = gray.shape
        # 边缘填充（replicate）
        padded = np.pad(gray, pad_width=1, mode='edge')  # (H+2, W+2)

        center = gray  # (H, W)

        # 8 个邻域视图（row-major: (i,j) 偏移）
        #  0 1 2
        #  7 C 3
        #  6 5 4
        neighbors = [
            padded[0:h,   0:w  ],   # 0: 左上  (i-1,j-1)
            padded[0:h,   1:w+1],   # 1: 上    (i-1,j)
            padded[0:h,   2:w+2],   # 2: 右上  (i-1,j+1)
            padded[1:h+1, 2:w+2],   # 3: 右    (i,j+1)
            padded[2:h+2, 2:w+2],   # 4: 右下  (i+1,j+1)
            padded[2:h+2, 1:w+1],   # 5: 下    (i+1,j)
            padded[2:h+2, 0:w  ],   # 6: 左下  (i+1,j-1)
            padded[1:h+1, 0:w  ],   # 7: 左    (i,j-1)
        ]

        code = np.zeros((h, w), dtype=np.uint8)
        for bit_idx, nbr in enumerate(neighbors):
            code |= ((nbr >= center).astype(np.uint8) << bit_idx)

        return code
