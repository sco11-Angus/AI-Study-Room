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

## Session 2026-07-09 Pull Merge Push

- Goal: pull latest `origin/main`, keep the merged code launchable, and push the complete result.
- Baseline:
  - `pwd` confirmed `D:\1\大二暑期实训\App`.
  - PowerShell could not resolve `git` from PATH, but Git was available at `C:\Program Files\Git\cmd\git.exe`.
  - Local `main` was behind `origin/main` by 2 commits.
- Actions:
  - Pulled `origin/main` with a fast-forward update to `a906fe8`.
  - Fixed a post-pull smoke blocker in `backend/app/__init__.py` by removing the duplicate `ws.register_ws_routes(sock)` call that registered `/ws/alarms` twice.
  - Updated `feature_list.json` with the verification evidence for the route-registration fix.
- Validation:
  - `./init.sh` returned exit code 0 from PowerShell.
  - From `backend/`: `python tests/smoke_test.py` passed with `ALL SMOKE TESTS PASSED`.
- Remaining risks:
  - This host's PowerShell PATH still does not expose `git`; use `C:\Program Files\Git\cmd\git.exe` directly or add it to PATH.
  - The existing `bash ./init.sh` WSL-distribution blocker remains unchanged.

## Session 2026-07-09 Task E DingTalk Real Integration Prep

- Goal: prepare task E for real DingTalk ActionCard delivery and button confirmation.
- Baseline:
  - `DINGTALK_WEBHOOK` in `.env` was verified with a real DingTalk text message; DingTalk returned `errcode=0`.
  - `bash ./init.sh` still fails on this Windows host because no WSL distribution is installed.
  - Pre-change focused baseline passed: from `backend/`, `python -m pytest tests/test_alarm_center.py` passed: 5 passed.
- Actions:
  - Added config support for `DINGTALK_SECRET`, `DINGTALK_LEADER_WEBHOOK`, `DINGTALK_LEADER_SECRET`, and `PUBLIC_BASE_URL`.
  - Updated `DingTalkNotifier` to append DingTalk signed webhook parameters when a secret is configured.
  - Updated ActionCard payloads to use `PUBLIC_BASE_URL` for snapshot and confirm URLs when configured.
  - Kept the word `告警` in ActionCard content so keyword-secured DingTalk robots can accept the card.
  - Added `GET /api/alarms/{id}/confirm` as a browser-friendly confirmation endpoint for DingTalk ActionCard buttons while preserving the existing POST API.
  - Added tests for signed webhook URL generation, public confirm URL generation, and GET confirmation behavior.
- Validation:
  - From `backend/`: `python -m py_compile app/config.py app/services/dingtalk.py app/api/alarms.py tests/test_alarm_center.py` passed.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py` passed: 28 passed, 7 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
  - `python backend/scripts/verify_task_e_real_db.py` passed against real MySQL. Latest run wrote and verified alarm IDs: confirmed fight `16`, escalated intrusion `17`, private fatigue `18`.
  - Real DingTalk ActionCard smoke send passed through `DingTalkNotifier`; DingTalk returned `{"errcode":0,"errmsg":"ok"}`.
- Remaining risks:
  - Full real DingTalk button confirmation still needs a public backend URL in `.env` as `PUBLIC_BASE_URL`.
  - If the robot is switched from keyword security to signing security, `.env` must also include the matching `DINGTALK_SECRET`.

## Session 2026-07-09 Task C3 Fire Smoke

- Goal: implement C task book C3, "fire/smoke detection".
- Baseline:
  - `pwd` confirmed `C:\Users\ASUS\AI-Study-Room`.
  - Recent git history showed branch `taskC_firesmoke` after merging `origin/main`.
  - `bash ./init.sh` still returned the Windows WSL "no distribution" message in this execution session; PowerShell-equivalent init smoke passed.
  - Existing `backend/app/detectors/fire_smoke.py` was incomplete and would not import.
- Actions:
  - Rebuilt `backend/app/detectors/fire_smoke.py` with `FireSmokeDetector` and `FireSmokePlugin(Detector)`.
  - Preserved the required 30-frame `FIRE_WINDOW` / `FIRE_CONF` sliding-window debounce logic.
  - Implemented YOLO weight resolution/loading in `setup()`, explicit missing/empty weight errors, fire/smoke class filtering, max-confidence extraction, and `AlarmEvent(type="fire_smoke")` output with snapshot, camera_id, ts, confidence, and metadata.
  - Registered `FireSmokePlugin()` in `backend/run.py`; the detector remains under `InferenceEngine` scheduling and does not create local threads or loops.
  - Added `backend/tests/test_fire_smoke.py` with fake YOLO output for deterministic tests.
  - Fixed narrow merge-damaged foundation blockers encountered during validation: MYSQL_* fallback and URL-encoded database credentials, duplicate `/ws/alarms` registration, duplicate `Guard` ORM class, missing `AlarmService` helpers, `FaceMatcher.encode_from_rect()` fallback for tests, and stale `init.sh` PRD path.
- Validation:
  - Installed missing local dependencies needed for validation: `SQLAlchemy`, `flask-cors`, `flask-sock`, `flasgger`, `requests`, `mysql-connector-python`, and transitive packages.
  - `python -m py_compile backend/app/services/alarm.py backend/app/detectors/face.py backend/app/models/entities.py backend/app/config.py backend/app/detectors/fire_smoke.py backend/run.py backend/tests/test_fire_smoke.py` passed.
  - From `backend/`: `python -m pytest tests/test_fire_smoke.py` passed: 6 passed.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py tests/test_fire_smoke.py` passed: 38 passed, 12 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed; database connection succeeded and `DATABASE_URI` was masked.
  - PowerShell-equivalent init smoke passed with 15 markdown docs.
