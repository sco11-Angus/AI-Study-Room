# progress

## 当前已验证状态

- 仓库根目录：`E:\软件\小学期实训`

- 标准启动路径：shell-capable 环境运行 `./init.sh`；本 Windows 主机 `bash` 是 WSL shim 且未安装发行版，使用 PowerShell 等价检查。

- 标准验证路径：
  - `python backend/scripts/verify_task_e_real_db.py`（在仓库根目录，使用 `.env` 中 `DATABASE_URI` 验证真实 MySQL 任务 E 链路）
  - `python -m pytest tests/test_fatigue.py tests/test_alarm_center.py tests/test_face.py tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py`（在 `backend/` 下）
  - `python tests/smoke_test.py`（在 `backend/` 下）
  - PowerShell-equivalent `init.sh` smoke

- 当前最高优先级未完成功能：`feature_list.json` 中暂无未完成项；任务 B 疲劳检测与自习伴侣已完成。

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

### Session 005

- 日期：2026-07-09

- 本轮目标：完成任务 B「疲劳检测 + 自习伴侣」。

- 已完成：
  - 保护当前脏工作区并从最新 `origin/main` 创建 `codex/task-b-fatigue-companion`。
  - 修复 `init.sh` 仍检查旧 `openspec/specs/PRD.md` 的基础 blocker，改为检查根目录 `PRD.md`。
  - 实现 `backend/app/detectors/fatigue.py`：EAR/MAR 状态机、内嘴 60-67 MAR 索引修正、Dlib 68 点关键点插件、按 studying 座位激活、resting/idle 热禁用并清理计时。
  - 实现 `POST /api/seat-status`：校验、seat region 限制、`user_id + region_id` 应用层 upsert、通过当前 `StreamScheduler.engine` 热更新 fatigue 插件。
  - 在 `backend/run.py` 注册 `FatiguePlugin`，并在 `StreamScheduler` 暴露只读 `engine` 属性。
  - 修复回归中暴露的基础问题：重复 `Guard` ORM、`AlarmService` 缺失 helper、`FaceDetector` mock fallback、重复 WebSocket 路由注册、本地默认 DB URI。
  - 新增 `backend/tests/test_fatigue.py` 覆盖疲劳状态机、弱提醒事件、resting 禁用、自习状态 API 和多座位启停。

- 运行过的验证：
  - `python -m py_compile backend/app/detectors/fatigue.py backend/app/api/seat_status.py backend/app/models/entities.py backend/app/config.py backend/app/services/alarm.py backend/app/detectors/face.py backend/app/__init__.py backend/app/stream/scheduler.py backend/run.py backend/tests/test_fatigue.py`
  - `python -m pytest tests/test_fatigue.py tests/test_alarm_center.py tests/test_face.py tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py`（在 `backend/` 下）：41 passed。
  - `python tests/smoke_test.py`（在 `backend/` 下）：通过。
  - PowerShell-equivalent `init.sh` smoke：通过，15 个 markdown 文档。
  - `bash ./init.sh`：失败，本 Windows 主机无 WSL 发行版。

- 已记录证据：已更新 `feature_list.json` 的 `task-b-fatigue-companion` 条目。

- 提交记录：待提交。

- 更新过的文件或工件：
  - `backend/app/detectors/fatigue.py`
  - `backend/app/api/seat_status.py`
  - `backend/app/stream/scheduler.py`
  - `backend/run.py`
  - `backend/tests/test_fatigue.py`
  - `backend/app/models/entities.py`
  - `backend/app/config.py`
  - `backend/app/services/alarm.py`
  - `backend/app/detectors/face.py`
  - `backend/app/__init__.py`
  - `init.sh`
  - `feature_list.json`
  - `openspec/progress/progress.md`
  - `openspec/progress/claude-progress.md`

- 已知风险或未解决问题：
  - 本机 `bash ./init.sh` 仍受 WSL 环境限制，PowerShell 等价 smoke 已通过。
  - 疲劳检测真实运行需要 `backend/model_weights/shape_predictor_68_face_landmarks.dat` 或设置 `MODEL_DIR`。
  - 真实私有端弱提醒 UI/推送仍需后续与前端/小程序联调。

