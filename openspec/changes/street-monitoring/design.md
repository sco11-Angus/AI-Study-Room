# 设计说明：街道监控（street-monitoring）

## 背景与约束

- 复用已冻结的 `Detector` 接口（`setup()` + `detect(frame) -> list[AlarmEvent]`）与 `InferenceEngine` 调度，检测器内禁止自建线程/推理循环。
- 复用已存在的 `backend/model_weights/yolov8n.pt` 与已安装的 `ultralytics 8.4.92`，不下载新模型。
- 目标是「最基础可用」，用于沙盘技术验证演示，不追求跟踪、越线、事故判定等进阶能力。

## 关键设计决策

### 决策 1：计数走旁路通道，而非 AlarmEvent

现有检测器全部是「告警型」：`detect()` 产出 `AlarmEvent`，由 `AlarmService` 入库、抓拍、推送。但「当前画面有 5 辆车 3 个人」是**逐帧变化的连续状态**，不是偶发事件。若走告警管道会导致：每帧一条入库记录、前端告警栏被刷爆、抓拍目录爆炸。

因此 `StreetDetector.detect()` 始终返回 `[]`（不产告警），计数与检测框通过**独立旁路通道** `broadcast_street_stats()` → `/ws/street` 推送。这与项目已有的 `broadcast_face_boxes()` → `/ws/face_boxes` 模式完全一致（人脸框也是连续状态、不走告警）。

```
StreetDetector.detect(frame)
   │ YOLOv8n 推理一次
   ├── 聚合当前画面计数 {person, car, bus, truck, motorcycle, bicycle}
   ├── 归一化检测框 [{cls, x, y, w, h, conf}, ...]
   ├── broadcast_street_stats({counts, boxes})   ← 旁路推送
   └── return []                                  ← 不进告警中心
```

### 决策 2：类别白名单聚合

yolov8n 输出 COCO 80 类，只保留街道相关类别并聚合计数。白名单固定为：
`person, bicycle, car, motorcycle, bus, truck`（COCO 类 id 分别为 0,1,2,3,5,7）。
计数结构对前端稳定：即使某类为 0 也返回该键，前端计数卡片布局不跳动。

### 决策 3：坐标归一化，前端负责画框与平滑

检测器输出**归一化坐标**（相对 0~1），与视频显示分辨率解耦。前端拿到框后按当前 `<video>`/`<img>` 实际渲染尺寸换算像素并用 Canvas 叠加，沿用人脸框已验证的 requestAnimationFrame 平滑跟随套路，避免框相对画面漂移/抖动。

### 决策 4：显示与识别解耦，识别限定 4 路（核心算力决策）

12 路 RTSP 全部拉流显示，但 YOLO 识别只挂 4 路。原因：`InferenceEngine` 全局只有 2 个 worker，`dispatch_async` 在队列积压 >2 时直接丢帧。若 12 路都跑 YOLO，绝大多数推理帧会被背压丢弃，检测框严重卡顿，且和现有自习室检测器（入侵/烟火/疲劳/打架/人脸）抢占同一线程池。

```
显示链路（12 路，便宜）           识别链路（4 路，受控）
每路独立解码线程 → ring_buffer    每 SKIP_N 帧 → InferenceEngine(2 workers)
→ /ws/video_feed/<id> 推 JPEG     → StreetDetector.detect()（camera_ids 过滤）
不受推理池影响，稳定 15fps         只在 [2,3,9,11] 上执行，其余路直接跳过
```

`StreetDetector.camera_ids = [3, 2, 11, 9]`（行人、停车场出口、停车场入口、隧道车辆数量）。`InferenceEngine.dispatch()` 需按 `detector.camera_ids` 过滤：为 None 时所有摄像头都跑，否则只在列表内的 camera_id 上执行 —— 需确认引擎已支持该过滤，若未支持则在 `dispatch`/`detect` 层补一个 camera_id 判断（`Detector` 基类已声明 `camera_ids` 字段）。

沙盘 12 路通过现有 `STREAM_URLS`（`elif "://" in url` 分支已支持 RTSP）接入，camera_id 从 1 开始与清单序号对齐。

### 决策 5：前端网格复用单路组件

大屏采用 3×4 CSS Grid，每格是一个独立的视频单元（内部就是现有 `VideoStreamViewer` 的取流逻辑：`/ws/video_feed/<id>` + `<img>` 渲染）。识别路额外挂一个覆盖在 `<img>` 上的 `<canvas>`，订阅 `/ws/street` 后按 camera_id 分发框到对应格子绘制。

- 网格用 `grid-template-columns: repeat(4, 1fr)`，`gap` 留白，每格 `aspect-ratio` 固定，大屏下每格 ≥480px 宽。
- 响应式：容器窄于阈值时降为 `repeat(2, 1fr)`。
- 单格放大：点击某格切到单路大图模式（覆盖层或路由参数），再点返回网格。
- 12 条 `/ws/video_feed` 长连接：现有后端 `threaded=True` 可承载，但需注意浏览器对同域 WebSocket 并发数限制（现代浏览器足够 12 条）。

## 数据契约

`/ws/street` 推送的消息体：

```json
{
  "type": "street",
  "camera_id": 6,
  "ts": 1720900000.123,
  "counts": { "person": 3, "car": 5, "bus": 0, "truck": 1, "motorcycle": 0, "bicycle": 0 },
  "boxes": [
    { "cls": "car", "x": 0.42, "y": 0.55, "w": 0.10, "h": 0.08, "conf": 0.87 }
  ]
}
```

- `x,y` 为框中心归一化坐标，`w,h` 为归一化宽高（与 face_boxes 约定一致，便于前端复用）。
- 队列 `maxsize=2`，满则丢最旧，只推最新帧，避免慢客户端积压延迟。

## 性能考量

- 复用 `InferenceEngine` 的 `SKIP_N` 跳帧与背压丢帧机制，`StreetDetector` 只是新增一个串行检测器，和烟火/入侵等共享同一线程池（max_workers=2）。
- yolov8n 是最小模型，CPU 也可跑；推理耗时叠加在现有检测链路上，若沙盘验证时延迟偏高，可调大 `SKIP_N` 或将 `StreetDetector` 限定到沙盘单摄像头（`camera_ids`）。

## 隧道烟雾（复用，不新增）

隧道烟雾场景直接复用 `FireSmokePlugin`：在沙盘摄像头上配置一个烟火检测防区即可，烟雾告警仍走现有告警中心与看板。本变更不涉及烟火检测代码改动。事故检测不在范围内。