- Evidence recorded:
  - Added `task-c3-fire-smoke-detection` to `feature_list.json`.
  - Updated `openspec/progress/progress.md` with Session 005 and current blockers.
- Remaining risks:
  - This host's PowerShell PATH still does not expose `git`; use `C:\Program Files\Git\cmd\git.exe` directly or add it to PATH.
  - The existing `bash ./init.sh` WSL-distribution blocker remains unchanged.
  - `backend/model_weights/fire_smoke.pt` is a 0-byte placeholder. Real YOLO/video validation requires replacing it with a trained non-empty fire/smoke weight file.
  - `bash ./init.sh` still fails in this execution session with WSL no-distribution output, despite PowerShell-equivalent smoke passing.
## Session 2026-07-09 Fire Smoke Swagger

- Goal: add Swagger documentation to the interfaces other modules use to integrate with fire/smoke detection.
- Baseline:
  - `pwd` confirmed `C:\Users\ASUS\AI-Study-Room`.
  - `feature_list.json` still marks `task-c3-fire-smoke-detection` as blocked only by the missing real non-empty YOLO weight.
  - `bash ./init.sh` still fails with the Windows WSL no-distribution message in this execution session.
- Actions:
  - Added global Swagger definitions for camera, region, alarm event, fire/smoke alarm extra metadata, and face result.
  - Added manual Swagger paths for `/ws/alarms`, `/ws/video_feed/{camera_id}`, and `/ws/face_recognition`.
  - Tagged fire/smoke integration endpoints in Swagger: `/api/cameras`, `/api/regions`, `/api/alarms`, `/api/alarms/{alarm_id}/confirm`, `/api/alarms/snapshots/{filename}`, `/ws/alarms`, and `/ws/video_feed/{camera_id}`.
  - Added endpoint descriptions explaining the fire/smoke contract: events are persisted and pushed as `AlarmEvent(type=fire_smoke)`, with confidence/window details in `extra`.
- Validation:
  - `.venv\Scripts\python.exe -m py_compile backend/app/__init__.py backend/app/api/cameras.py backend/app/api/regions.py backend/app/api/seat_status.py backend/app/api/alarms.py backend/app/api/ws.py backend/app/api/video_feed.py` passed.
  - Generated `/apispec_1.json` with a temporary `DATABASE_URI=sqlite:///:memory:` and verified `FireSmoke` is present on 11 required operations.
  - Ran `backend/tests/smoke_test.py` with temporary `DATABASE_URI=sqlite:///:memory:`; it passed with `ALL SMOKE TESTS PASSED`.
- Remaining risks:
  - Real MySQL validation was not rerun in this Swagger-only session. The local virtual environment lacks the `mysql-connector-python` driver required by a `mysql+mysqlconnector://` URI.
  - `backend/model_weights/fire_smoke.pt` remains a 0-byte placeholder, so real video/model validation is still blocked.

## Session 2026-07-10 Legacy Fire Smoke Model Graft

- Goal: graft the root `fire-smoke-detect-yolov4-master` fire/smoke model into the current detector system.
- Baseline:
  - `.\init.cmd` passed.
  - The project YOLOv4 `backup_fire/weights` file is 0 bytes.
  - The usable model is `fire-smoke-detect-yolov4-master/yolov5/best.pt`, with classes `fire` and `smoke`.
  - Modern `ultralytics.YOLO` rejects this checkpoint because it is an old YOLOv5 pickle.
- Actions:
  - Added `backend/app/detectors/legacy_yolov5.py` to load the local legacy YOLOv5 source tree, handle PyTorch `weights_only=False`, preprocess frames, run inference/NMS, and return a result object compatible with `FireSmokePlugin`.
  - Updated `FireSmokePlugin.setup()` to try current Ultralytics first, then fall back to the legacy YOLOv5 adapter.
  - Added fire/smoke legacy config knobs to `Config` and `.env.example`.
  - Copied `fire-smoke-detect-yolov4-master/yolov5/best.pt` to local gitignored `backend/model_weights/fire_smoke.pt`.
  - Added `scipy`, `tqdm`, and `mysql-connector-python` to backend requirements for legacy model loading and current MySQL URI support.
  - Added a unit test that verifies old-checkpoint fallback wiring.
- Validation:
  - `py_compile` passed for config, fire_smoke, legacy_yolov5, and fire smoke tests.
  - Real legacy checkpoint load passed; fallback model reported names `['fire', 'smoke']`.
  - Demo image inference passed on `fire-smoke-detect-yolov4-master/result/result_demo.jpg`: fire confidence about 0.662 and smoke confidence about 0.311; 30-frame debounce emitted `AlarmEvent(type=fire_smoke)`.
  - Focused fire smoke tests passed: 7 passed.
  - Related backend regression passed: 44 passed, using a repo-local pytest temp directory because the system temp pytest directory is permission-blocked.
  - Backend smoke passed with `ALL SMOKE TESTS PASSED`.
  - Real DB verification passed with `TASK_E_REAL_DB_VERIFY_OK`, using a temporary `DATABASE_URI` built from `.env` `MYSQL_*` values.
