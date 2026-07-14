"""三层反欺骗模型：AMTEN → Spatial + Frequency → CBAM → 分类头

对齐 shreyash1706/Solving-Deepfakes-with-Traces-Frequency-and-Attention 的 AMTENFC 架构。
该模型在 140k Real/Fake Faces 数据集上达到 ~98.97% 测试准确率。

架构：
  第一层 AMTEN：     自适应操作痕迹提取 (3→12ch)
  第二层 双分支：      SpatialLearner (12→256ch) + FrequencyLearner (DCT 48→128ch)
  第三层 CBAM：      384ch → 通道+空间注意力
  分类头：           BT4 → GAP → Linear(384→1) → sigmoid

输入：RGB (B,3,128,128) + DCT特征 (B,48,H',W')
输出：real_score ∈ [0, 1]
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ==============================================================================
# DCT 特征提取（与 repo block_dct 完全一致）
# ==============================================================================

def block_dct(image_np: np.ndarray, block_size: int = 4, stride: int = 2) -> np.ndarray:
    """从 RGB 图像提取逐块 DCT 特征，输出 48 通道特征图。

    对齐 repo 的 block_dct(): 4×4 块 DCT，zigzag 选取前 16 系数，
    R/G/B 交错排列 → 48 通道。

    Args:
        image_np: (H, W, 3) uint8 或 float [0, 255] RGB 图像
        block_size: DCT 块大小
        stride: 块滑动步长

    Returns:
        dct_features: (48, H', W') float32 DCT 系数图
    """
    try:
        from scipy.fftpack import dct as scipy_dct
    except ImportError:
        # fallback: 返回零特征图
        h, w = image_np.shape[:2]
        num_blocks_y = (h - block_size) // stride + 1
        num_blocks_x = (w - block_size) // stride + 1
        return np.zeros((48, num_blocks_y, num_blocks_x), dtype=np.float32)

    h, w, c = image_np.shape
    num_blocks_y = (h - block_size) // stride + 1
    num_blocks_x = (w - block_size) // stride + 1

    # Zigzag 顺序取前 16 个 DCT 系数
    zigzag_index = [0, 1, 5, 6, 2, 4, 7, 12, 3, 8, 11, 13, 9, 10, 14, 15]

    def compute_dct(channel: np.ndarray) -> np.ndarray:
        coeffs = np.zeros((16, num_blocks_y, num_blocks_x), dtype=np.float32)
        for i, y in enumerate(range(0, h - block_size + 1, stride)):
            for j, x in enumerate(range(0, w - block_size + 1, stride)):
                patch = channel[y:y + block_size, x:x + block_size].astype(np.float32)
                dct_patch = scipy_dct(scipy_dct(patch.T, norm='ortho').T, norm='ortho')
                coeffs[:, i, j] = dct_patch.flatten()[zigzag_index]
        return coeffs

    r, g, b = image_np[:, :, 0], image_np[:, :, 1], image_np[:, :, 2]
    dct_r, dct_g, dct_b = compute_dct(r), compute_dct(g), compute_dct(b)

    # R/G/B 交错排列: R0,G0,B0,R1,G1,B1,...,R15,G15,B15
    reordered = []
    for i in range(16):
        reordered.extend([dct_r[i], dct_g[i], dct_b[i]])
    return np.stack(reordered, axis=0).astype(np.float32)  # (48, H', W')


# ==============================================================================
# PyTorch 模型定义（完全对齐 repo）
# ==============================================================================

def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


if _torch_available():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    # ------------------------------------------------------------------
    # 基础构建块
    # ------------------------------------------------------------------

    class BT1(nn.Module):
        """单卷积块: Conv3×3 + BN + ReLU"""

        def __init__(self, in_channels: int, out_channels: int, groups: int = 1):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, stride=1, kernel_size=3,
                          padding=1, groups=groups),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=False),
            )

        def forward(self, x):
            return self.conv(x)

    class BT2(nn.Module):
        """残差块: Conv3×3→BN→ReLU→Conv3×3→BN + 恒等"""

        def __init__(self, channels: int):
            super().__init__()
            self.block = nn.Sequential(
                nn.Conv2d(channels, channels, kernel_size=3, padding=1),
                nn.BatchNorm2d(channels),
                nn.ReLU(inplace=False),
                nn.Conv2d(channels, channels, kernel_size=3, padding=1),
                nn.BatchNorm2d(channels),
            )

        def forward(self, x):
            return self.block(x) + x

    class BT3(nn.Module):
        """下采样残差块: Conv3×3×2 + AvgPool(3,2) 主路 + 1×1(stride=2) 跳跃连接"""

        def __init__(self, in_channels: int, out_channels: int):
            super().__init__()
            self.main = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=False),
                nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1),
                nn.BatchNorm2d(out_channels),
                nn.AvgPool2d(kernel_size=3, stride=2, padding=1),
            )
            self.skip = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, kernel_size=1, stride=2),
                nn.BatchNorm2d(out_channels),
            )

        def forward(self, x):
            return self.main(x) + self.skip(x)

    class BT4(nn.Module):
        """收尾块: Conv3×3→ReLU→Conv1×1→BN→AdaptiveAvgPool2d(1)"""

        def __init__(self, in_channels: int):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv2d(in_channels, in_channels, kernel_size=3, padding=1),
                nn.BatchNorm2d(in_channels),
                nn.ReLU(inplace=False),
                nn.Conv2d(in_channels, in_channels, kernel_size=1),
                nn.BatchNorm2d(in_channels),
                nn.AdaptiveAvgPool2d((1, 1)),
            )

        def forward(self, x):
            return self.conv(x)

    # ------------------------------------------------------------------
    # AMTEN — 自适应操作痕迹提取
    # ------------------------------------------------------------------

    class AMTEN(nn.Module):
        """AMTEN: 预测干净图像 → 做差得 fmt → 密集连接提取痕迹 → 输出 12ch"""

        def __init__(self):
            super().__init__()
            self.conv1 = nn.Conv2d(3, 3, kernel_size=3, stride=1, padding=1)
            # F1: Conv2 + Conv3
            self.conv2 = nn.Conv2d(3, 3, kernel_size=3, stride=1, padding=1)
            self.bn2 = nn.BatchNorm2d(3)
            self.conv3 = nn.Conv2d(3, 3, kernel_size=3, stride=1, padding=1)
            self.bn3 = nn.BatchNorm2d(3)
            # F2: Conv4 + Conv5
            self.conv4 = nn.Conv2d(6, 6, kernel_size=3, stride=1, padding=1)
            self.bn4 = nn.BatchNorm2d(6)
            self.conv5 = nn.Conv2d(6, 6, kernel_size=3, stride=1, padding=1)
            self.bn5 = nn.BatchNorm2d(6)

        def forward(self, x):
            pred = self.conv1(x)
            fmt = pred - x                              # (B, 3, H, W)
            f1_inter = F.relu(self.bn2(self.conv2(fmt)))
            f1 = F.relu(self.bn3(self.conv3(f1_inter)))
            f1_concat = torch.cat([f1, fmt], dim=1)     # (B, 6, H, W)
            f2_inter = F.relu(self.bn4(self.conv4(f1_concat)))
            f2 = F.relu(self.bn5(self.conv5(f2_inter)))
            freu = torch.cat([f2, f1_concat], dim=1)    # (B, 12, H, W)
            return freu

    # ------------------------------------------------------------------
    # CBAM — 卷积块注意力（对齐 repo）
    # ------------------------------------------------------------------

    class BasicConv(nn.Module):
        def __init__(self, in_planes, out_planes, kernel_size, stride=1,
                     padding=0, dilation=1, groups=1, relu=True,
                     bn=True, bias=False):
            super().__init__()
            self.out_channels = out_planes
            self.conv = nn.Conv2d(in_planes, out_planes, kernel_size=kernel_size,
                                  stride=stride, padding=padding, dilation=dilation,
                                  groups=groups, bias=bias)
            self.bn = nn.BatchNorm2d(out_planes, eps=1e-5, momentum=0.01,
                                     affine=True) if bn else None
            self.relu = nn.ReLU() if relu else None

        def forward(self, x):
            x = self.conv(x)
            if self.bn is not None:
                x = self.bn(x)
            if self.relu is not None:
                x = self.relu(x)
            return x

    class Flatten(nn.Module):
        def forward(self, x):
            return x.view(x.size(0), -1)

    class ChannelGate(nn.Module):
        def __init__(self, gate_channels, reduction_ratio=16,
                     pool_types=('avg', 'max')):
            super().__init__()
            self.gate_channels = gate_channels
            self.mlp = nn.Sequential(
                Flatten(),
                nn.Linear(gate_channels, gate_channels // reduction_ratio),
                nn.ReLU(),
                nn.Linear(gate_channels // reduction_ratio, gate_channels),
            )
            self.pool_types = pool_types
            self.avg_pool = nn.AdaptiveAvgPool2d(1)
            self.max_pool = nn.AdaptiveMaxPool2d(1)

        def forward(self, x):
            channel_att_sum = None
            for pool_type in self.pool_types:
                if pool_type == 'avg':
                    avg_pool = self.avg_pool(x)
                    channel_att_raw = self.mlp(avg_pool)
                elif pool_type == 'max':
                    max_pool = self.max_pool(x)
                    channel_att_raw = self.mlp(max_pool)
                else:
                    continue
                if channel_att_sum is None:
                    channel_att_sum = channel_att_raw
                else:
                    channel_att_sum = channel_att_sum + channel_att_raw
            # 使用 unsqueeze + repeat 替代 expand_as（ONNX 兼容）
            scale = torch.sigmoid(channel_att_sum).unsqueeze(2).unsqueeze(3)
            scale = scale.repeat(1, 1, x.size(2), x.size(3))
            return x * scale

    class ChannelPool(nn.Module):
        def forward(self, x):
            return torch.cat(
                (torch.max(x, 1)[0].unsqueeze(1),
                 torch.mean(x, 1).unsqueeze(1)), dim=1)

    class SpatialGate(nn.Module):
        def __init__(self):
            super().__init__()
            kernel_size = 7
            self.compress = ChannelPool()
            self.spatial = BasicConv(2, 1, kernel_size, stride=1,
                                     padding=(kernel_size - 1) // 2, relu=False)

        def forward(self, x):
            x_compress = self.compress(x)
            x_out = self.spatial(x_compress)
            scale = F.sigmoid(x_out)
            return x * scale

    class CBAM(nn.Module):
        """CBAM: Channel Gate → Spatial Gate"""

        def __init__(self, gate_channels, reduction_ratio=16,
                     pool_types=('avg', 'max'), no_spatial=False):
            super().__init__()
            self.ChannelGate = ChannelGate(gate_channels, reduction_ratio,
                                           pool_types)
            self.no_spatial = no_spatial
            if not no_spatial:
                self.SpatialGate = SpatialGate()

        def forward(self, x):
            x_out = self.ChannelGate(x)
            if not self.no_spatial:
                x_out = self.SpatialGate(x_out)
            return x_out

    # ------------------------------------------------------------------
    # SpatialLearner / FrequencyLearner
    # ------------------------------------------------------------------

    class SpatialLearner(nn.Module):
        """空间分支：AMTEN(3→12) → BT1×2 → BT2×3 → BT3×3 → (BT3+CBAM)(128) → BT3(256)"""

        def __init__(self):
            super().__init__()
            self.spatial = nn.Sequential(
                AMTEN(),
                BT1(12, 64),
                BT1(64, 16),
                BT2(16),
                BT2(16),
                BT2(16),
                BT3(16, 32),
                BT3(32, 64),
                nn.Sequential(BT3(64, 128), CBAM(128)),
                BT3(128, 256),
            )

        def forward(self, x):
            return self.spatial(x)

    class FrequencyLearner(nn.Module):
        """频域分支：BT1×3(48→32) → BT2×5 → BT3×2 → (BT3+CBAM)(128)"""

        def __init__(self):
            super().__init__()
            self.freq = nn.Sequential(
                BT1(48, 48, groups=4),
                BT1(48, 96),
                BT1(96, 32),
                BT2(32),
                BT2(32),
                BT2(32),
                BT2(32),
                BT2(32),
                BT3(32, 32),
                BT3(32, 64),
                nn.Sequential(BT3(64, 128), CBAM(128)),
            )

        def forward(self, x):
            return self.freq(x)

    # ------------------------------------------------------------------
    # AMTENFC — 完整模型
    # ------------------------------------------------------------------

    class AMTENFC(nn.Module):
        """AMTEN-Freq-CBAM: 双输入 (RGB + DCT) 端到端深度伪造检测器。

        Args:
            num_classes: 输出类别数，1 = sigmoid 二分类
        """

        def __init__(self, num_classes: int = 1):
            super().__init__()
            self.spatial = SpatialLearner()              # 3 → 256 ch, /16
            self.freq = FrequencyLearner()               # 48 → 128 ch, /16
            self.l2norm = nn.LayerNorm([384, 8, 8])
            self.cbam = CBAM(gate_channels=384)
            self.bt4 = BT4(in_channels=384)             # 384 → 384, GAP → (1,1)
            self.classifier = nn.Linear(384, num_classes)

        def forward(self, rgb, dct):
            x_spatial = self.spatial(rgb)               # (B, 256, 8, 8)
            x_freq = self.freq(dct)                     # (B, 128, 8, 8)
            x = torch.cat([x_spatial, x_freq], dim=1)   # (B, 384, 8, 8)
            x = self.l2norm(x)
            x = self.cbam(x)
            x = self.bt4(x)                             # (B, 384, 1, 1)
            x = x.view(x.size(0), -1)                   # (B, 384)
            return self.classifier(x)                    # raw logits

    # 别名：兼容旧接口
    AntiSpoofModel = AMTENFC

else:
    AMTEN = None
    BT1 = BT2 = BT3 = BT4 = None
    CBAM = None
    SpatialLearner = None
    FrequencyLearner = None
    AMTENFC = None
    AntiSpoofModel = None


# ==============================================================================
# AntiSpoofDetector — ONNX Runtime 推理封装（生产使用）
# ==============================================================================

class AntiSpoofDetector:
    """三层反欺骗模型 ONNX 推理器（双输入：RGB + DCT）。

    封装 onnxruntime 推理，提供简洁的 detect() 接口。
    DCT 特征在预处理阶段实时计算（block_dct）。
    支持延迟加载，模型缺失时降级返回中性分。
    """

    INPUT_SIZE = 128
    SPOOF_THRESHOLD = 0.5

    def __init__(
        self,
        model_path: Optional[str] = None,
        pytorch_model_path: Optional[str] = None,
        minifas_model_path: Optional[str] = None,
        amtenfc_onnx_weight: float = 0.5,
        amtenfc_pytorch_weight: float = 0.5,
    ):
        if model_path is None:
            model_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "model_weights", "antispoof_amtenet_vanet.onnx",
            )
        self._model_path = model_path
        self._session = None
        self._input_names: list[str] = []

        # ---- PyTorch 分支 ----
        if pytorch_model_path is None:
            pytorch_model_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "model_weights", "best_amtenfc.pth",
            )
        self._pytorch_model_path = pytorch_model_path
        self._torch_model = None

        # ---- MiniFASNetV2 分支 ----
        if minifas_model_path is None:
            minifas_model_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "model_weights", "2.7_80x80_MiniFASNetV2.onnx",
            )
        self._minifas_model_path = minifas_model_path
        self._minifas_session = None
        self._minifas_input_name = ""

        # ---- Ensemble 权重 ----
        self._amtenfc_onnx_weight = amtenfc_onnx_weight
        self._amtenfc_pytorch_weight = amtenfc_pytorch_weight

        # ---- FSD 观测器（零样本 AIGC 检测，CVPR 2025） ----
        self._fsd_detector = None
        self._fsd_load_attempted = False
        # EMA 平滑：防止真人视频偶发尖刺（单帧 z<-15）误触发
        self._fsd_z_ema: Optional[float] = None
        self._fsd_ema_alpha = 0.5  # 平滑系数，0.5=快速响应（2帧收敛）

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, face_crop: np.ndarray, full_frame: np.ndarray = None) -> Tuple[float, float, float, float]:
        """四模型 ensemble 推理：FSD + AMTEN-FC + MiniFASNetV2 → 静态融合分。

        Args:
            face_crop: BGR 人脸裁剪图像 (H, W, 3)
            full_frame: 可选，BGR 全帧图像。FSD 优先在全帧上检测（换脸边界/全局伪影）

        Returns:
            (deepfake_score, minifas_score, static_score, fsd_score):
                - deepfake_score: AMTEN-FC ensemble 分 ∈ [0,1]
                - minifas_score: MiniFASNetV2 分 ∈ [0,1]
                - static_score: 0.45*fsd + 0.30*deepfake + 0.25*minifas
                - fsd_score: FSD 归一化分 ∈ [0,1]
        """
        # 确保所有模型加载
        self._load_model()
        self._load_pytorch_model()
        self._load_minifas()
        self._load_fsd()

        # ---- AMTEN-FC ensemble ----
        score_onnx: Optional[float] = None
        score_pytorch: Optional[float] = None

        if self._session is not None:
            try:
                rgb_blob, dct_blob = self._preprocess(face_crop)
                outputs = self._session.run(
                    None, {self._input_names[0]: rgb_blob, self._input_names[1]: dct_blob}
                )
                logits = outputs[0]
                score_onnx = float(1.0 / (1.0 + np.exp(-logits[0][0])))
                score_onnx = float(np.clip(score_onnx, 0.0, 1.0))
            except Exception:
                logger.warning("[antispoof] AMTEN-FC ONNX 推理失败", exc_info=True)

        if self._torch_model is not None:
            score_pytorch = self._infer_amtenfc_pytorch(face_crop)

        # 加权融合
        if score_onnx is not None and score_pytorch is not None:
            deepfake = float(
                self._amtenfc_onnx_weight * score_onnx +
                self._amtenfc_pytorch_weight * score_pytorch
            )
        elif score_onnx is not None:
            deepfake = score_onnx
        elif score_pytorch is not None:
            deepfake = score_pytorch
        else:
            deepfake = 0.5

        deepfake = float(np.clip(deepfake, 0.0, 1.0))

        # ---- MiniFASNetV2（已弃用，始终返回 0） ----
        minifas = 0.0

        # ---- FSD 零样本检测（优先用全帧，人脸裁剪做 fallback）----
        fsd = self._detect_fsd(full_frame if full_frame is not None else face_crop)

        # ---- 静态融合：FSD 主权重 (0.60) + AMTEN-FC (0.40) ----
        # FSD=0.0 时 static_max = 0.40 < 0.45 → 触发性检测
        static_score = float(np.clip(
            0.60 * fsd + 0.40 * deepfake,
            0.0, 1.0,
        ))

        return deepfake, minifas, static_score, fsd

    def detect_fsd_only(self, full_frame: np.ndarray) -> float:
        """纯 FSD 检测入口：只跑 FSD 零样本 AIGC 检测，不加载其他模型。

        用于活体检测流水线最前端的 AI 生成预检门禁：
        FSD 先判断是否 AI 生成 → 是则直接拦截 → 否则进入完整活体检测。

        Args:
            full_frame: BGR 全帧图像 (H, W, 3)

        Returns:
            fsd_score ∈ [0, 1], 1.0 = 真实, 0.0 = AI生成
        """
        self._load_fsd()
        return self._detect_fsd(full_frame)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_model(self):
        if not os.path.exists(self._model_path):
            logger.warning("[antispoof] 模型文件不存在: %s，反欺骗功能降级", self._model_path)
            return

        try:
            import onnxruntime as ort
            self._session = ort.InferenceSession(
                self._model_path, providers=["CPUExecutionProvider"]
            )
            self._input_names = [inp.name for inp in self._session.get_inputs()]
            # Warmup
            dummy_rgb = np.zeros((1, 3, self.INPUT_SIZE, self.INPUT_SIZE), dtype=np.float32)
            dummy_dct = np.zeros((1, 48, 63, 63), dtype=np.float32)
            self._session.run(
                None, {self._input_names[0]: dummy_rgb, self._input_names[1]: dummy_dct}
            )
            logger.info("[antispoof] 三层反欺骗模型已加载: %s", os.path.basename(self._model_path))
        except Exception as e:
            logger.warning("[antispoof] 模型加载失败: %s", e)

    def _preprocess(self, face_crop: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """预处理：RGB → resize 128 → /255 → NCHW；同时计算 DCT 特征。

        Args:
            face_crop: BGR (H, W, 3) uint8

        Returns:
            (rgb_blob, dct_blob): (1,3,128,128) + (1,48,63,63) float32
        """
        # RGB 分支
        resized = cv2.resize(face_crop, (self.INPUT_SIZE, self.INPUT_SIZE))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        blob = rgb.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))
        rgb_blob = np.expand_dims(blob, axis=0).astype(np.float32)

        # DCT 分支
        dct_feat = block_dct(rgb, block_size=4, stride=2)  # (48, 63, 63)
        dct_blob = np.expand_dims(dct_feat, axis=0).astype(np.float32)

        return rgb_blob, dct_blob

    # ------------------------------------------------------------------
    # AMTEN-FC PyTorch 分支
    # ------------------------------------------------------------------

    def _load_pytorch_model(self):
        """加载 best_amtenfc.pth 到 AMTENFC PyTorch 模型（延迟加载）。"""
        if self._torch_model is not None:
            return
        if not os.path.exists(self._pytorch_model_path):
            logger.warning("[antispoof] PyTorch 模型文件不存在: %s", self._pytorch_model_path)
            return
        if AMTENFC is None:
            logger.warning("[antispoof] PyTorch 未安装，跳过 AMTEN-FC PyTorch 加载")
            return
        try:
            self._torch_model = AMTENFC(num_classes=1)
            state_dict = torch.load(self._pytorch_model_path, map_location="cpu")
            self._torch_model.load_state_dict(state_dict)
            self._torch_model.eval()
            logger.info(
                "[antispoof] AMTEN-FC PyTorch 模型已加载: %s",
                os.path.basename(self._pytorch_model_path),
            )
        except Exception as e:
            self._torch_model = None
            logger.warning("[antispoof] AMTEN-FC PyTorch 模型加载失败: %s", e)

    def _infer_amtenfc_pytorch(self, face_crop: np.ndarray) -> float:
        """使用 PyTorch AMTENFC 模型推理。

        Args:
            face_crop: BGR 人脸裁剪 (H, W, 3)

        Returns:
            real_score ∈ [0, 1]
        """
        try:
            import torch as _torch

            # RGB 预处理: BGR → resize(128,128) → RGB → /255 → CHW → (1,3,128,128)
            resized = cv2.resize(face_crop, (128, 128))
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            blob = rgb.astype(np.float32) / 255.0
            blob = np.transpose(blob, (2, 0, 1))
            rgb_tensor = _torch.from_numpy(blob).unsqueeze(0).float()  # (1, 3, 128, 128)

            # DCT 特征
            dct_feat = block_dct(rgb, block_size=4, stride=2)  # (48, 63, 63)
            dct_tensor = _torch.from_numpy(dct_feat).unsqueeze(0).float()  # (1, 48, 63, 63)

            with _torch.no_grad():
                logits = self._torch_model(rgb_tensor, dct_tensor)
                score = float(_torch.sigmoid(logits.squeeze()).item())

            return float(np.clip(score, 0.0, 1.0))
        except Exception:
            logger.warning("[antispoof] AMTEN-FC PyTorch 推理失败", exc_info=True)
            return 0.5

    # ------------------------------------------------------------------
    # MiniFASNetV2 ONNX 分支
    # ------------------------------------------------------------------

    def _load_minifas(self):
        """加载 MiniFASNetV2 ONNX 模型（延迟加载）。"""
        if self._minifas_session is not None:
            return
        if not os.path.exists(self._minifas_model_path):
            logger.warning("[antispoof] MiniFAS 模型文件不存在: %s", self._minifas_model_path)
            return
        try:
            import onnxruntime as _ort
            self._minifas_session = _ort.InferenceSession(
                self._minifas_model_path, providers=["CPUExecutionProvider"]
            )
            self._minifas_input_name = self._minifas_session.get_inputs()[0].name
            logger.info(
                "[antispoof] MiniFASNetV2 模型已加载: %s",
                os.path.basename(self._minifas_model_path),
            )
        except Exception as e:
            self._minifas_session = None
            logger.warning("[antispoof] MiniFASNetV2 模型加载失败: %s", e)

    def _infer_minifas(self, face_crop: np.ndarray) -> float:
        """MiniFASNetV2 ONNX 推理。

        Input: 80×80 BGR, NCHW, float32 [0, 255]（不归一化！）
        Output: (1, 3) logits → softmax → class_1 概率

        Args:
            face_crop: BGR 人脸裁剪 (H, W, 3)

        Returns:
            real_score ∈ [0, 1]
        """
        if self._minifas_session is None:
            return 0.5

        try:
            # 预处理: BGR → resize(80,80) → HWC→CHW → (1,3,80,80) float32
            resized = cv2.resize(face_crop, (80, 80))
            blob = resized.astype(np.float32)  # [0, 255]，不归一化
            blob = np.transpose(blob, (2, 0, 1))  # HWC → CHW
            blob = np.expand_dims(blob, axis=0)  # (1, 3, 80, 80)

            logits = self._minifas_session.run(
                None, {self._minifas_input_name: blob}
            )[0]  # (1, 3)

            # softmax
            exp_logits = np.exp(logits - np.max(logits))
            probs = exp_logits / np.sum(exp_logits)
            # class 1 = Real
            real_score = float(probs[0, 1])
            return float(np.clip(real_score, 0.0, 1.0))
        except Exception:
            logger.warning("[antispoof] MiniFASNetV2 推理失败", exc_info=True)
            return 0.5

    # ------------------------------------------------------------------
    # FSD 零样本 AIGC 检测（CVPR 2025）
    # ------------------------------------------------------------------

    def _load_fsd(self):
        """加载 FSD 检测器（延迟加载，零样本扩散模型检测）。

        Forensic Self-Descriptions: 仅用真实图像训练，泛化到 24 种生成器，
        包括 Stable Diffusion、Midjourney、DALL-E 等扩散模型。
        """
        if self._fsd_detector is not None or self._fsd_load_attempted:
            return
        self._fsd_load_attempted = True
        try:
            from fsd import FSDDetector
            self._fsd_detector = FSDDetector.load(device="cpu")
            # max_size 不在此固定，改由 _detect_fsd 按每帧尺寸动态设定（禁止放大）。
            logger.info("[antispoof] FSD 零样本检测器已加载 (CVPR 2025, 动态max_size)")
        except Exception as e:
            self._fsd_detector = None
            logger.warning("[antispoof] FSD 检测器加载失败: %s", e)

    def _detect_fsd(self, image: np.ndarray) -> float:
        """FSD 零样本推理：BGR numpy → PIL → FSD z_score → 归一化 [0,1]。

        关键：保留原图分辨率，不裁剪、不放大。max_size 动态设为
        min(输入帧长边, FSD_MAX_SIZE_CAP)，避免把低清图放大而抹掉 AI 频域指纹。
        （实测：324宽换脸视频 max_size=324→z≈-21 命中；放大到512→z≈-1 漏判。）

        Args:
            image: BGR 图像 (H, W, 3)

        Returns:
            fsd_score ∈ [0, 1], 1.0 = 真实, 0.0 = AI生成
        """
        if self._fsd_detector is None:
            return 0.5

        try:
            from PIL import Image
            from ..config import Config

            h, w = image.shape[:2]
            long_side = max(h, w)
            # 永不放大：max_size 取原图长边与上限的较小值
            self._fsd_detector.config["fsd"]["max_size"] = min(long_side, Config.FSD_MAX_SIZE_CAP)

            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            result = self._fsd_detector.score(pil_img)
            z = result.z_score

            # EMA 平滑：防止真人视频偶发尖刺（单帧 z<-15）误触发
            if self._fsd_z_ema is None:
                self._fsd_z_ema = z
            else:
                self._fsd_z_ema = (self._fsd_ema_alpha * z
                                   + (1.0 - self._fsd_ema_alpha) * self._fsd_z_ema)
            z_smooth = self._fsd_z_ema

            self._fsd_call_count = getattr(self, '_fsd_call_count', 0) + 1
            if self._fsd_call_count % 30 == 1:
                logger.info("[antispoof] FSD z=%.3f (smooth=%.3f) is_fake=%s max_size=%d (第%d帧)",
                            z, z_smooth, result.is_fake,
                            self._fsd_detector.config["fsd"]["max_size"],
                            self._fsd_call_count)

            # 归一化: z_smooth ≤ -25 → 0.0 (AI生成), z_smooth ≥ -1 → 1.0 (真实)
            # 区间 [-25, -1]：真人 webcam z≈-5~-15 → fsd≈0.4~0.8 不干扰，
            # Magic Hour z≈-40~-72 → fsd=0.0 触发拦截
            fsd_score = float(np.clip((z_smooth + 25.0) / 24.0, 0.0, 1.0))
            return fsd_score
        except Exception:
            logger.warning("[antispoof] FSD 推理失败", exc_info=True)
            return 0.5
