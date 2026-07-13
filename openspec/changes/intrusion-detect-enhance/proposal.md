## Why

当前座位占用检测存在一个根本性的身份混用问题：`seat_status.user_id` 直接与 `member.member_id` 比较，但 `seat_status.user_id` 外键指向 `app_user.id`，两者是不同的 ID 空间。这导致：

1. **身份空间混用** — `app_user.id` 和 `member.member_id` 是独立自增序列，对比无意义，预约人身份判定不可靠。
2. **预约关系脆弱** — 座位"预约人"依赖 `seat_status.status == "studying"` 这一自习状态，用户切到 `resting` 或 `idle` 后预约即失效，不适合长期绑定场景。
3. **人脸识别精度不足** — 当前 `_match_person()` 只裁剪 person box 区域做人脸检测，当 person box 裁剪后人脸太小或偏移时容易漏检，应改为整帧检测人脸后按中心点关联到 person box。
4. **多人共坐无隔离** — 同一座位中预约人和非预约人同时出现时，当前逻辑只对第一个 person box 做判断后 `break`，无法识别并告警非预约人。
5. **告警文案错误** — 当前告警描述为"占用时间过长"，实际语义是"非预约人员占用座位"，文案与逻辑不匹配。

## What Changes

- **新增 `seat_reservation` 持久化模型**：以 `region_id` 唯一绑定一个 `member_id`，保存启用状态和创建/更新时间；仅允许绑定 `seat` 类型防区和具有人脸特征的 member。
- **新增预约管理 API**：
  - `GET /api/members?face_enrolled=true` — 供前端选择可核验成员
  - `GET /api/seat-reservations?camera_id=` — 查询座位绑定状态
  - `PUT /api/seat-reservations/{region_id}` — 绑定或更新预约成员
  - `DELETE /api/seat-reservations/{region_id}` — 解除绑定
  - 绑定/更新/解绑后均热更新 `IntrusionPlugin`，无需重启后端
- **重构 `IntrusionPlugin` 座位判定**：
  - 仅从 `seat_reservation` 加载已绑定座位，不再依赖 `seat_status=studying`
  - 为"座位 + 人员轨迹"维护独立停留计时，使用轻量 IoU 关联人员框，避免多人共用一个计时器
  - 在整帧中识别人脸并按人脸中心点关联到 person box，使用 `encode_from_rect()` 提取特征
  - 识别为预约成员不报警；识别为其他 member 或 stranger 均产生 `AlarmEvent(type="occupy", level=1)`
  - 人员离开座位、轨迹超时或解绑后清空对应计时与已告警状态
- **完善告警信息**：`extra` 固定记录 `kind=unauthorized_seat`、座位名、预约成员 ID/姓名、实际识别结果、人员框、轨迹 ID；告警描述改为"非预约人员占用座位"。
- **前端防区配置页增强**：为 `seat` 防区增加预约成员下拉选择、绑定/解绑操作和当前绑定状态展示；危险防区不显示预约控件。
- **`seat_status` 职责收窄**：继续只服务"自习/休息/疲劳检测"，不再承担预约人身份，消除 `app_user.id` 与 `member.member_id` 混用。

## Capabilities

### New Capabilities

- `seat-reservation`: 座位预约绑定管理（独立能力域）

### Modified Capabilities

- `intrusion-detect`: 座位占用判定逻辑从 `seat_status` 切换到 `seat_reservation`，增加多人独立计时和整帧人脸关联
- `region-config`: 防区配置页为 seat 防区增加预约成员绑定/解绑 UI

## Impact

| 影响面 | 说明 |
|--------|------|
| `backend/app/models/entities.py` | 新增 `SeatReservation` 模型 |
| `backend/app/detectors/intrusion.py` | `SeatRuntime` 改为持有 `member_id`；`_load_active_seats()` 改读 `SeatReservation`；`detect()` 座位循环重构为多人独立计时 + IoU 关联 + 整帧人脸检测 |
| `backend/app/api/seat_reservations.py` | **新文件**：预约 CRUD 蓝图 |
| `backend/app/api/members.py` | **新文件**：成员查询蓝图，支持 `face_enrolled=true` 过滤 |
| `backend/app/__init__.py` | 注册新蓝图 |
| `init.sql` | 新增 `seat_reservation` 表 |
| 前端防区配置页 | seat 防区增加预约成员下拉 + 绑定/解绑按钮 + 绑定状态展示 |
| `backend/tests/test_intrusion*.py` | 重写座位相关测试，新增预约人免警、非预约人告警、陌生人告警、多人入座、离开重计、热更新、解绑停验、非法绑定等用例 |
