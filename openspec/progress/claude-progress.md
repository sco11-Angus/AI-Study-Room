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
