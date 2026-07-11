# Progress

## Session 2026-07-06

- Goal: initialize the local project and push markdown documents to `sco11-Angus/AI-Study-Room`.
- Verified baseline: `pwd` confirmed `E:\软件\小学期实训`.
- Initial blockers found:
  - The directory was not a Git repository.
  - `feature_list.json` was missing.
  - `init.sh` was missing.
- Actions in progress:
  - Added `feature_list.json` as the feature status source of truth.
  - Added `init.sh` as the standard smoke-test entry point.
- Validation run:
  - PowerShell-equivalent smoke test passed: required files present and markdown docs found.
  - `git init -b main` completed.
  - `git fetch origin main` completed.
  - `git merge origin/main --allow-unrelated-histories --no-edit` completed without conflicts.
  - `git push -u origin main` completed.
- Notes:
  - `bash ./init.sh` could not run on this Windows host because `bash.exe` is the WSL shim and no WSL distribution is installed.
  - Added `.gitattributes` so `init.sh` keeps LF endings when checked out in shell-capable environments.
- Result:
  - Markdown documentation and initialization metadata were pushed to `origin/main`.
  - Remote pre-existing `系统设计说明书.md` was preserved.

## Session 2026-07-06 README

- Goal: create and push a complete `README.md`.
- Baseline:
  - `pwd` confirmed `E:\软件\小学期实训`.
  - `feature_list.json` showed project initialization already completed.
  - PowerShell-equivalent smoke test passed before editing.
- Actions:
  - Created `README.md` from `PRD.md` and `系统设计说明书.md`.
  - Documented project positioning, core modules, architecture, performance goals, repository documents, validation entry, and GitHub URL.
  - Updated `feature_list.json` with the completed `readme-doc` feature.
- Validation:
  - PowerShell-equivalent smoke test passed after README creation.
- Remaining risks:
  - `bash ./init.sh` still cannot run on this Windows host because no WSL distribution is installed.

## Session 2026-07-08 Task E

- Goal: complete task E, "Alarm center + DingTalk close loop".
- Baseline:
  - Read `openspec/progress/progress.md`, `feature_list.json`, recent git history, task E docs, collaboration order, PRD, database design, system design §7/§10.2, and current backend contracts.
  - Ran `./init.sh` from PowerShell; it returned exit code 0 with no output on this host.
  - `bash ./init.sh` still fails because `bash.exe` is the Windows WSL shim and no WSL distribution is installed.
- Actions:
  - Reworked `detectors/base.py` `AlarmEvent` to match task E: type, region_id, camera_id, ts, level, snapshot_url, face_match, extra. Kept legacy confidence/snapshot/face_crop compatibility for existing B/C/D tests.
  - Extended SQLAlchemy models for `alarm_event.camera_id`, `fight`, `extra`, `Guard`, notification log guard FK, and indexes.
  - Implemented `AlarmService.raise_alarm()` with region/type cooldown dedup, snapshot persistence, intrusion/occupy face matching fallback, DB persistence, level=0 private-only behavior, level>=1 WebSocket broadcast and DingTalk notification trigger.
  - Implemented `/ws/alarms` registration and broadcast helper.
  - Implemented `DingTalkNotifier.notify()`, `confirm()`, and `_escalate()` with timers, notification_log writes, status transitions, confirmation ack timestamps, and safe no-webhook local behavior.
  - Implemented `GET /api/alarms?status=`, `POST /api/alarms/{id}/confirm`, and snapshot serving.
  - Updated the inference engine to pass complete `AlarmEvent` objects into the alarm service so fight level/extra/camera_id are preserved.
  - Fixed `Config.SNAPSHOT_DIR` to resolve to `backend/snapshots` by default.
  - Added `backend/tests/test_alarm_center.py`.
  - Fixed a pre-existing smoke blocker by restoring `StreamScheduler` ring buffer `maxlen=5` to match `backend/tests/smoke_test.py`.
  - Updated `init.sh` required file paths to match the current repository layout.
