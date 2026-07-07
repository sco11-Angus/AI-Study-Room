# 视频流前端显示修复 Spec

## Why
当前视频流前端使用 MJPEG (`multipart/x-mixed-replace`) + `<img>` 标签方案，浏览器兼容性差（Chrome/Edge 对 MJPEG 处理不一致），且 `video_feed.py` 独立拉一份 RTMP 流导致带宽翻倍。实际表现为前端无法正常显示画面、频繁掉帧。

## What Changes
- **废弃** `video_feed.py` 的 MJPEG 推流方式，改为 WebSocket 逐帧推送
- 新增 `/ws/video_feed/<camera_id>` WebSocket 端点，从 StreamScheduler 的 ring_buffer 取已解码帧直接推送
- 前端 `VideoStreamViewer.vue` 从 `<img>` + MJPEG 改为 `<canvas>` + WebSocket 渲染
- 删除冗余的 `video_feed.py` 独立 RTMP 拉流连接，**显示和推理共用一份流**

## Impact
- Affected specs: 视频流显示、A3 调度器
- Affected code:
  - `backend/app/api/video_feed.py` — 重写为 WebSocket 端点
  - `backend/app/stream/scheduler.py` — 暴露 ring_buffer 最高帧到共享内存
  - `frontend/src/views/VideoStreamViewer.vue` — `<img>` → `<canvas>` + WebSocket
  - `frontend/src/components/VideoPlayer.vue` — 保持不变（flv.js 方案后续启用）

## ADDED Requirements
### Requirement: 实时视频流通过 WebSocket + Canvas 渲染
系统 SHALL 通过 WebSocket 将 StreamScheduler ring_buffer 中已解码的帧推送到前端，前端使用 `<canvas>` 逐帧渲染，不再使用 MJPEG + `<img>` 标签。

#### Scenario: 前端成功显示实时画面
- **GIVEN** StreamScheduler 已启动并成功拉流
- **WHEN** 前端连接 `/ws/video_feed/<camera_id>`
- **THEN** 前端 `<canvas>` 逐帧显示视频画面，无明显延迟(<2s)和掉帧

#### Scenario: 断流自动恢复
- **GIVEN** RTMP 推流中断
- **WHEN** 推流恢复
- **THEN** 前端自动恢复画面显示，无需手动刷新

#### Scenario: 多路摄像头同时观看
- **WHEN** 前端同时连接多个 camera_id 的 WebSocket
- **THEN** 每个连接独立推送对应摄像头的最新帧

## MODIFIED Requirements
### Requirement: 视频拉流（原 video_feed.py）
原 MJPEG 端点 `/video_feed/<stream_id>` 废弃，替换为 WebSocket 端点 `/ws/video_feed/<camera_id>`。不再独立拉 RTMP 流，改为从 StreamScheduler 的 ring_buffer 复用已解码帧。

## REMOVED Requirements
### Requirement: MJPEG 视频流（原 video_feed.py）
**Reason**: `<img>` + MJPEG 方案浏览器兼容性差，且造成额外的 RTMP 连接开销。
**Migration**: 前端改用 WebSocket + `<canvas>`，后端 `/video_feed/<stream_id>` 路由移除。
