# Tasks

- [x] Task 1: StreamScheduler 暴露帧缓冲区供外部读取
  - [x] 1.1 在 `CameraStream` 中增加 `_lock` 保证线程安全读取
  - [x] 1.2 将 `latest_frame()` 返回值改为 JPEG 编码后的 bytes（减少 WebSocket 传输量）
  - [x] 1.3 在 `_decode_loop` 中，每帧解码后编码为 JPEG 存入 `ring_buffer`（替代裸 numpy 数组）

- [x] Task 2: 新增 WebSocket 视频流端点
  - [x] 2.1 在 `backend/app/api/video_feed.py` 中创建 WebSocket endpoint `/ws/video_feed/<camera_id>`
  - [x] 2.2 WebSocket 连接后，以固定间隔（33ms/30fps）从 StreamScheduler 取最新帧并推送
  - [x] 2.3 断流时推送占位消息（JSON `{"status": "offline"}`），前端显示"等待推流"

- [x] Task 3: 前端改用 Canvas + WebSocket 渲染
  - [x] 3.1 修改 `VideoStreamViewer.vue`，用 `<canvas>` 替换 `<img>`
  - [x] 3.2 实现 WebSocket 连接逻辑：连接、收帧、渲染到 canvas、断线重连
  - [x] 3.3 添加离线状态提示 UI

- [x] Task 4: 清理旧代码
  - [x] 4.1 移除 `video_feed.py` 中原 MJPEG 的 HTTP 路由 `/video_feed/<stream_id>`
  - [x] 4.2 移除 `VideoStreamViewer.vue` 中旧的 MJPEG URL 相关代码

- [x] Task 5: 端到端验证
  - [x] 5.1 确认 WebSocket 端点已注册（`__init__.py` 中 `sock.init_app` + `register_ws_routes`）
  - [x] 5.2 确认 frontend canvas 渲染逻辑完整（WebSocket Blob → Image → Canvas）
  - [x] 5.3 确认断流/恢复逻辑（离线提示 + 3s 自动重连）

# Task Dependencies
- Task 2 依赖 Task 1（WebSocket 需要从 StreamScheduler 取帧）
- Task 3 依赖 Task 2（前端需要 WebSocket 端点就绪）
- Task 4 可与 Task 3 并行
- Task 5 依赖所有前序任务
