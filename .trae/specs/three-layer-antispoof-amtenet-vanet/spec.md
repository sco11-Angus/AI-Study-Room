# 三层反欺骗模型 Spec
git checkout taska# 三层反欺骗模型 Spec

## Why
当前反欺骗系统依赖纯信号处理（LBP纹理、FFT频谱、光流运动）和独立ONNX模型（Meso4/ViT/EfficientNet），各模块独立工作，缺乏端到端的深度学习特征融合。需要一个统一的三层神经网络架构：第一层提取操作痕迹、第二层解析频域秘密、第三层注意力聚焦，三者协同工作，整体提升对AI换脸、视频回放、打印照片等欺骗攻击的检测能力。

## What Changes
- 新增 `backend/app/detectors/antispoof_model.py` — 三层反欺骗模型定义与ONNX推理封装
- 新增 `backend/app/detectors/antispoof_model.py` 中的 `AMTENet` 模块（自适应操作痕迹提取网络）
- 新增 `backend/app/detectors/antispoof_model.py` 中的 `VANet` 模块（视觉伪影网络：空间+频域双分支）
- 新增 `backend/app/detectors/antispoof_model.py` 中的 `CBAM` 模块（卷积块注意力）
- 新增 `backend/app/detectors/antispoof_model.py` 中的 `AntiSpoofModel` 类（三层串联 + 分类头 + ONNX推理）
- 新增模型权重文件 `model_weights/antispoof_amtenet_vanet.onnx`
- 修改 `backend/app/detectors/liveness.py` — 在 `check()` 和 `evaluate()` 中集成新模型作为反欺骗主信号

## Impact
- Affected specs: add-deepfake-detection, fix-liveness-robustness, enhance-fourier-spectrum-antispoof
- Affected code:
  - `backend/app/detectors/antispoof_model.py` — 新增
  - `backend/app/detectors/liveness.py` — 集成新模型调用
  - `backend/model_weights/` — 新增 `.onnx` 权重文件

## ADDED Requirements

### Requirement: AMTENet — 自适应操作痕迹提取网络（第一层）
系统 SHALL 实现 AMTENet 模块，通过预测"干净"原始图像并与输入图像做差来提取操作痕迹。

AMTENet 结构：
- 一个编码器-解码器风格的网络，接收输入人脸图像 (C×H×W)，输出同尺寸的"预测干净图"
- 计算操作痕迹 `fmt = input - predicted_clean`
- 借鉴 DenseNet 的密集连接思想：每一层的输入和输出在通道维度拼接后传递到下一层，确保早期捕获的细微痕迹信息不会在深层被淹没
- 输出：操作痕迹特征图 `fmt`，作为 VANet 的输入

#### Scenario: AMTENet 提取操作痕迹
- **GIVEN** 一张被AI换脸修改过的人脸图像
- **WHEN** 通过 AMTENet 前向传播
- **THEN** 输出 `fmt` 特征图中，被修改区域（如面部中心）应有非零响应
- **AND** 真实人脸图像的 `fmt` 整体接近零

#### Scenario: 密集连接保留细微痕迹
- **GIVEN** AMTENet 的中间层
- **WHEN** 每一层处理特征
- **THEN** 该层的输入和输出沿通道维度拼接后作为下一层的输入
- **AND** 拼接操作确保早期捕捉的微弱痕迹信号不被后续层丢失

### Requirement: VANet — 视觉伪影网络（第二层）
系统 SHALL 实现 VANet 双分支结构，分别处理空间域和频域信息。

空间分支：
- 直接对输入图像/特征图做卷积处理，提取像素布局和画面内容特征

频域分支：
- 将输入图像通过 DCT（离散余弦变换）或 DFT（离散傅里叶变换）转换到频率域
- 在频域做卷积，捕获由生成算法或图像压缩引入的异常频率信号
- 将频域特征逆变换回空间域（或保持频域表示后通过1×1卷积投影到统一特征空间）

两分支特征在通道维度拼接后输出给 CBAM。

#### Scenario: 频域分支捕获GAN网格伪影
- **GIVEN** GAN生成的换脸图像中存在周期性网格伪影
- **WHEN** VANet 频域分支处理
- **THEN** DCT/DFT 变换后的频谱中出现异常高频峰值
- **AND** 频域卷积层能放大并捕获这些异常信号

#### Scenario: 空间分支处理像素布局
- **GIVEN** 任意人脸输入
- **WHEN** VANet 空间分支处理
- **THEN** 提取正常的空间纹理、边缘、色彩分布特征

