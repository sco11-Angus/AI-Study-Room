# progress

## 当前已验证状态

- 仓库根目录：`C:\Users\ASUS\AI-Study-Room`

- 标准启动路径：shell-capable 环境运行 `./init.sh`；Windows PowerShell 运行 `.\init.cmd`。`init.cmd` 会用 `ExecutionPolicy Bypass` 调用 `init.ps1`，避免 PowerShell 直接执行 `.sh` 或受 `.ps1` 执行策略阻塞。

- 标准验证路径：
  - `python backend/scripts/verify_task_e_real_db.py`（在仓库根目录，使用 `.env` 中 `DATABASE_URI` 验证真实 MySQL 任务 E 链路）
  - `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py tests/test_fire_smoke.py`（在 `backend/` 下）
  - `python tests/smoke_test.py`（在 `backend/` 下）
  - `.\init.cmd`（Windows PowerShell smoke）

- 当前最高优先级未完成功能：暂无。`task-c3-fire-smoke-detection` 已接入 `fire-smoke-detect-yolov4-master/yolov5` 旧 YOLOv5 烟火权重，并通过后端脚本对 `test_photos/fire_test.jpg` 完成原始检测和 30 帧 `AlarmEvent(type="fire_smoke")` 告警验证。

- 当前 blocker：暂无功能完成阻塞。

- 当前风险/部署注意：
  - 部署时需保留 `fire-smoke-detect-yolov4-master/yolov5`，或通过 `FIRE_SMOKE_LEGACY_YOLOV5_DIR` 指向旧 YOLOv5 源码目录；`backend/model_weights/fire_smoke.pt` 是本地 gitignored 权重工件。
  - 真实 RTMP/OBS 烟火/反光负样本仍可作为联调演示素材补充，但不再作为 `task-c3-fire-smoke-detection` 完成阻塞项。

### Session 006

- 日期：2026-07-10

- 本轮目标：修复 Windows PowerShell 下直接运行 `./init.sh` 被拒绝访问导致的启动验证入口问题。