- Validation:
  - Installed missing local test dependencies after the user enabled the proxy: `pytest`, `SQLAlchemy`, `flask-cors`, `flask-sock`, `flasgger`, `requests`, `simple-websocket`.
  - `python -m py_compile backend/app/detectors/base.py backend/app/models/entities.py backend/app/services/alarm.py backend/app/services/dingtalk.py backend/app/api/ws.py backend/app/api/alarms.py backend/app/__init__.py backend/app/stream/engine.py backend/app/config.py backend/tests/test_alarm_center.py` passed.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py` passed: 27 passed, 5 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed.
  - PowerShell-equivalent `init.sh` smoke passed: required files present and 16 markdown docs found.
  - `python -m json.tool feature_list.json` passed.
- Evidence recorded:
  - Added completed `alarm-center-dingtalk-close-loop` entry to `feature_list.json`.
  - Updated `openspec/progress/progress.md` with current validated state and Session 003.
- Remaining risks:
  - Real DingTalk webhook is not configured in this repo; local behavior records notification logs without external send.
  - Dlib model files are absent locally; intrusion/occupy face matching safely falls back to `stranger` until models are provided.
  - `bash ./init.sh` is still blocked on this Windows host by missing WSL distribution; shell-capable environments should run the corrected `init.sh`.
  - `git status --short` emits permission warnings for generated `.pytest_cache` directories, but they are not part of the intended commit.

## Session 2026-07-08 Task E Real DB

- Goal: verify task E against the user's real MySQL database configured in `.env`.
- Baseline:
  - `.env` contains a `DATABASE_URI` using `mysql+pymysql`.
  - First connection attempt reached MySQL but failed with invalid credentials; after the user corrected `.env`, SQLAlchemy connected successfully to `study_room`.
- Actions:
  - Added `backend/scripts/verify_task_e_real_db.py` as a repeatable real-database verification script.
  - The script loads `.env`, supports both `KEY=` and PowerShell `$env:KEY=` syntax, connects to the configured database, applies task-E-required nullable columns, seeds minimal camera/region/primary guard/leader guard rows, and verifies confirm/escalate/private-only alarm behavior.
  - Updated `backend/app/config.py` to load the repo `.env` at startup.
  - Updated `backend/requirements.txt` with `PyMySQL` for `mysql+pymysql://...` URIs.
  - Updated `init.sql` to a task-E-compatible schema with nullable `alarm_event.confirmed_at` and `notification_log.ack_at`.
  - Updated `backend/tests/smoke_test.py` to mask credentials when printing `DATABASE_URI`.