- 下一步最佳动作：配置 Dlib 关键点模型后启动后端，联调真实摄像头帧下的 studying/resting 状态切换和 level=0 fatigue 记录。


### Session 006

- Date: 2026-07-09
- Goal: prepare a fast Docker dev/runtime path for Task B fatigue verification.
- Completed:
  - Reused existing dlib/cv2 backend image by tagging it as `ai-study-room-backend-env:dev`.
  - Updated `backend/Dockerfile` into a stable dependency image with apt/pip mirrors and future ffmpeg support.
  - Updated `deploy/docker-compose.yml` so backend uses the stable image, mounts `../backend` and `../backend/model_weights`, and runs `gunicorn --reload`.
  - Added `backend/.dockerignore`.
  - Added `backend/scripts/seed_demo_fatigue.py`.
  - Made `python-dotenv` optional for the reused image.
  - Made local SQLite init create tables automatically.
  - Fixed RTMP pull URLs by removing the ` live=1` suffix.
  - Corrected Docker runtime and demo seed data to use cloud RTMP server `49.233.71.82:9090`.
  - Fixed `AlarmService` persistence so legitimate `camera_id=0` values are not converted to `NULL`.
  - Pulled latest frontend Dashboard/VideoPlayer/CanvasDraw/RegionConfig files from `origin/main`.
  - Implemented `/api/cameras` database-backed response and adjusted frontend stream URL resolution for cloud RTMP -> HTTP-FLV playback.
- Validation:
  - `python -m py_compile backend/app/config.py backend/app/models/database.py backend/app/stream/scheduler.py backend/scripts/seed_demo_fatigue.py` passed.
  - `docker compose -f deploy/docker-compose.yml up -d --no-build --force-recreate backend` recreated backend without image rebuild.
  - `docker compose exec backend python scripts/seed_demo_fatigue.py --status studying` seeded demo user/camera/seat.
  - `POST /api/seat-status` returned success for `user_id=1001`, `region_id=5`, `status=studying`.
  - Container check confirmed dlib, cv2, and `shape_predictor_68_face_landmarks.dat` are available.
  - `linuxserver/ffmpeg:latest` pushed a temporary local test stream during debugging; after user clarification, runtime config was changed to pull from the cloud RTMP server.
  - Container check confirmed `Config.RTMP_SERVER=49.233.71.82`, scheduler URL `rtmp://49.233.71.82:9090/live/test`, and DB camera URL `rtmp://49.233.71.82:9090/live/test`.
  - Backend logs showed cloud stream pull success and persisted `level=0` fatigue alarms with `extra.kind=sleepy`.
  - Direct container verification after the `camera_id=0` fix persisted a debug fatigue alarm with `camera_id=0`.
  - `python -m pytest tests/test_alarm_center.py tests/test_fatigue.py` passed: 14 passed.
  - `GET /api/cameras` returned camera `0` with cloud RTMP stream URL.
  - `npm.cmd run build` in `frontend/` passed.
- Remaining risks:
  - Old local SQLite fatigue rows created before the `camera_id=0` fix still have `camera_id=NULL`; new rows persist `camera_id=0`.
  - Clean image rebuild still depends on network access; the current runtime uses the tagged local image.
  - `bash ./init.sh` remains blocked on this Windows host; `./init.sh` also could not run directly from PowerShell in this session due permission/WSL behavior.

### Session 007

- Date: 2026-07-10
- Goal: make studying-seat fatigue alerts use the existing DingTalk notification flow.
- Completed:
  - Added `Config.FATIGUE_ALERT_LEVEL`, defaulting to `1`.
  - Updated `FatiguePlugin` so sleepy/yawn events use the configured level and include it in `extra`.
  - Set `FATIGUE_ALERT_LEVEL=1` in `deploy/docker-compose.yml`.
  - Added tests proving level-1 fatigue alarms notify while level-0 private reminders still stay local.
- Validation:
  - `python -m py_compile backend/app/config.py backend/app/detectors/fatigue.py backend/tests/test_fatigue.py backend/tests/test_alarm_center.py` passed.
  - From `backend/`: `python -m pytest tests/test_fatigue.py tests/test_alarm_center.py` passed: 15 passed.
  - `docker compose -f deploy/docker-compose.yml up -d --no-build --force-recreate backend` recreated backend.
  - Container config check confirmed `FATIGUE_ALERT_LEVEL=1` and `DINGTALK_WEBHOOK_SET=False`.
  - Container smoke generated fatigue alarm id `48`; database check showed `status=notified`, `level=1`, and a `primary` notification log.