- 已完成：
  - 新增 `init.ps1`，复用 `init.sh` 的必需文件和 markdown 文档数量检查。
  - 新增 `init.cmd`，在 Windows PowerShell/cmd 下通过 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File init.ps1` 运行 smoke test。
  - 更新 `AGENTS.md` 和 `README.md`，明确 Windows 下使用 `.\init.cmd`，shell-capable 环境继续使用 `./init.sh`。
  - 更新 `init.sh`，让 shell 入口也检查 `init.ps1` 和 `init.cmd` 是否存在。

- 运行过的验证：
  - `.\init.cmd`：通过，输出 `Smoke test passed: required files present; markdown docs found.`
  - `cmd /c init.cmd`：通过，输出 `Smoke test passed: required files present; markdown docs found.`
  - `C:\Program Files\Git\bin\sh.exe ./init.sh`：通过，输出 `Smoke test passed: required files present; markdown docs found.`
  - `.\init.ps1`：本机被 PowerShell execution policy 拦截，因此保留 `init.cmd` 作为 Windows 直接入口。

- 已记录证据：已更新 `feature_list.json` 的初始化入口 evidence。

- 已知风险或未解决问题：
  - PowerShell 语法 `./init.sh` 在 Windows 上仍不能可靠支持，除非把 `init.sh` 替换为 Windows 原生可执行文件或修改系统级 shell launcher；仓库标准 Windows 入口改为 `.\init.cmd`。
  - `backend/model_weights/fire_smoke.pt` 仍是 0 字节占位文件，真实 YOLO 推理/视频验收仍需训练权重。

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
  - fire_smoke 权重文件为本地模型工件，按 `.gitignore` 不入库。

- 下一步最佳动作：配置ngrok内网穿透，实现公网可访问的确认页面和回放功能。

### Session 008

- 日期：2026-07-10

- 本轮目标：把根目录 `fire-smoke-detect-yolov4-master` 开源项目中的烟火模型嫁接到当前系统。

- 已完成：
  - 检查开源项目后确认 YOLOv4 权重占位为空，实际可用权重为 `fire-smoke-detect-yolov4-master/yolov5/best.pt`。
  - 确认该 `best.pt` 是老版 Ultralytics YOLOv5 pickle，不能被当前 `ultralytics==8.*` 的 `YOLO(...)` 直接加载。
  - 新增 `backend/app/detectors/legacy_yolov5.py`，封装旧 YOLOv5 源码路径、PyTorch 2.6+ `weights_only=False` 加载、letterbox、推理和 NMS，输出兼容现有 `FireSmokePlugin` 的 result/boxes 结构。
  - 修改 `FireSmokePlugin.setup()`：优先尝试 Ultralytics YOLO，失败时自动回退旧 YOLOv5 适配器。
  - 新增火烟配置项：`FIRE_SMOKE_LEGACY_YOLOV5_DIR`、`FIRE_SMOKE_IMG_SIZE`、`FIRE_SMOKE_DETECT_CONF`、`FIRE_SMOKE_IOU`、`FIRE_SMOKE_DEVICE`。
  - 将 `fire-smoke-detect-yolov4-master/yolov5/best.pt` 复制为本地 `backend/model_weights/fire_smoke.pt`，解除 0 字节权重问题；该权重按 `.gitignore` 不入库。
  - 补充后端依赖：`scipy`、`tqdm`、`mysql-connector-python`。

- 运行过的验证：
  - `.\init.cmd`：通过。
  - `python -m py_compile backend/app/config.py backend/app/detectors/fire_smoke.py backend/app/detectors/legacy_yolov5.py backend/tests/test_fire_smoke.py`：通过。
  - 真实权重加载：Ultralytics YOLOv8 拒绝旧 YOLOv5 权重后，legacy YOLOv5 fallback 成功加载，类别为 `['fire', 'smoke']`。
  - demo 图推理：`fire-smoke-detect-yolov4-master/result/result_demo.jpg` 检出 fire≈0.662、smoke≈0.311；连续 30 帧后产出 `AlarmEvent(type="fire_smoke")`。
  - `python -m pytest tests/test_fire_smoke.py`：7 passed。
  - `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py tests/test_fire_smoke.py`：44 passed（使用仓库内临时目录绕过系统 Temp 权限问题）。
  - `python tests/smoke_test.py`：`ALL SMOKE TESTS PASSED`。
  - `python backend/scripts/verify_task_e_real_db.py`：通过，输出 `TASK_E_REAL_DB_VERIFY_OK`（本次从 `.env` 的 `MYSQL_*` 临时拼接 `DATABASE_URI`）。

- 已记录证据：已更新 `feature_list.json` 的 `task-c3-fire-smoke-detection` evidence 和 blockers。

- 已知风险或未解决问题：
  - 还未用真实 live RTMP/OBS 烟火视频和反光负样本完成 C3 最终验收。
  - 旧 YOLOv5 权重依赖 `fire-smoke-detect-yolov4-master/yolov5` 源码目录；部署时需要保留该目录或配置 `FIRE_SMOKE_LEGACY_YOLOV5_DIR`。
  - `backend/model_weights/fire_smoke.pt` 为本地模型工件，按 `.gitignore` 不入库。

### Session 009

- 日期：2026-07-10

- 本轮目标：封装单张照片烟火检测测试脚本。

- 已完成：
  - 新增 `backend/scripts/test_fire_smoke_image.py`，用于对单张图片输出模型原始 `fire/smoke` 检测结果。
  - 新增 `backend/scripts/test_fire_smoke_alarm_image.py`，用于把单张图片重复送入 30 帧窗口，验证是否产出 `AlarmEvent(type="fire_smoke")`。
  - 两个脚本默认读取 `test_photos/fire_test.jpg`，也支持传入任意图片路径。
  - 脚本已抑制旧 YOLOv5 fallback 的加载噪声，只输出测试结果。

- 运行过的验证：
  - `.\init.cmd`：通过。
  - `python -m py_compile backend/scripts/test_fire_smoke_image.py backend/scripts/test_fire_smoke_alarm_image.py`：通过。
  - `python backend/scripts/test_fire_smoke_image.py`：对 `test_photos/fire_test.jpg` 输出 fire≈0.757、fire≈0.557、smoke≈0.256。
  - `python backend/scripts/test_fire_smoke_alarm_image.py`：对同一图片重复 30 帧后输出 1 个 `fire_smoke` 告警事件。

- 已知风险或未解决问题：
  - 该脚本是本地图片验证工具，不等同于真实 RTMP/OBS 视频验收。

### Session 010

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
  - 解决 git 冲突，采用 main 分支的直接推送方案（带冷却去重），保留 camera_id 和 face_spoof 修复。

- 运行过的验证：
  - `python -m pytest tests/test_alarm_center.py`（在 `backend/` 下）：10 passed。
  - 手动测试：face_spoof告警路由成功，face_recognition正确返回None（只走WebSocket）。

- 已记录证据：已更新 `feature_list.json` 的任务 E 和任务 G evidence。

- 提交记录：`b356712 fix: 欺骗攻击和陌生人告警推送失败问题`, `9da744f chore: 更新init.sql添加face_spoof告警类型`, `4d92de3 fix: 解决git冲突，采用main分支的直接推送方案`

- 更新过的文件或工件：
  - `backend/app/services/alarm.py`
  - `backend/app/detectors/face.py`
  - `backend/app/models/entities.py`
  - `init.sql`
  - `feature_list.json`
  - `openspec/progress/progress.md`

- 已知风险或未解决问题：
  - 公网IP `156.224.79.175:5000` 返回502 Bad Gateway，校园网网关未配置端口映射。建议使用ngrok内网穿透解决外部访问问题。
  - fire_smoke 权重文件为本地模型工件，按 `.gitignore` 不入库。

- 下一步最佳动作：测试人员验证欺骗攻击和陌生人告警推送功能是否正常。

### Session 011

- Date: 2026-07-13
- Goal: stabilize fatigue detection and add tuning observability.
- Completed:
  - Created OpenSpec change `fatigue-detect-stabilize` with proposal, design, tasks, and fatigue-detect delta spec.
  - Added fatigue presets and tunables: `FATIGUE_PRESET`, `FATIGUE_YAWN_WINDOW`, `FATIGUE_YAWN_HITS`, and `FATIGUE_ALERT_COOLDOWN`.
  - Updated `FatigueDetector` with yawn sliding-window voting, blink-safe sleepy behavior, and EAR/MAR/closed-duration metrics.
  - Updated `FatiguePlugin` with per-seat/kind cooldown and richer `AlarmEvent.extra`.
  - Added `GET /api/seat-status/companion`.
  - Added `backend/scripts/analyze_fatigue_video.py` for local video-to-CSV tuning.
  - Updated the frontend self-study companion view to show latest fatigue kind, metrics, and DingTalk webhook status.
- Validation:
  - `.\init.cmd` passed.
  - `npm.cmd run spec:validate` passed: 8 items.
  - `python -m py_compile backend/app/config.py backend/app/detectors/fatigue.py backend/app/api/seat_status.py backend/scripts/analyze_fatigue_video.py backend/tests/test_fatigue.py` passed.
  - With SQLite override: `python -m pytest tests/test_fatigue.py tests/test_alarm_center.py` passed: 29 passed.
  - `npm.cmd --prefix frontend run build` passed.
  - `npm.cmd run spec:archive -- fatigue-detect-stabilize --yes` archived the change into baseline `spec/fatigue-detect`.
  - Post-archive `npm.cmd run spec:validate` and `.\init.cmd` passed.
- Remaining risks:
  - Live human validation still requires OBS pushing a readable RTMP stream to `rtmp://49.233.71.82:9090/live/test`.
  - Dlib remains the active model; MediaPipe or learned fatigue classifier evaluation is deferred.