- Validation:
  - `python backend/scripts/verify_task_e_real_db.py` passed against real MySQL. Latest run wrote and verified alarm IDs: confirmed fight `7`, escalated intrusion `8`, private fatigue `9`.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py` passed: 27 passed, 5 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed and printed a masked database URI.
- Notes:
  - The script does not call a real DingTalk webhook; it uses empty webhook values and verifies local notification logs/status transitions.
  - The user pasted an alternate SQL draft. For task E compatibility, any final SQL must keep `alarm_event.confirmed_at` and `notification_log.ack_at` nullable because those timestamps are only available after confirmation.

## Session 2026-07-09 Task B Fatigue Companion

- Goal: implement Task B fatigue detection and study companion from latest `origin/main`.
- Baseline:
  - Protected pre-existing dirty work with a stash before switching branches.
  - Created `codex/task-b-fatigue-companion` from `origin/main`.
  - `bash ./init.sh` is still blocked on this Windows host because `bash.exe` is the WSL shim and no WSL distribution is installed.
- Actions:
  - Implemented `FatigueDetector` EAR/MAR detection with closed-eye duration reset behavior and yawn detection.
  - Corrected inner-mouth MAR indexing for landmarks 60-67.
  - Added `FatiguePlugin` with Dlib landmark loading, active studying-seat reload, per-region state, hot updates, and `AlarmEvent(type="fatigue", level=0)` output.
  - Implemented `POST /api/seat-status` validation, seat-only region checks, application-level upsert, and live fatigue hot reload through `StreamScheduler.engine`.
  - Registered `FatiguePlugin` in `backend/run.py`.
  - Fixed baseline regressions uncovered by validation: `init.sh` PRD path, duplicate `Guard` ORM declaration, missing `AlarmService` helper methods, `FaceDetector` test fallback, duplicate WebSocket route registration, and local default DB URI fallback.
  - Added `backend/tests/test_fatigue.py`.
- Validation:
  - `python -m py_compile backend/app/detectors/fatigue.py backend/app/api/seat_status.py backend/app/models/entities.py backend/app/config.py backend/app/services/alarm.py backend/app/detectors/face.py backend/app/__init__.py backend/app/stream/scheduler.py backend/run.py backend/tests/test_fatigue.py` passed.
  - From `backend/`: `python -m pytest tests/test_fatigue.py tests/test_alarm_center.py tests/test_face.py tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py` passed: 41 passed, 23 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed.
  - PowerShell-equivalent `init.sh` smoke passed: 15 markdown docs.
  - `bash ./init.sh` failed due to missing WSL distribution.
- Evidence recorded:
  - Added completed `task-b-fatigue-companion` entry to `feature_list.json`.
  - Updated `openspec/progress/progress.md` with Session 005.
- Remaining risks:
  - Runtime fatigue detection requires `backend/model_weights/shape_predictor_68_face_landmarks.dat` or a valid `MODEL_DIR`.
  - Private weak-reminder frontend/mobile delivery still needs real-device integration.

## Session 2026-07-09 Task B Docker Runtime

- Goal: rebuild the backend runtime for a minimal camera-based fatigue verification path while avoiding slow daily Docker rebuilds.
- Baseline:
  - Current branch: `codex/task-b-fatigue-companion`.
  - Existing backend image `deploy-backend:latest` already contained dlib/cv2, so it was tagged as `ai-study-room-backend-env:dev` to avoid another slow network build.
  - The new Dockerfile now uses apt/pip mirrors and separates stable dependency layers from source code.
- Actions:
  - Updated `backend/Dockerfile` into a stable backend environment image with Tsinghua apt/pip mirrors and dlib/OpenCV runtime dependencies, including ffmpeg for future rebuilds.
  - Added `backend/.dockerignore` so model weights, snapshots, caches, and local DB/log files are not copied into image builds.
  - Updated `deploy/docker-compose.yml` so backend uses `image: ai-study-room-backend-env:dev`, mounts `../backend` and `../backend/model_weights`, and runs `gunicorn --reload`.
  - Made `python-dotenv` optional in `backend/app/config.py` because the reused runtime image did not include it.
  - Made local SQLite startup call `Base.metadata.create_all()` in `backend/app/models/database.py` so the demo container can boot from an empty local DB.
  - Added `backend/scripts/seed_demo_fatigue.py` for repeatable local camera/user/seat setup.
  - Fixed RTMP pull URL generation in `backend/app/stream/scheduler.py` by removing the ` live=1` suffix that prevented OpenCV from opening the RTMP stream.
  - Corrected the Docker dev runtime back to the real cloud RTMP server `49.233.71.82:9090`; the local nginx-rtmp address is not the user's verification target.
  - Fixed `AlarmService` persistence so legitimate `camera_id=0` values are not converted to `NULL`.
  - Pulled the latest frontend files from `origin/main` for Dashboard, VideoPlayer, CanvasDraw, and RegionConfig.
  - Implemented the backend `/api/cameras` query so the refreshed frontend can get real camera stream data instead of an empty array.
  - Updated the frontend stream URL resolver to convert cloud RTMP camera URLs into cloud HTTP-FLV playback URLs.
- Validation:
  - `python -m py_compile backend/app/config.py backend/app/models/database.py backend/app/stream/scheduler.py backend/scripts/seed_demo_fatigue.py` passed.
  - `docker compose -f deploy/docker-compose.yml up -d --no-build --force-recreate backend` recreated backend without rebuilding the image.
  - `docker compose exec backend python scripts/seed_demo_fatigue.py --status studying` seeded user `1001`, camera `0`, region `5`, and `studying` state.
  - `POST http://localhost:5000/api/seat-status` returned success for `user_id=1001`, `region_id=5`, `status=studying`.
  - Container check confirmed `dlib 19.24.9`, `cv2 4.9.0`, and `/app/model_weights/shape_predictor_68_face_landmarks.dat` exists.
  - `linuxserver/ffmpeg:latest` pushed a 75 second local test stream during debugging; after user clarification, runtime config was changed to pull from the cloud RTMP server.
  - Container check confirmed `Config.RTMP_SERVER=49.233.71.82`, scheduler URL `rtmp://49.233.71.82:9090/live/test`, and DB camera URL `rtmp://49.233.71.82:9090/live/test`.
  - Backend logs showed cloud stream pull success and persisted `level=0` fatigue alarms with `extra.kind=sleepy`.
  - Direct container verification after the `camera_id=0` fix persisted a debug fatigue alarm with `camera_id=0`.
  - `python -m pytest tests/test_alarm_center.py tests/test_fatigue.py` passed: 14 passed.
  - `GET http://localhost:5000/api/cameras` returned camera `0` with `rtmp://49.233.71.82:9090/live/test`.
  - `npm.cmd run build` in `frontend/` passed.
