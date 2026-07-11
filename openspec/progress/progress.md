# progress

## 当前已验证状态

- 仓库根目录：`C:\Users\ASUS\AI-Study-Room`

- 标准启动路径：shell-capable 环境运行 `./init.sh`；本 Windows 会话中 `bash ./init.sh` 仍返回 WSL 无可用发行版提示，使用 PowerShell 等价检查。

- 标准验证路径：
  - `python backend/scripts/verify_task_e_real_db.py`（在仓库根目录，使用 `.env` 中 `DATABASE_URI` 验证真实 MySQL 任务 E 链路）
  - `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py tests/test_fire_smoke.py`（在 `backend/` 下）
  - `python tests/smoke_test.py`（在 `backend/` 下）
  - PowerShell-equivalent `init.sh` smoke

- 当前最高优先级未完成功能：`task-c3-fire-smoke-detection` 已完成代码和 mock 验证，真实视频验收阻塞于非空 YOLO 烟火权重。

- 当前 blocker：
  - `backend/model_weights/fire_smoke.pt` 是 0 字节占位文件，真实 YOLO 推理/视频验收需替换为训练好的非空权重。
  - 本会话 `bash ./init.sh` 仍返回 WSL 无可用发行版提示；PowerShell 等价 smoke 已通过。

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

### Session 005

- 日期：2026-07-09

- 本轮目标：按照 C 任务书完成 C3「烟火检测」插件。

- 已完成：
  - 重写 `backend/app/detectors/fire_smoke.py`，实现 `FireSmokeDetector` 30 帧滑动窗口均值防误报和 `FireSmokePlugin(Detector)`。
  - `FireSmokePlugin.setup()` 支持加载 YOLO 权重，缺失/空权重清晰失败；测试可注入 fake model。
  - `FireSmokePlugin.detect()` 筛选 `fire/smoke` 类别，取本帧最大置信度送入 `feed()`，窗口命中后产出 `AlarmEvent(type="fire_smoke")`。
  - 在 `backend/run.py` 注册 `FireSmokePlugin()`，由 `InferenceEngine` 统一调度，不自建线程或循环。
  - 新增 `backend/tests/test_fire_smoke.py`，覆盖连续窗口告警、单帧高置信不告警、fire/smoke 类别、非烟火类别过滤、空权重拒绝。
  - 为恢复基础状态，修复 `.env` 只有 `MYSQL_*` 时的数据库配置 fallback，并对用户名/密码做 URL 编码，避免特殊字符破坏连接串。
  - 修复合并残留：`create_app()` 重复注册 `/ws/alarms`、`entities.py` 重复 `Guard`、`AlarmService` helper 缺失、`FaceMatcher.encode_from_rect()` mock fallback、`init.sh` 旧 PRD 路径。

- 运行过的验证：
  - `python -m py_compile backend/app/services/alarm.py backend/app/detectors/face.py backend/app/models/entities.py backend/app/config.py backend/app/detectors/fire_smoke.py backend/run.py backend/tests/test_fire_smoke.py`
  - `python -m pytest tests/test_fire_smoke.py`（在 `backend/` 下）：6 passed。
  - `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py tests/test_fire_smoke.py`（在 `backend/` 下）：38 passed, 12 warnings。
  - `python tests/smoke_test.py`（在 `backend/` 下）：通过，数据库连接成功，`DATABASE_URI` 脱敏输出。
  - PowerShell-equivalent `init.sh` smoke：通过，15 个 markdown 文档。
  - `bash ./init.sh`：仍失败，当前会话返回 WSL 无可用发行版提示。

- 已记录证据：已更新 `feature_list.json` 的 `task-c3-fire-smoke-detection` 条目。

- 提交记录：待提交。

- 更新过的文件或工件：
  - `backend/app/detectors/fire_smoke.py`
  - `backend/tests/test_fire_smoke.py`
  - `backend/run.py`
  - `backend/app/config.py`
  - `backend/app/__init__.py`
  - `backend/app/models/entities.py`
  - `backend/app/services/alarm.py`
  - `backend/app/detectors/face.py`
  - `init.sh`
  - `feature_list.json`
  - `openspec/progress/progress.md`

- 已知风险或未解决问题：
  - `backend/model_weights/fire_smoke.pt` 是 0 字节占位文件；真实 fire/smoke YOLO 推理和打火机/反光视频验收需要替换为训练好的非空权重。
  - 本会话中 `bash ./init.sh` 仍未能进入 WSL 发行版；PowerShell 等价 smoke 已通过。

- 下一步最佳动作：提供真实 `fire_smoke.pt` 后运行后端服务，用打火机/烟雾视频和反光视频完成 C3 真实视频验收。

### Session 006

- 日期：2026-07-10

- 本轮目标：测试任务 E 抓拍功能，修复 scheduler camera_id 与数据库外键不匹配问题。

- 已完成：
  - 启动后端服务，验证 API `/api/alarms` 正常响应。
  - 发现 `backend/run.py` 中 scheduler 使用 `camera_id=0`，但数据库 `camera.id` 从 1 开始，且 `AlarmEvent.camera_id` 是外键约束，导致抓拍告警无法持久化。
  - 修复 `backend/run.py` 将 `scheduler.add_camera(camera_id=0, ...)` 修改为 `camera_id=5`，匹配数据库中指向云服务器 RTMP 流的摄像头记录。
  - 重新启动后端服务，验证 scheduler 使用正确的 camera_id。
  - 运行完整后端测试套件：43 passed，无回归问题。

