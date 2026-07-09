# progress

## 当前已验证状态

- 仓库根目录：`C:\Users\25003\AI-Study-Room`

- 标准启动路径：shell-capable 环境运行 `./init.sh`；本 Windows 主机 `bash` 是 WSL shim 且未安装发行版，使用 PowerShell 等价检查。

- 标准验证路径：
  - `python backend/scripts/verify_task_e_real_db.py`（在仓库根目录，使用 `.env` 中 `DATABASE_URI` 验证真实 MySQL 任务 E 链路）
  - `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py`（在 `backend/` 下）
  - `python tests/smoke_test.py`（在 `backend/` 下）
  - PowerShell-equivalent `init.sh` smoke

- 当前最高优先级未完成功能：`feature_list.json` 中暂无未完成项；任务 E 已完成。

- 当前 blocker：`bash ./init.sh` 在本 Windows 主机失败，因为未安装 WSL 发行版；PowerShell 等价 smoke 已通过。

## 会话记录

### Session 001

- 日期：

- 本轮目标：

- 已完成：

- 运行过的验证：

- 已记录证据：

- 提交记录：

- 更新过的文件或工件：

- 已知风险或未解决问题：

- 下一步最佳动作：

### Session 002

- 日期：

- 本轮目标：

- 已完成：

- 运行过的验证：

- 已记录证据：

- 提交记录：

- 更新过的文件或工件：

- 已知风险或未解决问题：

- 下一步最佳动作：

### Session 003

- 日期：2026-07-08

- 本轮目标：完成任务 E「告警中心 + 钉钉逐级闭环」。

- 已完成：
  - 统一 `AlarmEvent` 结构，补齐 `type/region_id/camera_id/ts/level/snapshot_url/face_match/extra`，并保留旧检测器兼容字段。
  - 实现 `AlarmService.raise_alarm()`：同防区同类型 30s 去重、抓拍落盘、人脸匹配 fallback、`alarm_event` 落库、level=0 私有端分流、level>=1 WebSocket + 钉钉分发。
  - 实现 `/ws/alarms` 告警订阅广播。
  - 实现钉钉 `notify/confirm/_escalate`，写入 `notification_log`，支持确认取消计时和超时升级。
  - 实现 `GET /api/alarms?status=`、`POST /api/alarms/{id}/confirm`、抓拍访问接口。
  - 补齐 ORM：`camera_id`、`fight`、`extra`、`Guard`、通知日志外键和索引。
  - 添加任务 E 聚焦测试 `backend/tests/test_alarm_center.py`。
  - 为恢复基础 smoke，将 `StreamScheduler` ring buffer 修回 `maxlen=5`。
  - 修正 `init.sh` 检查当前仓库真实文档路径。

- 运行过的验证：
  - `python -m pip install pytest SQLAlchemy flask-cors flask-sock flasgger requests simple-websocket`（代理开启后成功）
  - `python -m py_compile backend/app/detectors/base.py backend/app/models/entities.py backend/app/services/alarm.py backend/app/services/dingtalk.py backend/app/api/ws.py backend/app/api/alarms.py backend/app/__init__.py backend/app/stream/engine.py backend/app/config.py backend/tests/test_alarm_center.py`
  - `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py`（在 `backend/` 下，27 passed）
  - `python tests/smoke_test.py`（在 `backend/` 下，通过）
  - PowerShell-equivalent `init.sh` smoke（通过，16 个 markdown 文档）
  - `bash ./init.sh`（失败：Windows WSL shim 无发行版）

- 已记录证据：已更新 `feature_list.json` 的 `alarm-center-dingtalk-close-loop` 条目。

- 提交记录：待提交。

- 更新过的文件或工件：
  - `backend/app/detectors/base.py`
  - `backend/app/models/entities.py`
  - `backend/app/services/alarm.py`
  - `backend/app/services/dingtalk.py`
  - `backend/app/api/ws.py`
  - `backend/app/api/alarms.py`
  - `backend/app/__init__.py`
  - `backend/app/stream/engine.py`
  - `backend/app/stream/scheduler.py`
  - `backend/app/config.py`
  - `backend/tests/test_alarm_center.py`
  - `init.sh`
  - `feature_list.json`
  - `openspec/progress/progress.md`

- 已知风险或未解决问题：
  - 本机 `bash ./init.sh` 仍受 WSL 环境限制，shell-capable 环境可按修正后的 `init.sh` 运行。
  - 未配置真实钉钉 webhook 时不会外发，只记录通知日志；联调真实机器人时需要配置 `.env`。
  - 人脸 Dlib 模型缺失时 `FaceMatcher.encode()` 返回不可用，告警服务按 `stranger` fallback。

- 下一步最佳动作：配置真实钉钉 webhook 和 Dlib 模型后做前后端联调，验证真实 WebSocket 红闪蜂鸣与 3 分钟升级。

### Session 004

- 日期：2026-07-08

- 本轮目标：连接用户已建好的 MySQL 数据库，并验证任务 E 真实数据库链路。

- 已完成：
  - `.env` 中 `DATABASE_URI` 成功连接 MySQL，数据库为 `study_room`，表为 `alarm_event/app_user/camera/guard/member/notification_log/region/seat_status`。
  - 新增 `backend/scripts/verify_task_e_real_db.py`，可重复执行真实库验证。
  - 验证脚本会读取 `.env`，兼容 `$env:KEY=` 写法，补最小 `camera/region/primary guard/leader guard` 种子数据。
  - 真实库验证链路已跑通：fight 告警确认、intrusion 告警升级、fatigue 弱提醒不写钉钉日志。
  - `backend/app/config.py` 支持启动时自动加载仓库根目录 `.env`。
  - `backend/requirements.txt` 添加 `PyMySQL`，支持 `mysql+pymysql://...`。
  - `init.sql` 同步为任务 E 兼容版本：`confirmed_at` 和 `ack_at` 允许 `NULL`，避免新告警/新通知未确认时写入失败。
  - `backend/tests/smoke_test.py` 对 `DATABASE_URI` 输出做脱敏，避免日志泄露密码。

- 运行过的验证：
  - `python backend/scripts/verify_task_e_real_db.py`：通过，最新一次验证告警 ID 为 fight=7、intrusion=8、fatigue=9。
  - `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py`（在 `backend/` 下）：27 passed。
  - `python tests/smoke_test.py`（在 `backend/` 下）：通过，`DATABASE_URI` 已脱敏输出。
  - `./init.sh`：PowerShell 直接调用返回 0。
  - PowerShell-equivalent `init.sh` smoke：通过，16 个 markdown 文档。

- 已记录证据：已更新 `feature_list.json` 的任务 E evidence。

- 提交记录：待提交。

- 更新过的文件或工件：
  - `backend/app/config.py`
  - `backend/requirements.txt`
  - `backend/scripts/verify_task_e_real_db.py`
  - `backend/tests/smoke_test.py`
  - `init.sql`
  - `feature_list.json`
  - `openspec/progress/progress.md`

- 已知风险或未解决问题：
  - 真实钉钉 webhook 仍未外发验证；脚本使用空 webhook，仅验证本地闭环和通知日志。
  - Dlib 模型缺失时人脸识别仍按 `stranger` fallback。
  - 本机 `bash ./init.sh` 仍受 WSL 环境限制。

- 下一步最佳动作：配置真实钉钉 webhook 后执行一次外发 ActionCard 和确认按钮回调联调。

