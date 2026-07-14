## ADDED Requirements

### Requirement: 沙盘 12 路视频流接入与显示
系统 SHALL 接入沙盘设备的 12 路 RTSP 视频流（`rtsp://10.126.59.120:8554/live/live1..live12`），camera_id 与清单序号 1~12 对齐，全部拉流并可在街道监控大屏中显示。显示链路 SHALL 独立于推理链路（走 ring_buffer 与 `/ws/video_feed/<id>`），不受 YOLO 推理背压影响。

#### Scenario: 12 路全部显示
- **GIVEN** 沙盘 12 路 RTSP 均可达
- **WHEN** 用户打开街道监控大屏
- **THEN** 网格中 12 格分别显示 live1~live12 的实时画面与场景标题

#### Scenario: 某路断流不影响其他路
- **GIVEN** 12 路正在显示
- **WHEN** 其中一路 RTSP 断流
- **THEN** 该格显示离线/等待状态，其余 11 路显示不受影响

### Requirement: 街道场景当前画面计数（限定识别路）
系统 SHALL 仅在指定的识别路（`live3 行人检测`、`live2 停车场出口`、`live11 停车场入口`、`live9 隧道车辆数量`，对应 camera_id 3/2/11/9）上对推理帧执行 YOLOv8n 推理，识别街道相关类别（`person`、`bicycle`、`car`、`motorcycle`、`bus`、`truck`），聚合出**当前画面**各类别的目标数量，并通过独立 WebSocket 通道 `/ws/street` 推送计数结果（含 `camera_id`）。计数为逐帧连续状态，SHALL NOT 产生 `AlarmEvent`，不进入告警中心。

非识别路（其余 8 路）SHALL NOT 触发 YOLO 推理，由推理引擎按 `camera_ids` 过滤保证。

#### Scenario: 非识别路不跑推理
- **GIVEN** `StreetDetector.camera_ids = [3,2,11,9]`
- **WHEN** camera_id=1（桥面）的推理帧被派发
- **THEN** `StreetDetector.detect()` 不被调用，不产生 `/ws/street` 消息

计数结构 SHALL 对全部六个白名单类别恒定返回键，某类目标数为 0 时返回 0，保证前端计数面板布局稳定。

#### Scenario: 画面中存在车辆与行人
- **GIVEN** 沙盘街道摄像头在线且 `StreetDetector` 已启用
- **WHEN** 某推理帧中出现 5 辆小汽车、1 辆卡车、3 个行人
- **THEN** `/ws/street` 推送 `counts` 中 `car=5`、`truck=1`、`person=3`，其余白名单类别为 0
- **AND** 该帧不产生任何 `AlarmEvent`

#### Scenario: 空场景
- **GIVEN** 沙盘街道摄像头在线且 `StreetDetector` 已启用
- **WHEN** 某推理帧中无任何白名单类别目标
- **THEN** `/ws/street` 推送的 `counts` 六个白名单类别键均为 0

#### Scenario: 非街道类别被忽略
- **GIVEN** 画面中出现不在白名单内的 COCO 类别（如 `chair`、`dog`）
- **WHEN** 执行推理并聚合计数
- **THEN** 这些类别不计入 `counts`，不出现在 `boxes` 中

### Requirement: 归一化检测框推送
系统 SHALL 随计数一并推送本帧所有白名单目标的检测框，坐标以归一化形式（中心点 `x,y` 与宽高 `w,h`，取值范围 0~1）表示，附带类别名 `cls` 与置信度 `conf`，使前端可按实际渲染尺寸换算像素并叠加绘制。检测框通道 SHALL 采用有界队列（只保留最新帧），慢客户端不得导致积压延迟。

#### Scenario: 检测框随计数同帧推送
- **WHEN** 某推理帧识别到 2 个目标
- **THEN** `/ws/street` 同一消息的 `boxes` 数组含 2 个元素，每个元素包含 `cls`、`x`、`y`、`w`、`h`、`conf`
- **AND** 所有 `x,y,w,h` 取值在 0~1 之间

#### Scenario: 慢客户端不积压
- **GIVEN** 一个消费缓慢的 `/ws/street` 客户端
- **WHEN** 后端持续产出新帧且队列已满
- **THEN** 丢弃最旧帧只保留最新帧，客户端收到的始终是最近状态而非陈旧积压帧

### Requirement: 街道监控多屏网格大屏
系统 SHALL 提供独立的街道监控大屏页面（路由 `/street`），以 3×4 网格铺满 12 路视频流，每格显示视频画面与场景标题，每格尺寸足够大（大屏下每格 ≥480px 宽，非缩略图），窗口变窄时自适应降为 2 列。识别路（4 路）SHALL 在视频上叠加检测框并显示计数徽标。左侧全局导航栏 SHALL 在「实时视频流」条目下方新增「街道监控」入口。

#### Scenario: 从导航进入街道监控页
- **GIVEN** 用户在系统任意页面
- **WHEN** 点击左侧导航栏的「街道监控」入口
- **THEN** 跳转到 `/street` 路由并展示 12 路网格大屏

#### Scenario: 计数徽标实时更新
- **GIVEN** 用户停留在街道监控页且 `/ws/street` 已连接
- **WHEN** 后端推送某识别路新的 `counts`
- **THEN** 对应格子的计数徽标实时更新（如 👤人:5 / 🚗车:8）

#### Scenario: 检测框叠加视频
- **GIVEN** 识别路格子视频正常显示
- **WHEN** 收到该 camera_id 的 `boxes` 数据
- **THEN** 在该格视频画面上按当前渲染尺寸叠加绘制检测框，框随画面平滑跟随

#### Scenario: 单格放大单看
- **GIVEN** 用户在 12 路网格视图
- **WHEN** 点击某一格
- **THEN** 该路切换为单路大图显示，再次操作可返回网格

#### Scenario: 大屏格子尺寸
- **GIVEN** 在宽屏显示器上打开街道监控页
- **WHEN** 网格以 4 列布局渲染
- **THEN** 每格视频宽度足够大（≥480px），非小缩略图

### Requirement: 隧道烟雾复用现有烟火检测
隧道烟雾场景 SHALL 复用现有 `FireSmokePlugin`，通过在沙盘摄像头上配置烟火检测防区实现，烟雾告警仍走现有告警中心与看板。本能力 SHALL NOT 新增烟雾或事故检测代码。

#### Scenario: 隧道烟雾触发既有告警链路
- **GIVEN** 沙盘隧道摄像头已配置烟火检测防区
- **WHEN** 画面中出现烟雾并被 `FireSmokePlugin` 确认
- **THEN** 产生 `type=fire_smoke` 告警，进入现有告警中心，无需新增街道专用告警逻辑