- Remaining risks:
  - Real DingTalk external delivery is not verified because `DINGTALK_WEBHOOK` is currently unset.
  - Cloud RTMP stream timed out in the latest backend log, so camera-based live fatigue verification also depends on pushing a live stream to `rtmp://49.233.71.82:9090/live/test`.

### Session 008

- Date: 2026-07-10
- Goal: complete frontend danger-zone drawing to intrusion alarm end-to-end evidence.
- Completed:
  - Restored `/api/regions` CRUD persistence and validation for frontend drawn regions.
  - Restored `IntrusionPlugin` and registered it in `backend/run.py`.
  - Added repeatable verification script `backend/scripts/verify_intrusion_e2e.py`.
  - Created danger zone `id=6` through `POST /api/regions`; backend logs showed `[intrusion] active danger zones: [6]`.
  - Simulated a person box entering that saved polygon through the intrusion plugin and persisted alarm `id=103`.
- Validation:
  - `GET /api/regions?camera_id=0` returned danger zone `id=6`.
  - `docker compose exec backend PYTHONPATH=/app python scripts/verify_intrusion_e2e.py` produced `alarm_id=103`, `type=intrusion`, `status=notified`.
  - `GET /api/alarms?status=notified` returned alarm `id=103` with snapshot URL and person box evidence.
  - Snapshot file `/app/snapshots/alarm_6_intrusion_1783691102938.jpg` exists.
  - `python -m py_compile backend/scripts/verify_intrusion_e2e.py backend/app/detectors/intrusion.py backend/app/api/regions.py backend/run.py` passed.
  - `python -m pytest tests/test_intrusion.py tests/test_alarm_center.py` passed: 9 passed.
  - `npm.cmd --prefix frontend run build` passed.
- Evidence recorded:
  - Added completed `task-b-intrusion-e2e` entry to `feature_list.json`.
  - Updated `openspec/progress/claude-progress.md`.
- Remaining risks:
  - Cloud RTMP `rtmp://49.233.71.82:9090/live/test` was unavailable during this verification window (`opened False/read False`), so the final person-entry trigger used a deterministic mocked person box rather than a live camera frame.
  - Direct `npm.cmd run build` inside the Chinese-character frontend path hit a Vite/Rollup path issue; repo-root `npm.cmd --prefix frontend run build` passed.

### Session 009

- Date: 2026-07-10
- Goal: implement simple reserved-seat identity checking.
- Completed:
  - Extended `IntrusionPlugin` to load active studying seat regions from `seat_status` joined with `region type=seat`.
  - When a person enters an active reserved seat, the plugin crops the person box, calls `FaceMatcher`, and compares the result with `member:<seat_status.user_id>`.
  - Matching reserved user produces no alarm.
  - Mismatched user or `stranger` produces `AlarmEvent(type=occupy)` with `extra.kind=unauthorized_seat`.
  - `POST /api/seat-status` now hot-updates both `fatigue` and `intrusion`, so seat reservation/status changes are effective without backend restart.
- Validation:
  - `python -m py_compile backend/app/detectors/intrusion.py backend/app/api/seat_status.py backend/tests/test_intrusion_identity.py backend/tests/test_fatigue.py` passed.
  - `python -m pytest tests/test_intrusion.py tests/test_intrusion_identity.py tests/test_fatigue.py tests/test_alarm_center.py` passed: 20 passed.
  - Backend container logs showed `[intrusion] active reserved seats: [5]`.
- Evidence recorded:
  - Added completed `task-b-seat-identity-mvp` entry to `feature_list.json`.
- Remaining risks:
  - Real identity matching requires `backend/model_weights/dlib_face_recognition_resnet_model_v1.dat` and enrolled `member.feature` records. Current container logs show the face recognition model is missing, so live checks fall back to `stranger` until that model and member data are available.
  - Cloud RTMP live stream remains dependent on OBS/cloud availability.