- Remaining risks:
  - Old local SQLite fatigue rows created before the `camera_id=0` fix still have `camera_id=NULL`; new rows persist `camera_id=0`.
  - The reused `ai-study-room-backend-env:dev` image lacks the `ffmpeg` CLI; the Dockerfile includes ffmpeg, but a clean rebuild still depends on network access to Docker Hub and Debian/PyPI mirrors.
  - Face recognition model `dlib_face_recognition_resnet_model_v1.dat` is still absent; this affects face matching, not fatigue landmark detection.
  - `./init.sh` could not run directly from this PowerShell session due OS permission/WSL shim behavior.

## Session 2026-07-10 Fatigue DingTalk Path

- Goal: route studying-seat fatigue alerts into the existing DingTalk notification flow.
- Completed:
  - Added configurable `FATIGUE_ALERT_LEVEL` with default `1`.
  - Updated `FatiguePlugin` so sleepy/yawn events produce level-1 fatigue alarms by default.
  - Set `FATIGUE_ALERT_LEVEL=1` in Docker compose.
  - Added regression coverage for level-1 fatigue notification behavior.
- Validation:
  - `python -m py_compile backend/app/config.py backend/app/detectors/fatigue.py backend/tests/test_fatigue.py backend/tests/test_alarm_center.py` passed.
  - From `backend/`: `python -m pytest tests/test_fatigue.py tests/test_alarm_center.py` passed: 15 passed.
  - Docker backend recreated without image rebuild.
  - Container check confirmed `FATIGUE_ALERT_LEVEL=1`; `DINGTALK_WEBHOOK` is not configured.
  - Smoke fatigue alarm id `48` reached `status=notified` and wrote a `primary` notification log, verifying the DingTalk notifier path up to the configured-webhook boundary.
- Remaining risks:
  - Real DingTalk external send still requires setting `DINGTALK_WEBHOOK` before starting Docker.
  - Latest backend log showed cloud RTMP timeout, so live camera verification requires an active stream on `rtmp://49.233.71.82:9090/live/test`.

## Session 2026-07-10 Intrusion E2E Evidence

- Goal: complete and record frontend danger-zone drawing to intrusion alarm evidence.
- Completed:
  - Restored database-backed `/api/regions` CRUD with validation and intrusion hot reload.
  - Restored `IntrusionPlugin`, `PersonDetector`, per-region `IntrusionDetector` runtime loading, and shared person-box context writes.
  - Registered `IntrusionPlugin` in `backend/run.py`.
  - Added `backend/scripts/verify_intrusion_e2e.py` as repeatable evidence for region config -> person entry -> intrusion alarm persistence.