- 运行过的验证：
  - `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py tests/test_fire_smoke.py`：43 passed。
  - API 验证：`GET /api/alarms` 返回 200，包含 20 条历史告警记录。

- 已记录证据：已修复 `backend/run.py` 的 camera_id 配置问题。

- 提交记录：`3552cb2 fix: use correct camera_id=5 for scheduler to match database`

- 更新过的文件或工件：
  - `backend/run.py`
  - `openspec/progress/progress.md`

- 已知风险或未解决问题：
  - RTMP 云服务器流（49.233.71.82:9090）连接超时，需要 OBS 推流才能验证真实抓拍功能。
  - fire_smoke 权重文件仍为 0 字节占位。

- 下一步最佳动作：启动 OBS 推流到云服务器后，调用 `POST /api/alarms/test-capture` 验证真实抓拍功能。

### Session 007

- 日期：2026-07-11

- 本轮目标：实现告警日志记录、存储管理优化、钉钉通知图片嵌入，解决公网IP访问问题。

- 已完成：
  - 新增告警日志系统：每次告警触发时自动记录详细信息到 `backend/logs/alarm_YYYY-MM-DD.log`，包含告警ID、类型、级别、区域、摄像头、人脸匹配、消息、截图URL等。
  - 新增存储管理器 `backend/app/services/storage_manager.py`：基于磁盘使用率的分级清理策略（警告阈值80%，临界阈值90%），定时清理过期抓拍、视频片段和日志文件。
  - 优化钉钉通知：截图转换为Base64直接嵌入消息，解决公网IP无法访问问题。
  - 优化图片压缩：JPEG质量60%，最大分辨率限制为1280x720。
  - 确认页面资源路径改为相对路径，支持从任意访问地址加载。
  - 修改 `STREAM_CAMERA_ID` 默认值为5。
  - 添加Windows防火墙规则允许端口5000入站连接。
  - 测试验证：告警触发、截图生成、视频录制、钉钉通知发送均正常工作。

- 运行过的验证：
  - `python -m pytest tests/test_alarm_center.py`（在 `backend/` 下）：10 passed。
  - API验证：`GET /api/alarms/storage-status` 返回存储状态信息。
  - 真实告警测试：`POST /api/alarms/test-capture` 成功触发告警，截图和视频片段生成正常，钉钉消息发送成功。

- 已记录证据：已更新 `feature_list.json` 的任务 E 和任务 G evidence。

- 提交记录：`0c67429 feat: 告警日志记录、存储管理和钉钉通知优化`

- 更新过的文件或工件：
  - `backend/app/services/alarm.py`
  - `backend/app/services/storage_manager.py`
  - `backend/app/services/dingtalk.py`
  - `backend/app/api/alarms.py`
  - `backend/app/config.py`
  - `backend/app/services/stream_capture.py`
  - `backend/app/stream/scheduler.py`
  - `backend/run.py`
  - `.env`
  - `feature_list.json`
  - `openspec/progress/progress.md`

- 已知风险或未解决问题：
  - 公网IP `156.224.79.175:5000` 返回502 Bad Gateway，校园网网关未配置端口映射。建议使用ngrok内网穿透解决外部访问问题。
  - fire_smoke 权重文件仍为0字节占位。

- 下一步最佳动作：配置ngrok内网穿透，实现公网可访问的确认页面和回放功能。

### Session 008

- 日期：2026-07-11

- 本轮目标：修复欺骗攻击(face_spoof)和陌生人(stranger)告警推送失败问题。

- 已完成：
  - 修复 `backend/app/detectors/face.py` 中滑动窗口投票被提前return跳过的逻辑错误，确保陌生人告警去抖动正常工作。
  - 修复 `backend/app/services/alarm.py` 中缺少 `face_spoof` 类型路由处理的问题，现在欺骗攻击告警能正确触发钉钉通知。
  - 修复 `backend/app/detectors/face.py` 中 `face_spoof` 告警缺少 `camera_id` 的问题，补全 `frame.camera_id`。
  - 在 `backend/app/models/entities.py` 中添加 `face_spoof` 到告警类型枚举。
  - 在 `backend/app/services/alarm.py` 中添加 `face_spoof` 告警描述生成逻辑，包含活体分数和原因。
  - 更新数据库枚举类型，添加 `face_spoof`。
  - 更新 `init.sql` 添加 `face_spoof` 告警类型注释。

- 运行过的验证：
  - `python -m pytest tests/test_alarm_center.py`（在 `backend/` 下）：10 passed。
  - 手动测试：face_spoof告警路由成功，face_recognition正确返回None（只走WebSocket）。

- 已记录证据：已更新 `feature_list.json` 的任务 E 和任务 G evidence。

- 提交记录：`b356712 fix: 欺骗攻击和陌生人告警推送失败问题`, `9da744f chore: 更新init.sql添加face_spoof告警类型`

- 更新过的文件或工件：
  - `backend/app/services/alarm.py`
  - `backend/app/detectors/face.py`
  - `backend/app/models/entities.py`
  - `init.sql`
  - `feature_list.json`
  - `openspec/progress/progress.md`

- 已知风险或未解决问题：
  - 公网IP `156.224.79.175:5000` 返回502 Bad Gateway，校园网网关未配置端口映射。建议使用ngrok内网穿透解决外部访问问题。
  - fire_smoke 权重文件仍为0字节占位。

- 下一步最佳动作：测试人员验证欺骗攻击和陌生人告警推送功能是否正常。

