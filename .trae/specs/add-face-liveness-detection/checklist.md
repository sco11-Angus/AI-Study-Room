# Checklist: 人脸活体检测 Anti-Spoofing

- [x] `LivenessDetector` 类存在于 `app/detectors/liveness.py`
- [x] 眨眼检测使用 dlib 68 点 landmarks 计算 EAR，并缓存历史值
- [x] 微动分析基于相邻帧面部区域光流计算平均运动量
- [x] 纹理分析基于人脸区域 LBP 直方图熵值判别
- [x] 融合判决函数输出 [0, 1] 活体分数，加权策略正确
- [x] `FaceDetector.detect()` 中先执行活体检测再执行匹配
- [x] 活体失败时产出 `AlarmEvent(type="face_spoof")` 且不执行匹配
- [x] `Config` 中新增 `LIVENESS_ENABLED`、`LIVENESS_THRESHOLD`、`LIVENESS_HISTORY_SIZE`、`LIVENESS_EAR_BLINK_THRESH`
- [x] `.env.example` 包含活体检测相关环境变量
- [x] `LIVENESS_ENABLED=false` 时活体检测被完全跳过
- [x] WebSocket 支持 `face_spoof` 消息类型，含 `confidence` 和 `reasons`
- [x] 单元测试覆盖眨眼、微动、纹理、融合判决四个子模块
- [x] 单元测试覆盖 FaceDetector 集成（活体通过/失败两种路径）
- [x] 现有 `test_face.py` 测试不受影响（向后兼容）