- Remaining risks:
  - Final C3 acceptance still needs live RTMP/OBS fire-smoke video and negative reflection footage.
  - Deployment must keep `fire-smoke-detect-yolov4-master/yolov5` available or configure `FIRE_SMOKE_LEGACY_YOLOV5_DIR`.
  - The model artifact `backend/model_weights/fire_smoke.pt` is intentionally gitignored and must be provided on target machines.

## Session 2026-07-10 Fire Smoke Image Test Scripts

- Goal: wrap the two one-image fire/smoke test snippets into reusable Python scripts.
- Actions:
  - Added `backend/scripts/test_fire_smoke_image.py` for raw model detections.
  - Added `backend/scripts/test_fire_smoke_alarm_image.py` for 30-frame debounce and `AlarmEvent(type=fire_smoke)` output.
  - Both scripts default to `test_photos/fire_test.jpg` and accept a custom image path.
  - Suppressed noisy legacy YOLOv5 fallback/log output so script output is easy to read.
- Validation:
  - `.\init.cmd` passed.
  - `py_compile` passed for both scripts.
  - Raw image script detected fire about 0.757, fire about 0.557, and smoke about 0.256 on `test_photos/fire_test.jpg`.
  - Alarm image script emitted one `fire_smoke` event after 30 repeated frames.
- Remaining risks:
  - These scripts validate single-image behavior only; final C3 acceptance still needs real video/RTMP negative and positive cases.
  
## Session 2026-07-09 Task E Post-Merge Validation Repair

- Goal: verify the current `taskE` branch after conflict resolution and repair any narrow merge regressions.
- Baseline:
  - `pwd` confirmed `C:\Users\25003\AI-Study-Room`.
  - Current branch was `taskE` and was aligned with `origin/taskE`.
  - `rg` found no remaining conflict markers outside `.env`.
  - Ubuntu WSL is installed; `wsl -l -v` shows `Ubuntu` on WSL 2.
- Actions:
  - Removed a duplicate `ws.register_ws_routes(sock)` call in `backend/app/__init__.py`.
  - Removed a duplicate `Guard` ORM class definition in `backend/app/models/entities.py`.
  - Restored missing `AlarmService` helper methods for event normalization, snapshot save, face fallback, persistence, serialization, broadcast, and notification.
  - Added `FaceMatcher.encode_from_rect()` fallback for mocked/unit-test contexts where dlib is marked loaded but predictor/encoder objects are not present.
  - Updated `feature_list.json` with the repaired validation evidence and replaced the old WSL no-distribution blocker with the current proxy-warning note.
- Validation:
  - From repo root: `bash ./init.sh` passed and printed `Smoke test passed: required files present; markdown docs found`; WSL still printed a localhost proxy warning.
  - From `backend/`: `python -m py_compile app/__init__.py app/models/entities.py app/services/alarm.py app/detectors/face.py` passed.
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py tests/test_fire_smoke.py` passed: 39 passed, 14 warnings.
  - `python backend/scripts/verify_task_e_real_db.py` passed against real MySQL. Latest run wrote and verified alarm IDs: confirmed fight `4`, escalated intrusion `5`, private fatigue `6`.
- Remaining risks:
  - Full real DingTalk button confirmation still needs a public backend URL in `.env` as `PUBLIC_BASE_URL`.
  - WSL NAT mode still warns that localhost proxy configuration is not mirrored into WSL; this does not block `init.sh`.

## Session 2026-07-09 Task E DingTalk Send Escalation Test

- Goal: verify real DingTalk sending and the unconfirmed escalation path for task E.
- Baseline:
  - `pwd` confirmed `C:\Users\25003\AI-Study-Room`.
  - `feature_list.json` showed task E as completed, with remaining public confirm URL risk.
  - `wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/25003/AI-Study-Room && ./init.sh"` passed; WSL still printed the localhost proxy warning.
  - Windows Python needed non-sandbox execution in this session; `python --version` returned Python 3.14.6.
- Actions:
  - Re-read task E, especially E4: primary ActionCard, `ESCALATE_TIMEOUT=180`, confirm cancels timer, and unconfirmed alarms escalate to a leader/responsible person through either a second webhook or an @ mention.
  - Reviewed `backend/app/services/dingtalk.py` and confirmed current behavior: selects `Guard(role="primary")` for primary logs and `Guard(role="leader")` for escalated logs, sends ActionCard through `DINGTALK_WEBHOOK`, and uses `DINGTALK_LEADER_WEBHOOK` only when configured.
  - Confirmed current ActionCard payloads do not include DingTalk @ fields; `guard.dingtalk_id` is stored but not used for an @ mention.
  - Ran a real-send local escalation test with `DingTalkNotifier(timeout=5)` so the escalation path did not require waiting 3 minutes.
