## Context

PR #52（`intrusion-detect-enhance`）已合并到 main，`init.sql` 与应用代码均已就位。但本地运行库 `study_room` 是用**旧版 schema** 建的，从未按最新 `init.sql` 重新初始化，导致三处运行期报错（详见 proposal.md）。

**诊断依据（只读查询实际库结构）：**

```
SHOW TABLES →  alarm_event, app_user, camera, guard, member,
               notification_log, region, seat_status
               ^^^ 缺 seat_reservation

SELECT id,name,stream_url,status FROM camera
  → (1, '...习室A区', 'rtmp://49.233.71.82:9090/live/test1', 'online')
    ^^^ 只有 id=1

alarm_event 外键实际规则:
  alarm_event_ibfk_1  region_id → region   DELETE_RULE = CASCADE
  alarm_event_ibfk_2  camera_id → camera   DELETE_RULE = CASCADE
  init.sql 期望:                             DELETE_RULE = SET NULL
```

**运行期 camera_id 来源链：**

```
.env: STREAM_URLS=test1
   └─▶ run.py 首分支: cam_id = Config.STREAM_CAMERA_ID(默认5) + 0 = 5
        └─▶ scheduler 以 camera_id=5 拉流(成功) → 检测 → 写 alarm_event(camera_id=5)
             └─▶ camera 表无 id=5 → FK 1452 失败
```

## Goals / Non-Goals

**Goals:**
- 让 `intrusion` 检测器能正常加载（补建 `seat_reservation`）
- 让告警能正常入库（运行 camera_id 在 `camera` 表中存在）
- 让 `alarm_event` 外键规则对齐 `init.sql`，保护历史告警
- 不丢失任何现有数据，不改应用代码，不改 `.env`

**Non-Goals:**
- 不重建数据库
- 不修 RTMP 拉流（流本身正常）
- 不修改 `run.py` 的 camera_id 计算逻辑或 `STREAM_URLS` 配置语义
- 不引入自动化 DB 迁移框架（如 Alembic）——本次为一次性对齐

## Decisions

### D1: 用幂等 SQL 补建 `seat_reservation`，不重建库

**选择：** 执行 `init.sql:76-87` 的 `CREATE TABLE IF NOT EXISTS seat_reservation (...)`，其余表原样保留。

**理由：** `init.sql` 全程使用 `CREATE TABLE IF NOT EXISTS` / `INSERT IGNORE`，本身幂等。只补缺失的表，对现有 8 张表和数据零影响。

### D2: 用补插 camera 数据对齐 camera_id，而非改配置

**选择：** `INSERT INTO camera (id,name,stream_url,resolution,status) VALUES (5,'test1摄像头','rtmp://49.233.71.82:9090/live/test1','1920x1080','online')`（`INSERT ... ON DUPLICATE KEY UPDATE` 幂等）。

**权衡：** 运行 camera_id=5 来自 `STREAM_CAMERA_ID` 默认值。有两种对齐方式——(a) 补 camera 数据让 id=5 存在；(b) 改 `.env` 让运行拓扑指向已有的 id=1。选 (a)，因为它不改变运行拓扑、不掩盖"运行 id 与表主键需一致"这一数据契约，且改动可逆。

**注意：** `init.sql:127-129` 原本就有 id=5 的默认插入（url 为 `.../live/test`），本次将 url 对齐为运行实际使用的 `test1`。

### D3: 修正外键删除规则为 SET NULL

**选择：** `ALTER TABLE alarm_event DROP FOREIGN KEY alarm_event_ibfk_1/2` 后按 `init.sql` 重建为 `ON DELETE SET NULL`。

**理由：** 现规则 `CASCADE` 会在删除摄像头/防区时连带清除其历史告警，违背"告警留存可追溯"。`SET NULL` 下 `alarm_event.region_id/camera_id` 可空，删除关联实体仅置空外键、保留告警记录。此改动幂等性弱（依赖约束名 `ibfk_1/2`），执行前需先查实际约束名。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| 约束名 `ibfk_1/2` 在不同环境可能不同 | 执行 D3 前先 `SELECT CONSTRAINT_NAME FROM information_schema` 查实际名 |
| 直接改运行库绕过版本控制 | 本次仅为让运行库对齐已入库的 `init.sql`，无新 schema；长期应引入迁移工具（Non-Goal） |
| 误操作影响生产数据 | 全部为补充/规则调整，无 DROP TABLE / DELETE；执行前建议 `mysqldump` 备份 |

## Migration Plan

1.（建议）`mysqldump study_room > backup.sql` 备份
2. 执行 D1：补建 `seat_reservation`
3. 执行 D2：补插/更新 `camera` id=5
4. 执行 D3：先查约束名，再改外键规则为 SET NULL
5. 重启后端，确认三处报错消失、`intrusion` 加载成功、告警正常入库
