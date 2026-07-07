# 修复 H.264 解码卡顿导致掉帧 Spec

## Why
RTMP 流中的 H.264 编码存在 MBAFF (field coding) 和 MMCO 错误，导致 FFmpeg 解码器内部卡住、停止产出帧。前端 WebSocket 端点 `wait_frame()` 超时后发"缓冲中"，每次卡顿丢失大量帧。

## What Changes
- 升级 FFmpeg 解码参数：单线程解码 + 跳过环路滤波，消除 H.264 复杂特性导致的解码停滞
- WebSocket 端点超时重试机制：`wait_frame()` 超时后最多重试 3 次再发"缓冲中"
- 解码循环增加 frame drop 计数日志，方便监控

## Impact
- Affected specs: 视频流显示
- Affected code:
  - `backend/app/stream/scheduler.py` — FFmpeg 参数 + 解码计数日志
  - `backend/app/api/video_feed.py` — 超时重试逻辑

## MODIFIED Requirements
### Requirement: H.264 解码容错
系统 SHALL 使用单线程解码并跳过环路滤波，避免 MBAFF/MMCO 错误导致解码器内部卡顿。`wait_frame()` 超时后重试最多 3 次再通知前端"缓冲中"。

#### Scenario: H.264 解码错误不中断流
- **GIVEN** RTMP 流包含 MBAFF 编码帧
- **WHEN** 解码器遇到 "co located POCs unavailable" 错误
- **THEN** 解码继续，不中断，帧正常产出

#### Scenario: 短暂卡顿不触发"缓冲中"
- **GIVEN** 解码器短暂卡顿 < 3s
- **WHEN** `wait_frame()` 超时
- **THEN** 自动重试，不发送 "waiting" 到前端，前端不显示"缓冲中"