- Validation:
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
  - From `backend/`: `python -m pytest tests/test_alarm_center.py` passed: 6 passed, 7 warnings.
  - Real DingTalk primary ActionCard send returned HTTP 200 with `{"errcode":0,"errmsg":"ok"}`.
  - After 5 seconds without confirmation, alarm ID 14 became `status=escalated` and `level=2`.
  - Real DingTalk escalated ActionCard send returned HTTP 200 with `{"errcode":0,"errmsg":"ok"}`.
  - `notification_log` contained one `primary` row linked to a primary guard and one `escalated` row linked to a leader guard.
- Remaining risks:
  - `DINGTALK_LEADER_WEBHOOK` is not configured, so escalation currently reuses the primary group robot.
  - Current DingTalk ActionCard payloads do not @ a specific `dingtalk_id`; true per-person targeting needs either a leader webhook/group routing decision or an @-mention payload enhancement.
  - Full button-click confirmation still needs `PUBLIC_BASE_URL` pointing to a reachable HTTP/HTTPS backend URL.

## Session 2026-07-09 Task E Local Confirm Button URL Fix

- Goal: fix the DingTalk ActionCard "confirm" button opening an RTMP handler instead of the alarm confirmation page.
- Baseline:
  - The user reported that clicking "confirm处理" prompted Windows to choose an app capable of opening RTMP.
  - `wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/25003/AI-Study-Room && ./init.sh"` passed; WSL still printed the localhost proxy warning.
  - `.env` had `PUBLIC_BASE_URL` using an `rtmp://.../live/test` stream URL.
- Actions:
  - Changed local `.env` `PUBLIC_BASE_URL` to `http://127.0.0.1:5000`.
  - Started the lightweight backend with `python run_simple.py`, exposing `http://127.0.0.1:5000`.
  - Verified `DingTalkNotifier._public_url("/api/alarms/123/confirm")` now returns `http://127.0.0.1:5000/api/alarms/123/confirm`.
  - Verified an existing confirm page returned HTTP 200 at `http://127.0.0.1:5000/api/alarms/14/confirm`.
  - Sent a new DingTalk ActionCard for alarm ID 16; DingTalk returned `{"errcode":0,"errmsg":"ok"}` and the card used `http://127.0.0.1:5000/api/alarms/16/confirm`.
- Validation:
  - From `backend/`: `python -m pytest tests/test_alarm_center.py` passed: 6 passed, 7 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
- Remaining risks:
  - `http://127.0.0.1:5000` only works when clicking from the same Windows machine running the backend, such as DingTalk desktop on this PC.
  - Clicking from a phone or another machine still needs `PUBLIC_BASE_URL` to be an HTTP/HTTPS public tunnel or deployed server URL.
  - Existing old DingTalk cards still contain their original URL; only newly sent cards use the corrected `PUBLIC_BASE_URL`.

## Session 2026-07-09 Task E Actor Context And Handler Mention

- Goal: make DingTalk alarm messages clearly say who triggered the alarm, what behavior triggered it, and which guard should handle it.
- Baseline:
  - The local confirm page text `Alarm <id> confirmed / You can close this page.` was verified as normal behavior for the browser-friendly DingTalk confirm endpoint.
  - The existing card content showed raw alarm fields, and the selected guard was only recorded in `notification_log.guard_id`.
- Actions:
  - Updated `backend/app/services/dingtalk.py` so DingTalk ActionCards include actor, behavior, alarm type, handler, region/location, camera, snapshot, and score context.
  - Actor resolution now prefers detector-provided `extra` fields such as `actor`, `person_name`, `student_name`, or `member_name`, then falls back to member face match, seat user nickname for fatigue/occupy, `stranger`, or unknown.
  - Behavior resolution now prefers detector-provided `extra.behavior`/`extra.action`/`extra.reason`, then falls back to a per-alarm-type default behavior description.
  - Added a separate DingTalk text message after each ActionCard to @ the selected guard via `guard.dingtalk_id`; 11-digit IDs are sent as `atMobiles`, other IDs as `atUserIds`.
  - Added `.env.example` DingTalk placeholders and clarified that `PUBLIC_BASE_URL` must be HTTP/HTTPS backend URL, not an RTMP stream URL.
  - Added `test_dingtalk_card_describes_actor_behavior_and_mentions_guard` to cover rich card content and @ payload generation.
- Validation:
  - From repo root: `wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/25003/AI-Study-Room && ./init.sh"` passed; WSL still printed the localhost proxy warning.
  - From `backend/`: `python -m py_compile app/services/dingtalk.py tests/test_alarm_center.py` passed.
  - From `backend/`: `python -m pytest tests/test_alarm_center.py` passed: 7 passed, 11 warnings.
  - Real DingTalk smoke sent alarm ID 17 with actor `小明`, behavior `推搡同学，疑似发生肢体冲突`, and handler mention; DingTalk returned `{"errcode":0,"errmsg":"ok"}` for both the ActionCard and the text @ message.
  - Started `python run_simple.py` so `http://127.0.0.1:5000/api/alarms/17/confirm` can be clicked locally from DingTalk desktop.
- Remaining risks:
  - Whether DingTalk visually notifies the exact person depends on `guard.dingtalk_id` being a valid DingTalk user ID or mobile accepted by the robot.
  - `127.0.0.1` confirm links only work on this same Windows machine while the local backend is running.

## Session 2026-07-09 Task E Swagger Docs

