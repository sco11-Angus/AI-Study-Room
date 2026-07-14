## Why

实训评分项要求「使用沙盘设备对监测系统做技术验证」（可选，6 分）：沙盘设备提供摄像头视频流，可对算法模型做验证测试，覆盖隧道（烟雾/事故）、停车场（出入/数量）、车辆/行人识别（类型/检测）等街道场景。

当前系统的检测能力全部面向自习室业务（入侵、烟火、疲劳、打架、人脸），没有面向街道/交通场景的识别能力，也没有承载这类结果的前端页面。本次变更以「最基础可用」为目标，接入沙盘视频流做车辆/行人识别与当前画面计数，并复用已有烟火检测覆盖隧道烟雾，产出一块独立的街道监控大屏用于技术验证演示。

## What Changes

- **接入沙盘 12 路 RTSP 视频流**：沙盘设备提供 12 路 RTSP 流（`rtsp://10.126.59.120:8554/live/live1..live12`，见 `沙盘_rtsp_streams.md`），覆盖桥面、停车场出入口、行人检测、消防车、隧道（事故/车辆数量）、多条道路等场景。12 路 **全部拉流显示**，camera_id 采用 1~12 与清单序号对齐。scheduler 已默认 `rtsp_transport;tcp`，通过现有 `STREAM_URLS`（含 `://` 分支）或数据库摄像头机制接入，无需改调度器。
- **显示与识别解耦（关键算力决策）**：12 路显示走独立拉流线程 + ring_buffer，成本低；YOLO 识别只挂在 **4 路**上，避免 12 路同时推理打爆全局 2-worker 推理池。识别路：`live3 行人检测`、`live2 停车场出口`、`live11 停车场入口`、`live9 隧道车辆数量`。其余 8 路只显示不跑模型。
- **新增 `StreetDetector` 检测器（限定 camera_ids）**：继承现有 `Detector` 接口，加载仓库已存在的 `backend/model_weights/yolov8n.pt`（COCO 80 类，含 person/car/bus/truck/motorcycle/bicycle），设置 `camera_ids=[3,2,11,9]` 只在识别路执行推理，按类别聚合**当前画面计数**并输出归一化检测框。
- **计数走旁路通道，不进告警中心**：当前画面计数是逐帧变化的连续状态，若走 `AlarmEvent → AlarmService` 会导致每帧入库与前端告警栏刷屏。参照现有 `broadcast_face_boxes` 模式，新增 `broadcast_street_stats()` 与独立 WebSocket 通道 `/ws/street` 推送 `{camera_id, counts, boxes}`。`StreetDetector.detect()` 返回空告警列表。
- **隧道烟雾复用现有能力**：不新增烟雾/事故检测代码。隧道烟雾由已有 `FireSmokePlugin` 承担，仅需在沙盘隧道摄像头（live8/live9）上配置烟火防区，告警仍走现有告警中心。
- **新增街道监控大屏页面（多屏网格）**：新建 `frontend/src/views/StreetMonitor.vue`，采用 **3×4 网格**铺满 12 路视频流，每格显示视频（复用现有 `/ws/video_feed/<id>` 单路组件）+ 场景标题；识别路（4 路）额外叠加 Canvas 检测框（复用 face_boxes 的 rAF 平滑跟随套路）与计数徽标。每格尺寸足够大（大屏下约 ≥480px 宽，非缩略图），窗口变窄时自适应降为 2 列。支持点击单格放大单看。左侧导航栏在「实时视频流」下新增「街道监控」入口，新增 `/street` 路由。

## 明确不做（守住「基础可用」范围）

- ❌ 越线累计车流统计（需要目标跟踪 track ID，超出基础范围）— 只做当前画面计数。
- ❌ 停车场出入进出统计（同样需要跟踪）— 停车场只做当前车辆数量。
- ❌ 事故检测模型 —— 通用 YOLO 无法判定碰撞/异常事件，不训练也不接入专用模型。
- ❌ 训练或微调模型 —— 纯用现成 yolov8n COCO 权重。

## Capabilities

### New Capabilities

- `street-monitoring`: 沙盘街道场景车辆/行人当前画面计数与检测框推送，独立监控大屏展示。

## Impact

| 影响面 | 说明 |
|--------|------|
| `.env` / `STREAM_URLS` | 接入 12 路 RTSP（camera_id 1~12），替换现有单路 `test1` |
| `backend/app/detectors/street.py` | **新文件**：`StreetDetector(Detector)`，`camera_ids=[3,2,11,9]`，加载 yolov8n，逐帧计数 + 归一化框，经旁路通道推送 |
| `backend/app/api/ws.py` | 新增 `broadcast_street_stats()` 与 `/ws/street` WebSocket 通道（照抄 `/ws/face_boxes` 模式，payload 带 camera_id） |
| `backend/run.py` | `start_services()` 增加 `engine.register(StreetDetector())` |
| `frontend/src/views/StreetMonitor.vue` | **新文件**：街道监控大屏（3×4 网格 12 路视频 + 4 路检测框/计数徽标 + 单格放大） |
| `frontend/src/router/index.js` | 新增 `/street` 路由 |
| `frontend/src/App.vue` | 左侧菜单新增「街道监控」入口 |
| 隧道烟雾 | 复用现有 `FireSmokePlugin`，无代码改动，仅需在沙盘隧道摄像头配置烟火防区 |

## 场景与 camera_id 映射

| camera_id | RTSP | 场景 | 显示 | YOLO 识别 |
|---:|---|---|:---:|:---:|
| 1 | live1 | 桥面 | ✓ | — |
| 2 | live2 | 停车场出口 | ✓ | ✓ 车辆计数 |
| 3 | live3 | 行人检测 | ✓ | ✓ 行人计数 |
| 4 | live4 | 消防车识别 | ✓ | — |
| 5 | live5 | 桥出口 | ✓ | — |
| 6 | live6 | 桥入口 | ✓ | — |
| 7 | live7 | 道路2 | ✓ | — |
| 8 | live8 | 隧道（事故识别） | ✓ | — |
| 9 | live9 | 隧道（车辆数量） | ✓ | ✓ 车辆计数 |
| 10 | live10 | 道路3 | ✓ | — |
| 11 | live11 | 停车场入口 | ✓ | ✓ 车辆计数 |
| 12 | live12 | 道路1 | ✓ | — |

## 安全说明

新增的 `/ws/street` 通道与现有 `/ws/face_boxes`、`/ws/alarms` 保持一致，均为无鉴权的开放通道，仅用于沙盘技术验证与内网演示。若后续需对外部署，应统一为所有 WebSocket 通道补充鉴权，不在本次范围内单独处理。
