# Tasks

- [x] Task 1: 优化 FFmpeg 解码参数消除 H.264 卡顿
  - [x] 1.1 添加 `threads;1` 单线程解码，消除 MBAFF 多线程竞争
  - [x] 1.2 添加 `skip_loop_filter;all` 跳过环路滤波，减少解码复杂度
  - [x] 1.3 在解码循环中添加 `decode_dropped` 计数和日志

- [x] Task 2: WebSocket 端点超时重试
  - [x] 2.1 `wait_frame()` 超时后最多重试 3 次（每次 1s），确认真正卡顿才发"缓冲中"
  - [x] 2.2 重试期间不发送任何 WS 消息，避免触发前端状态切换

- [x] Task 3: 验证
  - [x] 3.1 跑 latency_test 确认帧率和错误数
  - [x] 3.2 确认终端不再输出大量 H.264 错误

# Task Dependencies
- Task 2 可独立于 Task 1 实施
- Task 3 依赖 Task 1 和 Task 2
