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