### Requirement: CBAM — 卷积块注意力模块（第三层）
系统 SHALL 实现 CBAM（Convolutional Block Attention Module），对 VANet 输出的特征图进行通道注意力和空间注意力的双重聚焦。

CBAM 包含：
- 通道注意力子模块：通过全局平均池化和全局最大池化 + 共享MLP，输出通道权重向量
- 空间注意力子模块：沿通道做平均池化和最大池化 → 拼接 → 7×7卷积 → sigmoid，输出空间权重图
- 两个子模块串行：先通道注意力、后空间注意力

#### Scenario: CBAM 聚焦篡改关键区域
- **GIVEN** VANet 输出的融合特征图（包含操作痕迹 + 频域异常信号）
- **WHEN** CBAM 处理
- **THEN** 通道注意力加权增强与伪造检测相关的特征通道
- **AND** 空间注意力加权聚焦于面部中心等常见篡改区域
- **AND** 输出注意力增强后的特征图

### Requirement: 三层模型串联与分类
系统 SHALL 将 AMTENet → VANet → CBAM 三层串联，后接全局平均池化 + 全连接分类头（2分类：真人/欺骗），输出反欺骗分数。

#### Scenario: 端到端推理
- **GIVEN** 一张预处理后的人脸图像 (3×256×256)
- **WHEN** 通过完整 AntiSpoofModel 前向传播
- **THEN** 输出一个 [0, 1] 的实数分数，1.0=真人，0.0=欺骗
- **AND** 三层按 AMTENet → VANet → CBAM → GAP → FC 顺序串联

### Requirement: ONNX 模型推理集成
系统 SHALL 提供 `AntiSpoofDetector` 类封装 ONNX Runtime 推理，与现有 liveness.py 的 `LivenessDetector` 协同工作。

- 使用 onnxruntime 的 CPUExecutionProvider 进行推理
- 模型权重文件路径：`model_weights/antispoof_amtenet_vanet.onnx`
- 预处理：resize 至 256×256，BGR→RGB，归一化至 [0, 1]，转为 NCHW
- 支持延迟加载（首次调用时加载）和 session 缓存
- 单张图像推理输出 `(real_score, is_spoof)`

#### Scenario: 延迟加载ONNX模型
- **GIVEN** `AntiSpoofDetector` 实例化时模型文件存在
- **WHEN** 首次调用 `detect(face_crop)`
- **THEN** 自动加载 ONNX 模型并缓存 session
- **AND** 后续调用复用已缓存的 session

#### Scenario: 模型文件缺失时降级
- **GIVEN** `model_weights/antispoof_amtenet_vanet.onnx` 不存在
- **WHEN** 调用 `detect(face_crop)`
- **THEN** 返回中性分 0.5
- **AND** 记录 warning 日志

### Requirement: LivenessDetector 集成
系统 SHALL 在 `LivenessDetector.check()` 和 `evaluate()` 中集成 `AntiSpoofDetector` 输出，作为反欺骗主信号之一参与最终融合。

- `antiSpoofDetector` 在 `LivenessDetector` 中延迟初始化
- `antispoof_score` 作为新的信号参与被动分数融合
- `_make_details()` 中新增 `antispoof_score` 字段

#### Scenario: check() 中集成反欺骗分数
- **GIVEN** `AntiSpoofDetector` 已加载模型
- **WHEN** `LivenessDetector.check()` 被调用
- **THEN** 计算 `antispoof_score` 并参与被动信号融合
- **AND** `_make_details()` 返回中包含 `antispoof_score`

### Requirement: 模型训练与导出（PyTorch → ONNX）
系统 SHALL 提供 `backend/scripts/export_antispoof_onnx.py` 脚本，基于 PyTorch 定义 AMTENet + VANet + CBAM 完整模型，加载预训练权重，导出为 ONNX 格式。

- 模型架构在脚本中完整定义（不依赖外部 PyTorch 文件）
- 支持从 `.pth` 文件加载预训练权重
- ONNX 导出使用动态 batch size（或固定 batch=1）
- 输入 shape: (1, 3, 256, 256)，输出 shape: (1, 1)

#### Scenario: 从预训练权重导出ONNX
- **GIVEN** 存在 `model_weights/antispoof_amtenet_vanet.pth` 权重文件
- **WHEN** 运行 `python backend/scripts/export_antispoof_onnx.py`
- **THEN** 生成 `model_weights/antispoof_amtenet_vanet.onnx`
- **AND** 脚本输出模型参数量和导出确认信息
