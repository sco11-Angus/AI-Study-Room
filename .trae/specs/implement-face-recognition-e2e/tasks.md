# Tasks

- [x] Task 1: 实现 FaceDetector 检测器
  - [x] 在 `backend/app/detectors/face.py` 中新增 `FaceDetector` 类，继承 `Detector`
  - [x] `setup()` 中初始化 dlib 检测器和 FaceMatcher
  - [x] `detect()` 中：对帧进行人脸检测 → 裁剪人脸区域 → encode 提取特征 → match 匹配会员 → 构造 AlarmEvent
  - [x] AlarmEvent 的 `type` 设为 `"face_recognition"`，`extra` 携带 `face_match` 和 `name`
  - [x] 无脸帧返回空列表，不做无效推理

- [x] Task 2: 实现 WebSocket 人脸识别推送通道
  - [x] 在 `backend/app/api/ws.py` 中实现 `/ws/face_recognition` WebSocket 端点
  - [x] 使用 `queue.Queue` 作为广播通道，AlarmService 写入，WS 端点读取推送
  - [x] 完善 `backend/app/services/alarm.py` 的 `raise_alarm()`：识别到人脸时将结果写入广播队列（不触发钉钉）
  - [x] 消息格式: `{"type": "member", "member_id": 1, "name": "张三"}` 或 `{"type": "stranger"}`

- [x] Task 3: 前端人脸识别结果展示
  - [x] 在 `frontend/src/views/Dashboard.vue` 中新增 WebSocket 连接 `/ws/face_recognition`
  - [x] 添加响应式状态 `faceResult` 存储最新识别结果
  - [x] 会员匹配时显示"欢迎你, XXX"（绿色提示横幅）
  - [x] 陌生人时显示"陌生人"（灰色提示）
  - [x] 结果变化时平滑过渡，无结果时隐藏

- [x] Task 4: 注册 FaceDetector 到推理引擎
  - [x] 在 `backend/run.py` 中创建 `FaceDetector` 实例并注册到 `InferenceEngine`
  - [x] 在 `dispatch_and_raise` 中处理 `type="face_recognition"` 的事件（走人脸推送通道，不走告警入库）

- [x] Task 5: 端到端测试验证
  - [x] 在 `backend/tests/` 新增 E2E 测试，模拟推流视频帧 → FaceDetector 检测 → 断言返回正确的 face_match
  - [x] 测试包含：会员匹配成功、陌生人、无人脸三种场景
  - [x] 运行测试确保全部通过（10/10 passed）

# Task Dependencies
- Task 2 依赖 Task 1（需要 FaceDetector 产出 AlarmEvent 才能推送）
- Task 3 依赖 Task 2（需要 WebSocket 端点才能连接）
- Task 4 依赖 Task 1（需要 FaceDetector 才能注册）
- Task 5 依赖 Task 1-4（E2E 测试需完整链路）
- Task 3 和 Task 4 可并行（不互相依赖）
