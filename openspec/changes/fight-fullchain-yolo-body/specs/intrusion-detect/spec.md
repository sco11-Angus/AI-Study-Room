## MODIFIED Requirements

### Requirement: 入侵检测告警
The system SHALL 在人员基准点闯入防区或低于安全距离，且无间断停留时间达到 `Y_stay_time` 时触发告警。

系统 SHALL 在每个推理帧上无条件执行 YOLO 人体检测并将人员框写入引擎共享上下文（`shared_ctx.set(camera_id, frame_idx, boxes)`），且该写入 SHALL 在「本摄像头是否配置危险区/座位」的早退判断**之前**完成。即：无论该摄像头是否配置任何防区或占座座位，人员框都 SHALL 被计算并写入共享上下文，供打架检测等下游检测器复用（协作红线「人员框只算一次」）。入侵告警的计数与判定逻辑保持不变。

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

#### Scenario: 无防区摄像头仍写入人员框
- **GIVEN** 某摄像头未配置任何危险区或占座座位
- **WHEN** 该摄像头的推理帧被派发到 `IntrusionPlugin.detect()`
- **THEN** YOLO 人体检测仍被执行，人员框写入 `shared_ctx`
- **AND** 不产生任何入侵告警（因无防区可判定）

#### Scenario: 打架检测复用同一份人员框
- **GIVEN** `IntrusionPlugin` 已在本帧写入 `shared_ctx`
- **WHEN** `FightPlugin` 通过 `SharedContextProvider` 按 `(camera_id, frame_idx)` 读取人员框
- **THEN** 取回的是 YOLO 人体框（非人脸框）
- **AND** 全系统本帧仅执行一次人体 YOLO 推理
