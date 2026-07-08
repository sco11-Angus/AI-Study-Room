# Tasks

- [x] Task 1: 修复推流重连时 online 状态更新时序
  - [x] 1.1 在 `scheduler.py` 的 `_decode_loop` 重连分支中，`cap = cv2.VideoCapture(...)` 成功后立即置 `cs.online = cap.isOpened()`
  - [x] 1.2 重连成功添加 info 级别日志

- [x] Task 2: WebSocket 视频推送超时容错优化
  - [x] 2.1 将 `_MAX_RETRIES` 从 3 改为 2，`_FRAME_TIMEOUT` 保持 1.0s（总等待 2s）
  - [x] 2.2 移除重试循环内的"缓冲中"发送，仅在全部重试完毕后确认持续无帧才发 `{"status":"waiting"}`
  - [x] 2.3 超时期间静默等待，不发送任何 WS 消息，前端画面保持最后一帧

- [x] Task 3: Dashboard 人脸识别从轮询改为 WebSocket 推送
  - [x] 3.1 移除 `setInterval` + `/api/face_result` 的 500ms 轮询逻辑
  - [x] 3.2 改为连接 `/ws/face_recognition` WebSocket，收到消息直接更新 `faceResult`
  - [x] 3.3 添加 WebSocket 断线重连（3s 间隔）

- [x] Task 4: 前端 Canvas 渲染帧跳过 + 性能优化
  - [x] 4.1 用 `createImageBitmap` 替代 `new Image()` + `URL.createObjectURL`，减少内存分配
  - [x] 4.2 增加渲染锁/标志位：新帧到达时若上一帧仍在渲染，取消旧帧渲染，直接处理新帧
  - [x] 4.3 确保 `createImageBitmap` 不可用时回退到 `Image` + blob URL 方案

# Task Dependencies
- Task 1 和 Task 2 可并行（修改不同文件/不同逻辑）
- Task 3 独立于 Task 1-2
- Task 4 独立于 Task 1-3
- 所有 Task 之间无强依赖，可全并行实施
