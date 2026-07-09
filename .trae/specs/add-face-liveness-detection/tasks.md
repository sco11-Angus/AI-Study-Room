# Tasks

- [x] Task 1: 实现 LivenessDetector 核心类
  - [x] 新增 `app/detectors/liveness.py`，实现 `LivenessDetector` 类
  - [x] 实现 **眨眼检测**：基于 dlib 68 点 landmarks 计算 EAR，缓存历史值检测眨眼事件
  - [x] 实现 **微动分析**：基于相邻帧面部区域的光流幅值，计算平均运动量
  - [x] 实现 **纹理分析**：计算人脸区域的 LBP 直方图，与正常/翻拍纹理分布做比对（使用 LBP 方差作为简易判别指标）
  - [x] 实现 **融合判决**：加权融合三个信号输出 [0, 1] 活体分数
  - [x] 加权策略：EAR 眨眼权重 0.4 / 光流微动权重 0.35 / 纹理权重 0.25

- [x] Task 2: 在 FaceDetector 中集成活体检测
  - [x] 修改 `app/detectors/face.py` 的 `FaceDetector.__init__()`，接收 liveness 配置
  - [x] 修改 `FaceDetector.detect()`，在人脸检测后、匹配前插入活体检测
  - [x] 活体失败时生成 `AlarmEvent(type="face_spoof", ...)`，跳过匹配
  - [x] 维护人脸裁剪历史队列（`deque`），供微动分析和眨眼检测使用

- [x] Task 3: 新增配置项
  - [x] 在 `app/config.py` 的 `Config` 类中新增 `LIVENESS_ENABLED`, `LIVENESS_THRESHOLD`, `LIVENESS_HISTORY_SIZE`, `LIVENESS_EAR_BLINK_THRESH`
  - [x] 在 `.env.example` 中添加对应环境变量注释

- [x] Task 4: WebSocket 支持 face_spoof 消息
  - [x] 在 `app/api/ws.py` 中新增 `broadcast_face_result()` 函数，同时更新最新结果并推入 WebSocket 队列
  - [x] 确保 `face_spoof` 消息结构与 spec 一致（含 confidence 和 reasons）

- [x] Task 5: 单元测试
  - [x] 新增 `tests/test_liveness.py`（14 passed, 6 skipped — 缺少 mysql 驱动）
  - [x] 测试眨眼检测（模拟 EAR 变化序列：真实 vs 静态）
  - [x] 测试微动分析（模拟有微动 vs 静止的光流）
  - [x] 测试纹理分析（正常纹理 vs 异常纹理的 LBP 差异）
  - [x] 测试融合判决（真实/攻击场景的分数输出）
  - [x] 测试 FaceDetector 集成：活体通过走匹配、活体失败产 face_spoof

# Task Dependencies
- Task 2 依赖 Task 1
- Task 4 依赖 Task 2
- Task 5 依赖 Task 1 和 Task 2
- Task 3 独立，可与 Task 1 并行