- Goal: add Swagger/OpenAPI documentation for task E REST interfaces used by other modules.
- Actions:
  - Rewrote `backend/app/api/alarms.py` docstrings with clean Swagger YAML while preserving existing route behavior.
  - Documented `GET /api/alarms` for dashboard/list consumers, including status filtering and `AlarmEvent` schema.
  - Documented `POST /api/alarms/{alarm_id}/confirm` for JSON clients.
  - Documented `GET /api/alarms/{alarm_id}/confirm` as the DingTalk ActionCard browser confirmation callback.
  - Documented `GET /api/alarms/snapshots/{filename}` for alarm snapshot access.
  - Added response schemas for `AlarmEvent`, `AlarmConfirmResponse`, and `AlarmErrorResponse`.
- Validation:
  - From repo root: `wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/25003/AI-Study-Room && ./init.sh"` passed; WSL still printed the localhost proxy warning.
  - From `backend/`: `python -m py_compile app/api/alarms.py` passed.
  - From `backend/`: `python -m pytest tests/test_alarm_center.py` passed: 7 passed, 11 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
  - Flask test client `GET /apispec_1.json` returned 200 and exposed `/api/alarms`, `/api/alarms/{alarm_id}/confirm`, `/api/alarms/snapshots/{filename}`, plus `AlarmEvent`, `AlarmConfirmResponse`, and `AlarmErrorResponse` definitions.
- Remaining risks:
  - WebSocket `/ws/alarms` is referenced in the REST description but is not represented as a native Swagger path because it is a WebSocket route.

## Session 2026-07-09 Task E Local Stream Capture

- Goal: add a Task E self-test path so alarm-center testing can pull one frame and create its own snapshot while upstream stream/detector modules are still incomplete.
- Baseline:
  - `pwd` confirmed `C:\Users\25003\AI-Study-Room`.
  - `feature_list.json` still treats `alarm-center-dingtalk-close-loop` as the Task E source of truth.
  - `wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/25003/AI-Study-Room && ./init.sh"` passed; WSL still printed the localhost proxy warning.
  - PowerShell sandbox could not launch `python.exe` directly, so Python validation was run with elevated execution.
- Actions:
  - Added `backend/app/services/stream_capture.py` as a one-shot RTMP/RTSP/video frame capture helper using OpenCV `VideoCapture`.
  - Added `POST /api/alarms/test-capture` in `backend/app/api/alarms.py`.
  - The endpoint accepts `stream_url` or resolves `camera.stream_url` from `camera_id`, requires/derives `region_id`, captures one frame, creates `AlarmEvent`, and calls `AlarmService.raise_alarm(event, frame)`.
  - The endpoint carries `actor`, `behavior`, `face_match`, scores, and custom `extra` into the alarm extra JSON so DingTalk cards can say who did what and who should handle it.
  - Added Swagger documentation for the new local/manual test-capture endpoint.
  - Added tests for stream capture success/failure and for the API path that resolves a camera stream URL, saves a snapshot, persists the alarm, broadcasts, and notifies.
- Validation:
  - From repo root: `wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/25003/AI-Study-Room && ./init.sh"` passed.
  - From `backend/`: `python -m py_compile app/api/alarms.py app/services/stream_capture.py tests/test_alarm_center.py` passed.
  - From `backend/`: `python -m pytest tests/test_alarm_center.py` passed: 10 passed, 13 warnings.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_alarm_center.py tests/test_fire_smoke.py` passed: 43 passed, 20 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
- Remaining risks:
  - `POST /api/alarms/test-capture` is a local/manual integration helper. Continuous production stream scheduling and detector-driven alarm creation still belong to the upstream stream scheduler and detector modules.
  - Real RTMP capture still depends on the RTMP source being reachable from this machine and OpenCV/FFmpeg being able to decode it.

## Session 2026-07-09 Task E Capture Testing with Real Stream

- Goal: test the `POST /api/alarms/test-capture` endpoint with a real RTMP stream from OBS.
- Actions:
  - Fixed `scheduler.py`: removed `live=1` from the RTMP URL (it should be an FFmpeg option, not part of the URL).
  - Fixed `scheduler.py`: added `rtmp_live;live` to `OPENCV_FFMPEG_CAPTURE_OPTIONS` environment variable.
  - Fixed `alarms.py`: changed `camera_id <= 0` check to `camera_id < 0` to allow camera_id=0.
  - Fixed `alarms.py`: changed falsy checks (`if not camera_id`) to explicit `None` checks (`if camera_id is None`).
  - Enhanced `stream_capture.py`: added `_try_get_from_scheduler()` to get frames from the scheduler's ring buffer instead of opening a second RTMP connection.
- Validation:
  - Backend successfully connected to RTMP stream: `cam-0 解码统计: ok=129, dropped=0`.
  - Real-time frame capture from scheduler buffer works when stream is stable.
- Remaining issues:
  - Network instability: RTMP stream shows frequent packet mismatch errors, causing intermittent frame drops.
  - When the stream is stable, `test-capture` can successfully grab frames from the scheduler's ring buffer.

## Session 2026-07-10 Configurable Camera 5 Stream Startup

- Goal: make backend stream startup configurable and use `camera_id=5` for the current real-camera test without hard-coding the only usable camera.
- Baseline:
  - `pwd` confirmed `C:\Users\25003\AI-Study-Room`.
  - `wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/25003/AI-Study-Room && ./init.sh"` passed; WSL still printed the localhost proxy warning.
  - Direct sandboxed `python.exe` launch failed in this session with "specified logon session does not exist", so Python tests were run with approved non-sandbox execution.