- Validation:
  - `POST /api/regions` created danger zone `id=6` for `camera_id=0` with polygon `[[0,0],[640,0],[640,360],[0,360]]`.
  - `GET /api/regions?camera_id=0` returned the saved danger zone, proving the frontend draw/save API shape persists.
  - Backend logs showed `registered detector intrusion` and `[intrusion] active danger zones: [6]`, proving runtime hot reload consumed the saved region.
  - `PYTHONPATH=/app python scripts/verify_intrusion_e2e.py` in the backend container produced alarm `id=103`, `type=intrusion`, `region_id=6`, `camera_id=0`, `status=notified`, with a simulated person box inside the saved polygon.
  - `GET /api/alarms?status=notified` returned alarm `id=103` with `snapshot_url=/api/alarms/snapshots/alarm_6_intrusion_1783691102938.jpg` and `face_match=stranger`.
  - Container check confirmed `/app/snapshots/alarm_6_intrusion_1783691102938.jpg` exists.
  - `python -m py_compile backend/scripts/verify_intrusion_e2e.py backend/app/detectors/intrusion.py backend/app/api/regions.py backend/run.py` passed.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_alarm_center.py` passed: 9 passed.
  - `npm.cmd --prefix frontend run build` passed.
- Remaining risks:
  - Live cloud RTMP `rtmp://49.233.71.82:9090/live/test` was unavailable during this verification window; direct container OpenCV returned `opened False/read False`, so the person-entry trigger used a deterministic mocked person box instead of a live human camera frame.
  - Direct `npm.cmd run build` from inside the Chinese-character `frontend` path failed with a Vite/Rollup absolute-path emitted asset issue; running from repo root with `npm.cmd --prefix frontend run build` passed.

## Session 2026-07-10 Seat Identity MVP

- Goal: implement the simple version of reserved-seat identity checking.
- Completed:
  - Extended `IntrusionPlugin` to load active studying seats from `seat_status` joined with `region type=seat`.
  - For a person entering an active reserved seat, the plugin crops the person box, calls `FaceMatcher`, and compares the result against `member:<seat_status.user_id>`.
  - Matching reserved users are allowed without alarm.
  - Mismatched users and `stranger` produce `AlarmEvent(type=occupy)` with `extra.kind=unauthorized_seat`, expected user id, actual face match, and person box.
  - `POST /api/seat-status` now hot-updates both `fatigue` and `intrusion`.
  - Added `backend/tests/test_intrusion_identity.py`.
- Validation:
  - `python -m py_compile backend/app/detectors/intrusion.py backend/app/api/seat_status.py backend/tests/test_intrusion_identity.py backend/tests/test_fatigue.py` passed.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_intrusion_identity.py tests/test_fatigue.py tests/test_alarm_center.py` passed: 20 passed.
  - Backend container logs showed `[intrusion] active reserved seats: [5]`.
- Remaining risks:
  - Real identity matching requires `backend/model_weights/dlib_face_recognition_resnet_model_v1.dat` and enrolled `member.feature` records. Current container logs show the face recognition model is missing, so live checks fall back to `stranger` until that model and member data are available.
  - Cloud RTMP live stream remains dependent on OBS/cloud availability.

## Session 2026-07-11 Face Model Runtime Test

- Goal: verify the newly placed Dlib face-recognition model and prepare live reserved-seat identity testing.
- Completed:
  - Confirmed `backend/model_weights/dlib_face_recognition_resnet_model_v1.dat` exists on the Windows host.
  - Restarted the Docker backend so the mounted model directory is reloaded.
  - Verified the model is visible inside the backend container at `/app/model_weights/dlib_face_recognition_resnet_model_v1.dat`.
- Validation:
  - Host model check showed size `22466066`.
  - Container model check showed `exists=True`, `size=22466066`.
  - Container `FaceMatcher()` check returned `dlib_loaded=True`, `threshold=0.35`.
  - Backend logs showed `[face] FaceMatcher 已初始化（Dlib 模型加载完成）` and `[face] FaceDetector 已就绪`.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_intrusion_identity.py tests/test_fatigue.py tests/test_alarm_center.py` passed: 20 passed.
- Remaining risks:
  - Current Docker database has active seat status `(region_id=5, user_id=1001, status=studying)`, but `member` is empty, so live identity checks will still match as `stranger` until user `1001` is enrolled.
  - Direct container OpenCV check against `rtmp://49.233.71.82:9090/live/test` returned `opened=False`, `read=False`; live camera testing still needs an active cloud RTMP stream.
  - `bash ./init.sh` remains blocked by the local Windows WSL-shim/no-distro environment.
