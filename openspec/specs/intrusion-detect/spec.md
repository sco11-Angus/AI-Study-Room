# Intrusion Detect

## Purpose
通过人员检测、几何距离判定和时空防抖机制检测人员进入或靠近防区的行为，按摄像头隔离防区状态并在满足停留条件后产生可追溯的安全告警。

## Requirements

### Requirement: 入侵检测告警
The system SHALL 在人员基准点闯入防区或低于安全距离，且无间断停留时间达到 `Y_stay_time` 时触发告警。

#### Scenario: 基准点闯入防区
- **GIVEN** 一个已配置的防区多边形
- **WHEN** 基准点 `pointPolygonTest >= 0`
- **THEN** 启动危险计时器

#### Scenario: 安全距离不足
- **GIVEN** 一个已配置的安全距离 `X_distance`
- **WHEN** `D < 0` 且 `|D| <= X_distance`
- **THEN** 启动危险计时器

#### Scenario: 持续停留触发告警
- **GIVEN** 危险计时器已启动
- **WHEN** 危险计时无间断累计 `>= Y_stay_time`
- **THEN** 触发告警事件

#### Scenario: 回到安全状态
- **GIVEN** 危险计时器正在累计
- **WHEN** 任一帧回到安全状态
- **THEN** 计时器清零
