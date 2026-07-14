## 1. 备份与核对

- [ ] 1.1 `mysqldump study_room > backup_before_align.sql` 备份现有库。
- [ ] 1.2 复核实际库现状：`SHOW TABLES`（确认缺 `seat_reservation`）、`SELECT id,stream_url FROM camera`（确认无 id=5）、查 `alarm_event` 外键 `DELETE_RULE`（确认为 CASCADE）。

## 2. 补建 seat_reservation（修复 intrusion 加载）

- [ ] 2.1 执行 `init.sql:76-87` 的 `CREATE TABLE IF NOT EXISTS seat_reservation (...)`。
- [ ] 2.2 验证 `DESC seat_reservation` 与 `init.sql` 一致（`region_id` 唯一键、`member_id` 外键、`enabled`、时间戳）。

## 3. 对齐 camera_id（修复告警外键）

- [ ] 3.1 `INSERT INTO camera (id,name,stream_url,resolution,status) VALUES (5,'test1摄像头','rtmp://49.233.71.82:9090/live/test1','1920x1080','online') ON DUPLICATE KEY UPDATE stream_url=VALUES(stream_url), resolution=VALUES(resolution), status=VALUES(status)`。
- [ ] 3.2 验证 `SELECT id,stream_url FROM camera WHERE id=5` 返回记录。

## 4. 修正 alarm_event 外键删除规则

- [ ] 4.1 `SELECT CONSTRAINT_NAME,COLUMN_NAME,DELETE_RULE FROM information_schema.KEY_COLUMN_USAGE ... WHERE TABLE_NAME='alarm_event'` 查实际约束名。
- [ ] 4.2 `ALTER TABLE alarm_event DROP FOREIGN KEY <region_fk>, DROP FOREIGN KEY <camera_fk>`。
- [ ] 4.3 按 `init.sql:108-109` 重建：`ADD FOREIGN KEY (region_id) REFERENCES region(id) ON DELETE SET NULL`、`ADD FOREIGN KEY (camera_id) REFERENCES camera(id) ON DELETE SET NULL`。
- [ ] 4.4 复查 `DELETE_RULE` 已变为 `SET NULL`。

## 5. 验证

- [ ] 5.1 重启后端，确认日志无 `seat_reservation doesn't exist`、无 `1452 foreign key` 报错。
- [ ] 5.2 确认 `[run] 已注册检测器` 含 `intrusion`，且 `intrusion 加载完成`。
- [ ] 5.3 触发一次告警（或等 face_spoof），确认 `SELECT COUNT(*) FROM alarm_event` 增加、无写库异常。
- [ ] 5.4 运行 `backend/tests/test_intrusion*.py`、`test_alarm_center.py`、`test_seat_reservations.py` 通过。
