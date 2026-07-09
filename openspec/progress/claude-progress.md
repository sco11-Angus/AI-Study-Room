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