- Actions:
  - Added `STREAM_CAMERA_ID`, `STREAM_NAME`, `STREAM_URL`, and `STREAM_LOCAL_CAMERA` config values.
  - Updated `backend/run.py` so startup uses those config values. Default startup camera remains `camera_id=5`.
  - Updated `StreamScheduler.add_camera()` so `add_camera(camera_id=5)` loads `camera.stream_url` from the database when no explicit stream name or URL is provided.
  - Preserved legacy behavior: `add_camera(camera_id=0, stream_name="test")` still builds `rtmp://{RTMP_SERVER}:{RTMP_PORT}/live/test`.
  - Fixed local camera mode so `local_camera=0` is passed to OpenCV as integer `0`, not string `"0"`.
  - Fixed `verify_task_e_g_real_camera.py` so `--camera-id 5` keeps camera 5 and derives a region for camera 5 instead of falling back to the first camera/region pair.
  - Added `--stream-url` to `verify_task_e_g_real_camera.py` so any existing camera/region row can be tested against an arbitrary RTMP source without editing the database first.
  - Documented the new stream startup settings in `.env.example`.
- Validation:
  - WSL py_compile passed for `app/stream/scheduler.py`, `app/config.py`, `run.py`, `scripts/verify_task_e_g_real_camera.py`, and `tests/test_task_g.py`.
  - From `backend/`: `python -m pytest tests/test_task_g.py -q` passed: 6 passed.
  - From `backend/`: `python -m pytest tests/test_alarm_center.py tests/test_task_g.py -q` passed: 16 passed, 13 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
  - Real-camera script with `--camera-id 5` resolved `camera_id=5`, `region_id=5`, and `source=rtmp://49.233.71.82:9090/live/test`.
  - Retesting with `--camera-id 1 --stream-url rtmp://49.233.71.82:9090/live/test` still failed at RTMP handshake, confirming the blocker is independent of camera id.
- Remaining risks:
  - The real `camera_id=5` RTMP run timed out waiting for a readable frame after about 30 seconds, so snapshot/playback/report could not complete until the RTMP pusher/server path is live.
  - Existing frontend files remain staged from prior merge/conflict work and were not modified in this session.

## Session 2026-07-10 Stream Capture Failure Triage

- Goal: analyze why OBS can start streaming but backend capture still cannot read frames.
- Findings:
  - `python backend/run.py` does start StreamScheduler for `camera_id=5` and tries `rtmp://49.233.71.82:9090/live/test`.
  - `fire_smoke.pt` missing only makes the fire/smoke detector setup fail; engine continues and this is not the RTMP capture blocker.
  - The frontend `VideoPlayer` does not directly play RTMP. It extracts `camera_id` and subscribes to `/ws/video_feed/{camera_id}`, which depends on the backend scheduler ring buffer.
  - `verify_task_e_g_real_camera.py` starts a separate Python scheduler process, so it is not testing the exact same scheduler instance that a running frontend may be viewing.
  - `stream_capture.capture_frame()` previously waited only about 1 second for a scheduler frame before falling back to a second RTMP `VideoCapture`; this made it too easy to hit the currently failing direct-RTMP path.
  - Minimal OpenCV tests with and without `OPENCV_FFMPEG_CAPTURE_OPTIONS` both returned `opened=False` for `rtmp://49.233.71.82:9090/live/test`.
  - Low-level socket tests show the server port can respond to RTMP handshake bytes, so the port is not completely dead; the failure is in OpenCV/FFmpeg opening/reading that playback stream.
- Actions:
  - Added `GET /api/cameras/{camera_id}/stream-status` for scheduler diagnostics: scheduler started, registered camera ids, online state, latest frame bytes, ring buffer length, and pre-buffer length.
  - Updated `stream_capture.capture_frame()` to wait the full requested timeout for an existing scheduler camera frame before falling back to opening a second RTMP connection.
- Validation:
  - WSL py_compile passed for `app/api/cameras.py`, `app/services/stream_capture.py`, and `tests/test_task_g.py`.
  - From `backend/`: `python -m pytest tests/test_task_g.py tests/test_alarm_center.py -q` passed: 17 passed, 13 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
  - Found two Python processes listening on port 5000; stopped the duplicate/stale listeners and restarted a single clean `python backend/run.py`.
  - Clean backend startup connected to `camera_id=5` at `rtmp://49.233.71.82:9090/live/test`; scheduler logged successful source size `1280x720` and decode statistics with ok frames and 0 dropped.
  - `GET /api/cameras/5/stream-status` returned `online=true`, `has_frame=true`, `latest_frame_bytes=10334`, `ring_buffer_len=5`, and `pre_buffer_len=75`.
  - `POST /api/alarms/test-capture` created real scheduler-buffer alarm `id=48` with snapshot `/api/alarms/snapshots/alarm_1783691900602_5_fight.jpg`.
  - Async clip recording completed for alarm 48 and set `clip_url=/api/alarms/clips/alarm_48_1783691900602.mp4`.
  - Snapshot endpoint returned 200 with 17558 bytes; clip endpoint returned 200 with 227218 bytes and `video/mp4`.
  - `GET /api/alarms/daily-report?date=2026-07-10` returned 200 and included alarm 48 in the daily report data.
