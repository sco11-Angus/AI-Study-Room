# F 任务书 — 前端全包（Vue 3 + Element Plus）

> 角色定位：前端一人统包三个页面与全部组件。等 A/D/E 契约冻结后写联调细节，前期用 mock 搭骨架。
> 关联设计：系统设计说明书 §4、§5.1、§7.3。
> 涉及文件：`frontend/src/views/*`、`frontend/src/components/*`、`frontend/src/api/index.js`、`frontend/src/store/alarm.js`、`frontend/src/router/index.js`。
> 依赖：A 的 HTTP-FLV 播放地址、D 的接口+返回结构、E 的 AlarmEvent+WebSocket。

---

## 一、任务拆解

### 任务 F1：工程基座与接口封装
- `npm install` 跑通 Vite + Vue3 + Element Plus + Pinia + flv.js。
- 完善 `api/index.js`：8 个接口封装已列出（cameras/regions×4/seat-status/alarms/confirm）。
- axios 拦截器：统一解包 `{code,message,data}`，`code!=0` 弹 `ElMessage` 报错。
- 完善 `store/alarm.js`：告警列表 + `activeRegions` 颜色状态。

### 任务 F2：视频播放组件 `VideoPlayer.vue`（§3.3）
- flv.js 播放 A 提供的 HTTP-FLV 地址，`isLive:true`。
- 断流重连、组件卸载 `destroy()`（骨架已有）。
- 暴露 `videoWidth/videoHeight` 供 Canvas 对齐。

### 任务 F3：画区组件 `CanvasDraw.vue`（§5.1，与 B 联调）
- 透明 canvas 叠在 video 上，尺寸/坐标严格对齐。
- 单击加控制点并连线预览；双击闭合成多边形；支持画多个、选中删除、重绘。
- 提交前**坐标归一化到 [0,1]**（与 B 定死的格式一致，写注释标明）。
- `@polygon` 事件把顶点数组抛给父组件。

### 任务 F4：防区配置页 `RegionConfig.vue`（§5.2）
- 左侧 CanvasDraw，右侧表单：名称、类型(danger_zone/seat)、`X_distance`、`Y_stay_time`。
- 提交调 `createRegion`；列表展示已有防区，可删除（`deleteRegion`）、回显 polygon。

### 任务 F5：告警大屏 `Dashboard.vue` + `AlarmPanel.vue`（§7.3，与 E 联调）
- VideoPlayer + 防区格子叠加层，正常绿色。
- WebSocket 连 `/ws/alarms`，收到 `AlarmEvent`：对应 `region_id` 格子**红色闪烁** + `AudioContext` 蜂鸣。
- `AlarmPanel` 表格：类型/防区/人脸匹配/时间 + 「确认处理」按钮（调 `confirmAlarm`，确认后格子恢复绿色）。
- **区分 level**：level=0（疲劳弱提醒）不在大屏红闪，仅列表灰色提示或不显示。

### 任务 F6：自习伴侣页 `SeatCompanion.vue`（§4）
- studying/resting 切换（`switchSeatStatus`）。
- 接收该用户的疲劳弱提醒并展示（私有提醒样式，非红色告警）。

---

## 二、交付物清单

| 编号 | 交付物 | 文件 | 截止 |
| --- | --- | --- | --- |
| F1 | 基座+接口封装 | `api/index.js`、`store/` | W1 |
| F2 | 播放组件 | `VideoPlayer.vue` | W1（A 地址就绪后） |
| F3/F4 | 画区+配置页 | `CanvasDraw.vue`、`RegionConfig.vue` | W2（与 B 联调） |
| F5 | 告警大屏 | `Dashboard.vue`、`AlarmPanel.vue` | 联调期（与 E） |
| F6 | 伴侣页 | `SeatCompanion.vue` | W2 |

---

## 三、验收标准（逐条可测）

- [ ] 播放流畅，延迟观感 ≤ 2s。
- [ ] 可在画面上画多个多边形，双击闭合，提交后刷新能回显。
- [ ] 720p/1080p 下画区坐标与后端判定一致（与 B 对拍验证）。
- [ ] 触发入侵告警 → 对应格子实时红闪 + 蜂鸣；点确认后恢复绿色。
- [ ] 疲劳弱提醒只在伴侣页私有展示，大屏不红闪。
- [ ] studying/resting 切换即时生效（后端能收到状态变更）。
- [ ] 接口报错有友好提示，不白屏。

---

## 四、协作接口

| 方向 | 对象 | 约定 |
| --- | --- | --- |
| 依赖 | A | HTTP-FLV 播放地址格式 |
| 依赖 | D | 接口路径、统一返回结构、Swagger |
| 依赖 | E | `AlarmEvent` JSON、`/ws/alarms` 推送格式 |
| 对接 | B | 画区坐标格式（归一化 or 像素，定死一种） |

> 提示：前期用 mock JSON 搭骨架，A/D/E 契约冻结后替换真实接口，避免返工。
