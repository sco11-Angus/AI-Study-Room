## MODIFIED Requirements

### Requirement: 防区实时生命周期

The system SHALL maintain a per-trajectory lifecycle of enter, dwell, alerted,
and exited for danger zones and reserved seats. It SHALL persist exactly one
alarm when an unauthorized trajectory reaches the configured dwell time, and
SHALL publish a non-persistent `region_state` clear event when that alerted
trajectory leaves or expires after the configured inference-miss tolerance.

#### Scenario: 非预约人员离开座位后解除实时状态
- **GIVEN** 陌生人 S 已在预约座位 A 中停留到阈值并触发 `occupy` 告警
- **WHEN** S 离开座位多边形，或连续超过三次推理未再被检测到
- **THEN** 系统发布 `region_state=cleared` 和 S 的 `track_key`
- **AND THEN** 不创建第二条历史告警记录

#### Scenario: 多人防区在最后一人离开前保持告警
- **GIVEN** 同一防区有两个已告警的非授权轨迹 S1 和 S2
- **WHEN** S1 离开
- **THEN** 系统仅解除 S1 的实时状态，防区仍为 active
- **WHEN** S2 随后离开
- **THEN** 防区实时状态解除

#### Scenario: 离开后再次进入创建新告警
- **GIVEN** 非授权轨迹 S 已触发告警并完成实时解除
- **WHEN** S 再次进入同一防区并停留到阈值
- **THEN** 系统创建一条新的同类型告警

### Requirement: 座位占用检测告警
The system SHALL 在人员停留于已绑定预约成员的座位防区内且停留时间达到 `Y_stay_time` 时，对人脸识别结果非预约成员的人员触发 `occupy` 告警。预约成员进入绑定座位不触发告警。

座位预约关系来源于 `seat_reservation` 表，不再依赖 `seat_status.status`。

#### Scenario: 预约成员进入绑定座位
- **GIVEN** 座位防区 A 已绑定预约成员 M（`seat_reservation` 记录存在且 `enabled=true`）
- **WHEN** 成员 M 进入防区 A 并停留达到 `Y_stay_time`
- **THEN** 不触发 `occupy` 告警

#### Scenario: 非预约已知成员占用座位
- **GIVEN** 座位防区 A 已绑定预约成员 M
- **WHEN** 另一已知成员 N 进入防区 A 并停留达到 `Y_stay_time`
- **THEN** 触发 `AlarmEvent(type="occupy", level=1)`，`extra.kind="unauthorized_seat"`，`extra.reserved_member_id=M`，`extra.actual_face_match="member:{N}"`

#### Scenario: 陌生人占用座位
- **GIVEN** 座位防区 A 已绑定预约成员 M
- **WHEN** 陌生人（人脸未匹配到任何 member）进入防区 A 并停留达到 `Y_stay_time`
- **THEN** 触发 `AlarmEvent(type="occupy", level=1)`，`extra.actual_face_match="stranger"`

#### Scenario: 多人同时入座各自独立判定
- **GIVEN** 座位防区 A 已绑定预约成员 M
- **WHEN** 成员 M 和陌生人 S 同时进入防区 A 并停留达到 `Y_stay_time`
- **THEN** 成员 M 不告警，陌生人 S 触发 `occupy` 告警

#### Scenario: 人员离开后重新进入重新计时
- **GIVEN** 人员 P 在座位防区 A 内已停留 `Y_stay_time - 2` 秒
- **WHEN** P 离开防区 A 后再次进入
- **THEN** P 的停留计时清零，从 0 重新累计

#### Scenario: 未绑定座位的防区不执行身份核验
- **GIVEN** 座位防区 B 未绑定任何预约成员（`seat_reservation` 无记录）
- **WHEN** 任意人员进入防区 B 并停留
- **THEN** 不触发 `occupy` 告警（座位身份核验不生效）

#### Scenario: 解绑后停止身份核验
- **GIVEN** 座位防区 A 原已绑定预约成员 M
- **WHEN** 管理员解绑（删除 `seat_reservation` 记录）并热更新后
- **THEN** 防区 A 不再执行座位身份核验，不再产生 `occupy` 告警

#### Scenario: 绑定热更新
- **GIVEN** 座位防区 A 未绑定预约成员
- **WHEN** 管理员通过 API 绑定成员 M
- **THEN** `IntrusionPlugin` 热更新后，防区 A 开始执行身份核验，无需重启后端

#### Scenario: 整帧人脸检测关联
- **GIVEN** 人员 P 的 person box 在座位防区 A 内停留达到 `Y_stay_time`
- **WHEN** 系统对人脸进行识别
- **THEN** 在整帧中检测所有人脸，按人脸中心点落入哪个 person box 来关联，使用 `encode_from_rect()` 提取特征

#### Scenario: 危险防区入侵检测不受影响
- **GIVEN** 一个 `type=danger_zone` 的防区
- **WHEN** 人员侵入并停留达到 `Y_stay_time`
- **THEN** 触发 `intrusion` 告警，行为与变更前完全一致

## ADDED Requirements

### Requirement: 座位预约绑定管理
The system SHALL 提供独立的 `seat_reservation` 持久化模型和 REST API，允许管理员为 `seat` 类型防区绑定或解绑预约成员。预约成员必须来自 `member` 表且具备有效人脸特征。

#### Scenario: 绑定预约成员
- **GIVEN** 一个 `type=seat` 的防区和一个具有人脸特征的成员 M
- **WHEN** 管理员调用 `PUT /api/seat-reservations/{region_id}` 传入 `{member_id: M}`
- **THEN** 创建或更新 `seat_reservation` 记录，`region_id` 唯一绑定 `member_id=M`，`enabled=true`

#### Scenario: 更新预约成员
- **GIVEN** 座位防区 A 已绑定成员 M
- **WHEN** 管理员调用 `PUT /api/seat-reservations/{region_id}` 传入 `{member_id: N}`
- **THEN** `seat_reservation` 记录更新为 `member_id=N`，热更新 `IntrusionPlugin`

#### Scenario: 解除绑定
- **GIVEN** 座位防区 A 已绑定成员 M
- **WHEN** 管理员调用 `DELETE /api/seat-reservations/{region_id}`
- **THEN** 删除 `seat_reservation` 记录，热更新 `IntrusionPlugin`，防区 A 停止身份核验

#### Scenario: 查询座位绑定状态
- **GIVEN** 摄像头 C 下有多个 seat 防区
- **WHEN** 管理员调用 `GET /api/seat-reservations?camera_id=C`
- **THEN** 返回该摄像头下所有已绑定座位的预约状态列表

#### Scenario: 绑定校验 — 仅 seat 类型
- **GIVEN** 一个 `type=danger_zone` 的防区
- **WHEN** 管理员尝试绑定预约成员
- **THEN** 返回 400 错误，提示仅允许 seat 类型防区绑定

#### Scenario: 绑定校验 — 成员需有人脸特征
- **GIVEN** 成员 K 的 `feature` 字段为空
- **WHEN** 管理员尝试绑定 K 到某座位
- **THEN** 返回 400 错误，提示预约成员必须具备有效人脸特征

#### Scenario: 查询可核验成员
- **WHEN** 前端调用 `GET /api/members?face_enrolled=true`
- **THEN** 返回所有 `feature IS NOT NULL AND feature != ''` 的成员列表

#### Scenario: 默认约束 — 长期绑定
- **GIVEN** 座位防区 A 已绑定成员 M
- **WHEN** 无管理员操作
- **THEN** 绑定关系持续有效，直到管理员手动解绑