- Next diagnostic step:
  - Keep using a single `python backend/run.py` process for live-video tests. If capture fails again, first check for duplicate `:5000` Python listeners before changing RTMP code.

## Session 2026-07-10 Task E/G Completion Verification

- Goal: verify whether Task E and Task G are complete, especially snapshot capture, playback clip evidence, and AI monitoring daily report generation.
- Baseline:
  - Current branch is `taskE`.
  - `feature_list.json` already marked Task E completed, but its evidence mixed Task G details and still contained a stale RTMP timeout blocker.
  - Frontend files were already staged from earlier work; this backend verification did not modify or include them.
- Actions:
  - Confirmed Task E close-loop remains implemented: alarm query/confirm/snapshot APIs, test-capture alarm creation, DingTalk workflow, and persisted alarm records.
  - Confirmed Task G backend evidence flow is implemented: `clip_url`, async `ClipRecorder`, `/api/alarms/clips/<filename>` playback endpoint with range support, stream-status diagnostics, and `DailyReportService` in `backend/app/services/daily_report.py`.
  - Added a separate completed Task G entry to `feature_list.json` and removed the stale RTMP-timeout blocker from Task E.
  - Added `backend/clips/*.mp4` to `.gitignore` so generated playback evidence videos do not pollute source control; the tracked `backend/reports/report_2026-07-10.json` remains daily-report evidence.
- Validation:
  - `wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/25003/AI-Study-Room && ./init.sh"` passed; WSL only printed the localhost proxy warning.
  - WSL `python3 -m py_compile` passed for Task E/G files: daily report, clip recorder, alarm/camera APIs, stream capture, scheduler, and `tests/test_task_g.py`.
  - WSL `python3 -m json.tool feature_list.json` passed.
  - From `backend/`: `python -m pytest tests/test_task_g.py tests/test_alarm_center.py -q` passed: 17 passed, 13 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
- Remaining risks:
  - Task G backend capture/playback/report is complete; frontend playback UI belongs to Task F and was not changed in this pass.
  - Fight MP4 evidence is currently video-only in the OpenCV encoder path; precise audio muxing remains a future enhancement if required.
  - If live RTMP capture fails again, first check for duplicate Python processes on port 5000 before changing stream code.

## Session 2026-07-11 Task E/G Backend Review And DingTalk Wording

- Goal: review the current backend-only Task E/G changes, remove local-only leftovers, clarify ownership of public snapshot/playback access, and make DingTalk alarm context read like a person speaking.
- Actions:
  - Kept only source-worthy changes and ignored generated runtime artifacts with `.gitignore` entries for `backend/clips/`, `backend/reports/`, and `backend/logs/`.
  - Removed local experiment/deployment leftovers that were not tracked by Git, including temporary cloud deploy examples, shared alarm server experiment files, generated clips, and local-only test scripts.
  - Updated DingTalk ActionCard content to summarize actor, behavior, location, camera, handler, type, level, and evidence in one natural spoken paragraph.
  - Removed Base64 snapshot embedding from DingTalk cards and kept public HTTP/HTTPS snapshot markdown only when `PUBLIC_BASE_URL` makes it reachable.
  - Added `face_spoof` to the Task E alarm API allowed types and Swagger enum.
  - Repaired `FaceDetector.detect()` indentation so imports work again while preserving existing behavior: normal face recognition pushes WebSocket updates only; `face_spoof` remains an alarm path.
  - Added formal backend tests for confirm-page snapshot/clip detail rendering, MP4 Range playback, and daily-report JSON/Markdown artifact generation.
- Validation:
  - `.\init.cmd` passed.
  - From repo root: `python -m py_compile backend/app/detectors/face.py backend/app/services/dingtalk.py backend/app/api/alarms.py backend/app/services/daily_report.py backend/app/services/clip_recorder.py backend/app/services/alarm.py backend/run.py backend/tests/test_alarm_center.py` passed.
  - From `backend/`: `python -m pytest tests/test_alarm_center.py -q` passed: 14 passed, 13 warnings.
  - From `backend/`: `python -m pytest tests/test_face.py tests/test_alarm_center.py -q` passed: 26 passed, 20 warnings.
  - From `backend/`: `python -m pytest tests/test_intrusion.py tests/test_intrusion_identity.py tests/test_fatigue.py tests/test_fight.py tests/test_fight_integration.py tests/test_face.py tests/test_fire_smoke.py tests/test_alarm_center.py -q` passed: 61 passed, 37 warnings.
  - From `backend/`: `python tests/smoke_test.py` passed and printed `ALL SMOKE TESTS PASSED`.
- Remaining risks:
  - Full external DingTalk snapshot/playback viewing still requires `PUBLIC_BASE_URL` to point to a publicly reachable HTTP/HTTPS backend or media host.
  - A full pytest run including `tests/test_liveness.py` still has one independent liveness assertion mismatch: identical frames are classified earlier as `static_frame_mse` spoof instead of the test's allowed `prolonged_no_blink`/`spoof_streak` reasons.
  - Public access to snapshots and MP4 clips is a deployment/network responsibility; backend can serve correct URLs, but other users cannot open local `127.0.0.1` or private-LAN addresses from DingTalk.

