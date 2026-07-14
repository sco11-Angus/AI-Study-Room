# 任务清单：街道监控（street-monitoring）

## 接入沙盘 12 路 RTSP

- [x] 1. 配置 12 路 RTSP 接入（预计 30min）
  - `.env` 的 `STREAM_URLS` 改为 12 条 `rtsp://10.126.59.120:8554/live/live1..live12`，camera_id 从 1 顺序编号（对齐清单序号）
  - 确认 `run.py` 的 `elif "://" in url` 分支正确接住 RTSP 地址
  - 确认 `STREAM_CAMERA_ID` 起始值使 12 路编号为 1~12（或在 run.py 明确指定）
  - 依赖：沙盘网络可达

## 后端：引擎按 camera_ids 过滤（关键前置）

- [x] 2. `InferenceEngine.dispatch()` 增加 `camera_ids` 过滤（预计 1h）
  - 现状：`dispatch()` 只判 `detector.enabled`，未按 `detector.camera_ids` 过滤
  - 改为：`camera_ids is None` 时所有摄像头都跑；否则仅当 `frame.camera_id in detector.camera_ids` 才调用 `detect()`
  - 保证其余 8 路非识别流不触发 YOLO 推理
  - 依赖：无（`Detector.camera_ids` 字段已存在）

## 后端：街道检测器

- [x] 3. 新建 `backend/app/detectors/street.py`，实现 `StreetDetector(Detector)`（预计 2h）
  - `name = "street"`，`camera_ids = [3, 2, 11, 9]`（行人/停车场出口/停车场入口/隧道车辆数量）
  - `setup()`：用 ultralytics `YOLO` 加载 `model_weights/yolov8n.pt`，路径解析参照 `FireSmokePlugin._resolve_weights_path()`
  - 定义白名单类别 `{0:person,1:bicycle,2:car,3:motorcycle,5:bus,7:truck}`
  - 依赖：任务 2（模型已存在）

- [x] 4. 实现 `StreetDetector.detect(frame)` 推理与聚合（预计 2h）
  - 对 `frame.image` 跑一次推理，过滤白名单类别
  - 聚合 `counts`（六类恒定返回键，缺省 0），构造归一化 `boxes`（中心点 `x,y` + `w,h` + `cls` + `conf`）
  - 调用 `broadcast_street_stats({camera_id, ts, counts, boxes})`
  - `return []`（不产告警）
  - 依赖：任务 3、任务 5

- [x] 5. `backend/app/api/ws.py` 新增 `/ws/street` 通道（预计 1h）
  - 新增 `street_stats_queue = queue.Queue(maxsize=8)` 与 `broadcast_street_stats(payload)`（满则丢最旧），照抄 `broadcast_face_boxes` 模式
  - 队列容量放宽到 8：4 路识别流并发推送，避免互相挤掉
  - 在 `register_ws_routes` 中新增 `@sock.route("/ws/street")`，照抄 `ws_face_boxes` 循环，前端按 `camera_id` 分发
  - 依赖：无

- [x] 6. `backend/run.py::start_services()` 注册检测器（预计 15min）
  - `from app.detectors.street import StreetDetector`
  - `engine.register(StreetDetector())`（在 `setup_all()` 之前）
  - 依赖：任务 3

## 前端：多屏网格大屏

- [x] 7. 新建 `frontend/src/views/StreetMonitor.vue` — 3×4 网格骨架（预计 2h）
  - 12 格 CSS Grid（`repeat(4, 1fr)`，gap 留白，每格固定 `aspect-ratio`，大屏 ≥480px 宽）
  - 每格显示场景标题（桥面/停车场出口/…）+ 视频单元
  - 响应式：窄屏降为 2 列
  - 依赖：任务 1

- [x] 8. 抽取单路视频单元组件并接入 12 路（预计 2h）
  - 将 `VideoStreamViewer` 的取流逻辑（`/ws/video_feed/<id>` + `<img>` + 重连）抽为可复用组件，接受 `cameraId` prop
  - 网格 12 格各连一路
  - 依赖：任务 7

- [x] 9. 识别路叠加检测框 + 计数徽标（预计 3h）
  - 连接 `/ws/street`，按 `camera_id` 分发到对应格子
  - 识别格（2/3/9/11）在 `<img>` 上叠加 `<canvas>`，按当前渲染尺寸换算像素画框，rAF 平滑跟随（复用人脸框套路）
  - 格子角标显示计数徽标（👤人 / 🚗车）
  - 依赖：任务 5、任务 8

- [x] 10. 单格放大单看（预计 1h）
  - 点击某格切换到单路大图模式，再点返回网格
  - 依赖：任务 8

- [x] 11. `frontend/src/router/index.js` 新增 `/street` 路由（预计 10min）
  - `{ path: '/street', component: () => import('../views/StreetMonitor.vue') }`
  - 依赖：任务 7

- [x] 12. `frontend/src/App.vue` 左侧菜单新增「街道监控」入口（预计 15min）
  - 在 `/stream`（实时视频流）条目下方新增 `el-menu-item index="/street"`，图标 🚦
  - 依赖：任务 11

## 隧道烟雾（复用，无代码）

- [ ] 13. 在沙盘隧道摄像头（live8/live9）配置烟火检测防区，验证 `FireSmokePlugin` 告警链路（预计 30min）
  - 通过现有防区配置页操作，无需改代码
  - 依赖：任务 1

## 车牌识别（已评估放弃）

- [x] 15. 停车场车牌识别 —— 已评估放弃，代码已回退
  - 实测沙盘车离摄像头远（车辆检测框约 210×150px），车牌区域太小；沙盘车牌为非标准格式
  - hyperlpr3 在原图 / 整车裁剪 / 放大 2~6 倍下均返回空，无法识别
  - 结论：车牌识别不纳入本能力，`StreetDetector` 回退为纯车辆计数；已移除 hyperlpr3 依赖与前端车牌显示
  - 保留：检测框 rAF 平滑跟随（车框跟随移动车辆）

## 验证

- [ ] 14. 联调验证（预计 1.5h）
  - 12 路视频流全部在网格中显示，画面稳定（显示链路不受推理影响）
  - `/ws/street` 仅 4 路（2/3/9/11）有数据，计数与画框正确
  - 确认 8 路非识别流未触发 YOLO 推理（引擎 camera_ids 过滤生效）
  - 空场景计数归零、非白名单类别被忽略
  - 隧道烟雾能触发既有 `fire_smoke` 告警
  - 确认街道计数未产生 `AlarmEvent`、未刷屏告警栏
  - 单格放大/返回正常
  - 依赖：任务 1-13
