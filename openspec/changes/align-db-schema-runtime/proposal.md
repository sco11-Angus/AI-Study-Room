## Why

合并 PR #52（`intrusion-detect-enhance` / 座位预约增强）后，后端启动出现三处运行期报错。经诊断，三者全部是**运行库 schema/数据滞后于 `init.sql`**，代码本身无 bug——现有 `study_room` 库是用旧版 schema 建的，从未按最新 `init.sql` 重新初始化。

1. **`seat_reservation` 表不存在** — PR #52 在 `init.sql:76-87` 新增了该表，`IntrusionPlugin.setup()` → `_load_active_seats()` 启动即查询它，导致 `intrusion` 检测器加载失败：
   ```
   pymysql.err.ProgrammingError: (1146, "Table 'study_room.seat_reservation' doesn't exist")
   ```
2. **`camera` 表缺 id=5 记录，外键冲突** — `.env` 配置 `STREAM_URLS=test1`，触发 `run.py` 首个分支，`cam_id = STREAM_CAMERA_ID(5) + 0 = 5`。运行期以 `camera_id=5` 写 `alarm_event`，但库中 `camera` 只有 `id=1`，写库持续失败并刷屏：
   ```
   pymysql.err.IntegrityError: (1452, 'a foreign key constraint fails ...
     alarm_event_ibfk_2 FOREIGN KEY (camera_id) REFERENCES camera(id))')
   ```
3. **`alarm_event` 外键删除规则与 `init.sql` 不一致** — 实际库 `alarm_event_ibfk_1/2` 为 `ON DELETE CASCADE`，`init.sql:108-109` 期望 `ON DELETE SET NULL`。旧规则下删除某摄像头/防区会连带删除其全部历史告警，与设计（保留历史告警、仅置空外键）不符。

RTMP 拉流本身正常（`ffprobe` 确认 `rtmp://49.233.71.82:9090/live/test1` 在推 1920x1080 H.264，后端日志亦有 `camera_id=5 拉流成功`）。**不属于本提案范围。**

## What Changes

- **补建 `seat_reservation` 表** — 幂等执行 `init.sql:76-87` 的建表 DDL，修复 `intrusion` 检测器加载失败。
- **补齐 `camera` 数据 / 对齐运行 camera_id** — 让运行期使用的 `camera_id` 在 `camera` 表中存在，消除 `alarm_event` 外键写入失败。采用最小改动：向 `camera` 表补插 `id=5`（`test1`，`rtmp://49.233.71.82:9090/live/test1`，`1920x1080`，`online`）。
- **修正 `alarm_event` 外键删除规则** — 将 `alarm_event_ibfk_1`（region_id）与 `alarm_event_ibfk_2`（camera_id）由 `ON DELETE CASCADE` 改为 `ON DELETE SET NULL`，对齐 `init.sql` 设计，保护历史告警不被连带删除。
- **不重建数据库、不清空现有数据**（已注册人脸 member、历史 alarm_event、region 配置全部保留）；不修改 `.env`、不改任何应用代码。

## Capabilities

### Modified Capabilities

- `stream-scheduler`: 明确运行期 camera_id 必须与 `camera` 表主键一致，作为告警持久化的前置数据契约。
- `alarm-closeloop`: 明确 `alarm_event` 外键在关联删除时置空（SET NULL）而非级联删除，保护历史告警留存。

## Impact

| 影响面 | 说明 |
|--------|------|
| `study_room.seat_reservation`（运行库） | 幂等补建表（照 `init.sql:76-87`） |
| `study_room.camera`（运行库） | 补插 `id=5` 记录，对齐运行 camera_id |
| `study_room.alarm_event`（运行库） | 两个外键 `CASCADE` → `SET NULL` |
| 应用代码 | 无改动 |
| `.env` | 无改动 |
| 现有数据 | 全部保留，无删除/清空 |

## Alternatives Considered

| 方案 | 取舍 | 结论 |
|------|------|------|
| **A. 最小数据修复（本提案）** | 仅补表 + 补数据 + 改外键规则，不丢数据、不动配置 | ✅ 采用 |
| B. `DROP DATABASE` 重跑完整 `init.sql` | schema 100% 对齐，但清空全部现有数据（人脸/告警/区域） | ❌ 破坏性，仅限全新环境 |
| C. 改 `.env` 把 `STREAM_URLS` 指向已存在的 id=1 | 不用补 camera 数据，但改变运行拓扑、掩盖 id 不一致根因 | ❌ 治标不治本 |
