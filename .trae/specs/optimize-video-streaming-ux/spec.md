# 视频流播放体验优化 Spec

## Why
当前视频流前端播放存在四个交互问题：(1) "缓冲中"提示频繁出现，解码器短暂卡顿就触发；(2) 推流重连期间前端一直显示"等待推流"，与后端实际状态脱节；(3) 人脸识别结果前端用轮询而非 WebSocket 推送，延迟高；(4) 前端渲染管道无背压控制，帧堆积导致卡顿。

## What Changes
- WebSocket 端点增加帧 backlog 容错：短暂无帧不立即发送"缓冲中"，只在持续无帧 >2s 后才通知前端
- 修复重连期间 `cs.online` 状态更新时序：`VideoCapture` 打开成功立即设置 `online=True`
- Dashboard 人脸识别从 500ms 轮询改为 WebSocket 实时推送
- 前端 Canvas 渲染增加帧跳过机制：队列积压时丢弃旧帧，只渲染最新帧
- 前端渲染管线优化：用 `createImageBitmap` 替代 `Image` + `createObjectURL`，减少内存分配

## Impact
- Affected specs: 视频流显示，人脸识别端到端
- Affected code:
  - `backend/app/api/video_feed.py` — 调整等待/超时逻辑
  - `backend/app/stream/scheduler.py` — 修复重连 online 时序
  - `frontend/src/views/VideoStreamViewer.vue` — Canvas 渲染优化 + 帧跳过
  - `frontend/src/views/Dashboard.vue` — 轮询改 WebSocket

## MODIFIED Requirements

### Requirement: WebSocket 视频帧推送超时容错
系统 SHALL 在短暂无帧时不立即通知前端，仅在持续无新帧超过 2 秒后才发送"缓冲中"；期间静默等待，前端画面保持最后一帧不变。

#### Scenario: 短暂解码卡顿不触发缓冲提示
- **GIVEN** 解码器因 H.264 复杂帧短暂卡顿 1.5 秒
- **WHEN** `wait_frame()` 连续超时
- **THEN** 后端不发送 `{"status":"waiting"}`，前端不显示"缓冲中"，画面停在最后一帧

#### Scenario: 持续无帧超过 2 秒触发缓冲提示
- **GIVEN** 解码器卡顿超过 2 秒
- **WHEN** `wait_frame()` 累计超时超过 2 秒
- **THEN** 后端发送 `{"status":"waiting"}`，前端显示"缓冲中"

### Requirement: 推流重连状态即时更新
系统 SHALL 在重连成功时立即将 `cs.online` 置为 `True`，而非等待下一帧成功读取。

#### Scenario: 重连后前端立即显示画面
- **GIVEN** RTMP 推流中断后恢复
- **WHEN** `VideoCapture` 重新打开成功（`cap.isOpened()` 返回 True）
- **THEN** `cs.online` 立即设为 True，WebSocket 不再发送 `{"status":"offline"}`，前端"等待推流"遮罩立即消失

### Requirement: 人脸识别结果实时推送
Dashboard SHALL 使用 WebSocket（`/ws/face_recognition`）接收人脸识别结果，不再使用 500ms HTTP 轮询。

#### Scenario: 人脸识别结果实时展示
- **GIVEN** 前端已连接 `/ws/face_recognition`
- **WHEN** 后端 FaceDetector 完成一次识别匹配
- **THEN** 前端在 200ms 内更新 `faceResult` 并显示对应横幅

### Requirement: 前端 Canvas 渲染帧跳过
前端 SHALL 在渲染管道积压时跳过旧帧，仅渲染最新到达的帧，避免画面延迟累积。

#### Scenario: 高频帧到达时丢弃旧帧
- **GIVEN** WebSocket 以 30fps 推送帧，但浏览器渲染能力有限
- **WHEN** 前一帧仍在渲染中，新帧到达
- **THEN** 跳过前一帧的渲染回调，直接渲染最新帧

#### Scenario: 正常帧率下不丢帧
- **GIVEN** WebSocket 以 15fps 推送帧
- **WHEN** 浏览器渲染能力充足
- **THEN** 每一帧都被渲染，无跳过
