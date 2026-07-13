## 1. 数据模型与数据库

- [ ] 1.1 `backend/app/models/entities.py` 新增 `SeatReservation` 模型：`id` PK、`region_id` (UNIQUE, FK→region.id ON DELETE CASCADE)、`member_id` (FK→member.member_id ON DELETE CASCADE)、`enabled` (Boolean, default True)、`created_at`、`updated_at` — 预计 10min，无依赖
- [ ] 1.2 `init.sql` 新增 `seat_reservation` 表定义（含唯一索引 `idx_seat_reservation_region`） — 预计 5min，依赖 1.1
- [ ] 1.3 `backend/app/models/database.py` 确认 `init_db()` 会自动创建新表（SQLAlchemy `create_all` 已覆盖，确认无遗漏） — 预计 5min，依赖 1.1

## 2. 预约管理 API

- [ ] 2.1 新建 `backend/app/api/members.py`：`GET /api/members` 蓝图，支持 `?face_enrolled=true` 过滤 `feature IS NOT NULL AND feature != ''` 的成员，返回 `[{member_id, name}]` — 预计 15min，依赖 1.1
- [ ] 2.2 新建 `backend/app/api/seat_reservations.py`：`GET /api/seat-reservations?camera_id=` 查询绑定状态，JOIN `member` 表返回 `[{region_id, member_id, member_name, enabled, created_at, updated_at}]` — 预计 20min，依赖 1.1
- [ ] 2.3 `seat_reservations.py` 实现 `PUT /api/seat-reservations/{region_id}`：校验 region 存在且 `type=seat`、校验 member 存在且 `feature` 非空、upsert `seat_reservation` 记录、调用 `_notify_intrusion_changed()` 热更新 — 预计 25min，依赖 2.2
- [ ] 2.4 `seat_reservations.py` 实现 `DELETE /api/seat-reservations/{region_id}`：删除记录、调用 `_notify_intrusion_changed()` 热更新 — 预计 10min，依赖 2.3
- [ ] 2.5 `backend/app/__init__.py` 注册 `members` 和 `seat_reservations` 蓝图 — 预计 5min，依赖 2.1、2.2
- [ ] 2.6 单元测试：非法绑定（danger_zone 类型、feature 为空的 member、不存在的 region/member）、合法绑定、更新、解绑、查询 — 预计 30min，依赖 2.5

## 3. IntrusionPlugin 座位判定重构

- [ ] 3.1 `SeatRuntime` 改为持有 `member_id`、`member_name`，新增 `_timers: dict[str, dict]` 多人计时器字段 — 预计 10min，依赖 1.1
- [ ] 3.2 `_load_active_seats()` 改为查询 `SeatReservation`（`enabled=True`），JOIN `Member` 获取 `member_name`，不再依赖 `SeatStatus.status=studying` — 预计 20min，依赖 3.1
- [ ] 3.3 `detect()` 座位循环重构：遍历 seat 内所有 person box（不 break），用 IoU 与上一帧 box 匹配生成 track_key，为每个 track_key 维护独立 `enter_ts` 和 `alarmed` 状态 — 预计 40min，依赖 3.2
- [ ] 3.4 实现 `_match_person_fullframe()`：整帧调用 `face_matcher.detect_faces()`，按人脸中心点关联到 person box，调用 `encode_from_rect()` 提取特征并匹配 — 预计 25min，依赖 3.3
- [ ] 3.5 `detect()` 座位循环中：person box 停留达阈值且 `alarmed=False` 时，调用 `_match_person_fullframe()`，预约成员不报警，其他 member/stranger 产生 `occupy` 告警并标记 `alarmed=True` — 预计 20min，依赖 3.4
- [ ] 3.6 人员离开/轨迹超时清理：person box 不再在 seat 内时清除对应 `_timers[track_key]`；IoU 匹配连续失败超阈值（如 3 帧）也清除 — 预计 15min，依赖 3.5
- [ ] 3.7 告警 `extra` 结构标准化：`kind`、`seat_name`、`reserved_member_id`、`reserved_member_name`、`actual_face_match`、`person_box`、`track_key`；`message` 改为 `"非预约人员占用座位「{seat_name}」"` — 预计 10min，依赖 3.5
- [ ] 3.8 `_match_person()` 旧方法标记废弃或删除，确保无其他调用 — 预计 5min，依赖 3.4

## 4. 单元测试

- [ ] 4.1 预约人免警：绑定 member A → FakeFaceMatcher 返回 `member:A` → 无告警 — 预计 10min，依赖 3.5
- [ ] 4.2 已知非预约人告警：绑定 member A → FakeFaceMatcher 返回 `member:B` → 产生 occupy 告警，extra 含 reserved/actual — 预计 10min，依赖 3.5
- [ ] 4.3 陌生人告警：绑定 member A → FakeFaceMatcher 返回 `stranger` → 产生 occupy 告警 — 预计 5min，依赖 3.5
- [ ] 4.4 多人同时入座：FakePersonDetector 返回 2 个 box，一个匹配 A 一个匹配 stranger → 只有 stranger 告警 — 预计 15min，依赖 3.5
- [ ] 4.5 离开后重新计时：person box 进入 → 离开 → 再进入 → 计时清零重新累计 — 预计 15min，依赖 3.6
- [ ] 4.6 绑定热更新：先无绑定（无告警）→ 绑定后 `_reload_regions()` → 非预约人告警 — 预计 15min，依赖 3.2
- [ ] 4.7 解绑后停止核验：绑定 → 解绑 → `_reload_regions()` → 无告警 — 预计 10min，依赖 3.2
- [ ] 4.8 告警内容校验：extra 字段完整性、message 文案正确 — 预计 10min，依赖 3.7
- [ ] 4.9 更新 `test_intrusion_identity.py`：`seed_reserved_seat()` 改为插入 `SeatReservation` 而非 `SeatStatus` — 预计 15min，依赖 1.1

## 5. 前端集成

- [ ] 5.1 防区配置页 seat 防区编辑表单增加"预约成员"下拉（调用 `GET /api/members?face_enrolled=true` 获取选项） — 预计 20min，依赖 2.1
- [ ] 5.2 seat 防区表单增加"绑定"/"解绑"按钮和当前绑定状态展示（调用 `GET /api/seat-reservations?camera_id=` 获取状态） — 预计 20min，依赖 2.2
- [ ] 5.3 danger_zone 防区表单不渲染预约控件（条件渲染） — 预计 5min，依赖 5.2
- [ ] 5.4 绑定/解绑成功后更新前端状态展示 — 预计 10min，依赖 5.2

## 6. 回归与端到端验收

- [ ] 6.1 运行 `pytest tests/test_intrusion.py tests/test_intrusion_identity.py tests/test_face.py tests/test_fatigue.py tests/test_alarm_center.py -v`（SQLite 临时配置），确认全部通过 — 预计 15min，依赖 4.x
- [ ] 6.2 运行 `.\init.cmd` 烟雾测试，确认后端启动正常 — 预计 10min，依赖 6.1
- [ ] 6.3 前端生产构建 `npm run build`，确认无编译错误 — 预计 10min，依赖 5.x
- [ ] 6.4 本地端到端验收：画 seat 防区 → 绑定成员 A → A 入座不告警 → B/陌生人入座告警（大屏红闪 + 告警记录含预约人和实际识别结果）→ 解绑后停止核验 → danger_zone 入侵检测不受影响 — 预计 30min，依赖 6.2、6.3
