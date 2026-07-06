# F 任务书 — 前端全包（Vue 3 + Element Plus）

> 角色定位：前端一人统包三个页面与全部组件，与 B（画区参数）、E（告警结构）重点联调。
> 关联设计：系统设计说明书 §4、§5.1、§7.3。

## 一、职责范围

1. **告警监测大屏 `Dashboard.vue`（§7.3）**
   - FLV 低延迟播放（`VideoPlayer.vue` + flv.js）。
   - WebSocket 订阅 E 的告警推送，对应格子绿→红闪烁 + 局部蜂鸣。
   - 告警列表 `AlarmPanel.vue` + 确认处理按钮（调 `alarms/{id}/confirm`）。
2. **防区配置 `RegionConfig.vue`（§5.1）**
   - `CanvasDraw.vue`：视频图层上单击加点、双击闭合生成多边形 ROI，支持多防区/删除/重绘。
   - 坐标归一化后提交，参数 `X_distance` / `Y_stay_time` 表单。
   - 与 B 联调传参格式。
3. **自习伴侣 `SeatCompanion.vue`（§4）**
   - studying / resting 状态切换（调 `seat-status`）。
   - 疲劳弱提醒展示（私有提醒，非公用警报）。
4. **公共**
   - `api/index.js` 接口封装、Pinia store、路由。

## 二、交付物

| 交付 | 说明 |
| --- | --- |
| 三个页面 + 六个组件 | Dashboard / RegionConfig / SeatCompanion 等 |
| Canvas 画区交互 | 加点/闭合/多防区/坐标归一化 |
| WebSocket 大屏 | 实时红闪蜂鸣 + 确认 |

## 三、验收标准

- [ ] 画面流畅播放，延迟观感 ≤ 2s。
- [ ] 画区可画多个多边形并正确提交、回显。
- [ ] 告警实时红闪 + 蜂鸣，确认后恢复。
- [ ] 状态切换即时生效。

## 四、协作接口

- **上游**：A（播放地址）、D（接口 + 返回结构）、E（告警事件结构 + WebSocket）。
- **下游**：B（画区参数交付给后端判定）。

> 提示：等 A 的播放地址、D 的接口契约、E 的告警结构冻结后再动手细节，避免返工。前期可先用 mock 数据搭页面骨架。