## Session 2026-07-11 Fire Smoke Legacy Loader Default

- Goal: fix local fire/smoke test scripts stalling while importing Ultralytics/Torch before falling back to the grafted legacy YOLOv5 model.
- Baseline:
  - User command `.venv\Scripts\python.exe backend\scripts\test_fire_smoke_image.py` was interrupted while importing `ultralytics -> torch -> platform.machine()`.
  - The same environment had already proven the local checkpoint is an old YOLOv5 model and the legacy adapter can load it.
- Actions:
  - Added `FIRE_SMOKE_MODEL_LOADER`, defaulting to `legacy`.
  - Updated `FireSmokePlugin.setup()` to load the legacy YOLOv5 adapter directly by default, while preserving `FIRE_SMOKE_MODEL_LOADER=ultralytics` as an explicit opt-in path with legacy fallback.
  - Cleaned the fire/smoke detector and unit-test files to ASCII to avoid brittle mojibake string matching.
  - Updated `.env.example` with `FIRE_SMOKE_MODEL_LOADER=legacy`.
- Validation:
  - `py_compile` passed for fire/smoke config, detector, tests, and helper scripts.
  - Raw image script passed on `test_photos/fire_test.jpg`: detected fire 0.757, fire 0.557, and smoke 0.256.
  - Alarm image script passed: 30 frames produced one `AlarmEvent(type=fire_smoke)`.
  - Focused pytest passed: `tests/test_fire_smoke.py tests/test_alarm_center.py --basetemp=.pytest_tmp` -> 19 passed.
  - `.\init.cmd` passed.
- Remaining risks:
  - Full C3 acceptance still needs live RTMP/OBS positive and negative footage.
  - Deployment still must include `backend/model_weights/fire_smoke.pt` and the legacy YOLOv5 source directory, or configure `FIRE_SMOKE_LEGACY_YOLOV5_DIR`.
  - If a new Ultralytics-compatible model is introduced later, set `FIRE_SMOKE_MODEL_LOADER=ultralytics`.

## Session 2026-07-11 PR Merge

- Goal: merge the latest PR changes into local `main`.
- Baseline:
  - `pwd` confirmed `D:\1\大二暑期实训\App`.
  - `git` was not available on PowerShell PATH; used `C:\Program Files\Git\cmd\git.exe`.
  - Local `main` was behind `origin/main` by 3 commits.
  - Pre-existing local changes remained in `backend/app/stream/scheduler.py` and `.claude/settings.local.json`.
- Actions:
  - Fetched `origin`.
  - Fast-forwarded local `main` from `be64b72` to `ea4dfb8`, incorporating `Merge pull request #39 from sco11-Angus/taskE`.
- Validation:
  - Standard Windows smoke passed through the PowerShell executable directly: `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\init.ps1`.
  - Latest history now starts with `ea4dfb8 Merge pull request #39 from sco11-Angus/taskE`.
- Remaining risks:
  - `.\init.cmd` still fails in this shell because `powershell.exe` is not on PATH, although the equivalent full-path PowerShell command passes.
  - The working tree still contains pre-existing uncommitted local files unrelated to the PR merge.

## Session 2026-07-12 Mark C3 Complete

- Goal: update the repository status source after confirming the grafted `fire-smoke-detect-yolov4-master` backend fire/smoke path is usable.
- Baseline:
  - `pwd` confirmed `C:\Users\ASUS\AI-Study-Room`.
  - `.\init.cmd` passed before editing.
  - `feature_list.json` still marked `task-c3-fire-smoke-detection` as `blocked` because it treated live RTMP/OBS footage as a completion blocker.
- Actions:
  - Updated `feature_list.json` so `task-c3-fire-smoke-detection` is `completed`.
  - Replaced the old RTMP/video completion requirement with the validations that are currently implemented and runnable in this workspace: focused pytest plus `.venv` image scripts.
  - Cleared C3 blockers in `feature_list.json`; deployment notes remain in progress docs rather than blocking completion.
  - Updated `openspec/progress/progress.md` top status so there is no current highest-priority unfinished feature.
- Validation:
  - `.venv\Scripts\python.exe backend\scripts\test_fire_smoke_image.py` passed on `test_photos/fire_test.jpg`: fire 0.757, fire 0.557, smoke 0.256.
  - `.venv\Scripts\python.exe backend\scripts\test_fire_smoke_alarm_image.py` passed: 30 repeated frames emitted one `AlarmEvent(type=fire_smoke, camera_id=5, level=1)`.
  - From `backend/`: `..\.venv\Scripts\python.exe -m pytest tests/test_fire_smoke.py` passed: 8 passed.
  - `.\init.cmd` passed.
- Remaining risks:
  - Deployment must keep `backend/model_weights/fire_smoke.pt` and the legacy YOLOv5 source directory available, or configure `FIRE_SMOKE_LEGACY_YOLOV5_DIR`.
  - Real RTMP/OBS smoke/fire and reflection-negative footage remains useful for live demo/integration proof, but it is no longer recorded as a C3 completion blocker.
