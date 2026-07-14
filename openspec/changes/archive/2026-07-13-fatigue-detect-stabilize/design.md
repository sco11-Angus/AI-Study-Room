## Context

Task B fatigue detection currently uses Dlib 68-point landmarks, EAR for closed eyes, and MAR for yawning. `FatiguePlugin` only runs for `studying` seat regions and emits `AlarmEvent(type="fatigue")`, which enters the existing DingTalk path when level is at least 1.

The main operational risks are false positives from one-frame MAR spikes, repeated notifications while the same student remains tired, and lack of observable metrics for tuning.

## Decisions

### D1: Keep Dlib and add temporal filtering first

This change keeps Dlib landmarks and does not add MediaPipe or a new classifier. Stability comes from temporal filtering and better observability:

- sleepy: EAR below threshold continuously for `EAR_DURATION`
- blink: EAR below threshold for less than the sleepy duration and then resets
- yawn: MAR threshold must be met in a sliding window before alerting

### D2: Cooldown is enforced per active seat and fatigue kind

Cooldown lives in `FatiguePlugin`, keyed by `(region_id, kind)`, so the detector can continue measuring state but repeated alarms do not spam DingTalk. Default cooldown is configurable and should be long enough for real classrooms.

### D3: Alarm `extra` carries tuning metrics

Fatigue events include at least:

- `kind`: `sleepy` or `yawn`
- `user_id`
- `level`
- `ear`
- `mar`
- `closed_duration`
- `yawn_hits`
- `yawn_window`

This keeps downstream alarm and DingTalk code unchanged while making tuning visible.

### D4: Tuning script is offline and local

The video tuning script reads a local video path, runs the same Dlib landmark and detector logic, and writes CSV rows with timestamp, EAR, MAR, and decision. It does not persist alarms or call DingTalk.

## Non-Goals

- No MediaPipe replacement in this change.
- No dedicated fatigue neural network.
- No database schema migration.
- No real OBS/RTMP acceptance automation; live verification remains manual.
