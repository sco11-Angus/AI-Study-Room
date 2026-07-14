## ADDED Requirements

### Requirement: 运行期 camera_id 与 camera 表主键一致
调度器为每一路流分配的 `camera_id` SHALL 在 `camera` 表中存在对应主键记录。凡以该 `camera_id` 写入 `alarm_event` 等关联表的操作，均以此为数据前置契约。

当 `STREAM_URLS` 触发按序号分配 camera_id（`camera_id = STREAM_CAMERA_ID + 序号`）时，所分配的每个 id 都必须能在 `camera` 表中找到记录。

#### Scenario: 运行 camera_id 存在于 camera 表
- **GIVEN** `.env` 配置 `STREAM_URLS=test1`，`STREAM_CAMERA_ID=5`，运行分配 `camera_id=5`
- **WHEN** 调度器拉流并触发告警写入 `alarm_event(camera_id=5)`
- **THEN** `camera` 表存在 `id=5` 记录，写入成功，无外键冲突

#### Scenario: 运行 camera_id 缺失时暴露为配置错误
- **GIVEN** 运行分配 `camera_id=N` 但 `camera` 表无 `id=N`
- **WHEN** 尝试写入 `alarm_event(camera_id=N)`
- **THEN** 触发外键约束失败（1452），应通过补齐 `camera` 记录或修正 camera_id 配置解决，而非静默丢弃告警
