# OpenSpec 规范驱动边界定义 (系统设计说明书 §10.3)

> 规范驱动开发：先由本文件明确边界，再编写代码。每个能力对应一份规范。

## 能力清单

| 能力 | 边界 | 对应模块 | 设计章节 |
| --- | --- | --- | --- |
| seat-status | 状态切换驱动疲劳算法激活/挂起 | backend/api/seat_status, detectors/fatigue | §4 |
| region-config | Canvas 画区 + 参数持久化 | frontend/RegionConfig, backend/api/regions | §5.1-5.2 |
| intrusion-detect | 几何判定 + 时空防抖告警 | detectors/intrusion | §5.3-5.4 |
| fire-smoke-detect | 连续 30 帧置信度加权 | detectors/fire_smoke | §6 |
| alarm-closeloop | 抓拍+人脸+看板+钉钉升级 | services/alarm, services/dingtalk | §7 |
| stream-scheduler | 跳帧调度，延迟≤2s | stream/scheduler | §3 |

## 规范样例：intrusion-detect

### 需求
系统应当在人员基准点闯入防区或低于安全距离，且无间断停留时间达到 `Y_stay_time` 时触发告警。

### 场景
- WHEN 基准点 `pointPolygonTest >= 0` THEN 启动危险计时器。
- WHEN `D < 0` 且 `|D| <= X_distance` THEN 启动危险计时器。
- WHEN 危险计时无间断累计 `>= Y_stay_time` THEN 触发告警事件。
- WHEN 任一帧回到安全状态 THEN 计时器清零。

## 验收对照
详见系统设计说明书 §13 需求追溯矩阵。
