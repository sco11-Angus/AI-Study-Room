## ADDED Requirements

### Requirement: 告警历史在关联实体删除时留存
`alarm_event` 表对 `region_id`、`camera_id` 的外键 SHALL 使用 `ON DELETE SET NULL` 删除规则。删除关联的防区或摄像头时，对应外键置空，`alarm_event` 记录本身保留，保证历史告警可追溯。

#### Scenario: 删除摄像头保留历史告警
- **GIVEN** `alarm_event` 存在若干 `camera_id=5` 的历史告警记录
- **WHEN** 删除 `camera` 表中 `id=5` 的记录
- **THEN** 相关 `alarm_event` 记录保留，其 `camera_id` 被置为 NULL，不发生级联删除

#### Scenario: 删除防区保留历史告警
- **GIVEN** `alarm_event` 存在若干 `region_id=R` 的历史告警记录
- **WHEN** 删除 `region` 表中 `id=R` 的记录
- **THEN** 相关 `alarm_event` 记录保留，其 `region_id` 被置为 NULL
