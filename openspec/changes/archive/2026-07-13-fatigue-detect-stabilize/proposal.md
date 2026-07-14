## Why

The current fatigue companion is a working MVP, but it still relies on single-threshold EAR/MAR rules. A single yawn-like MAR spike can trigger an alarm, repeated detections can notify DingTalk too frequently, and alarm payloads do not expose enough EAR/MAR context for tuning.

This change improves the Dlib-based implementation into a more stable, tunable engineering version without replacing the model stack.

## What Changes

- Add sliding-window voting for yawn detection so one MAR spike is not enough to alert.
- Keep sleepy detection based on continuous low EAR duration, while treating short eye closures as blinks instead of fatigue.
- Add per-seat fatigue notification cooldown to prevent repeated DingTalk alerts.
- Include EAR/MAR metrics, trigger duration, and window counters in fatigue alarm `extra`.
- Add fatigue tuning presets and environment-configurable thresholds while preserving existing defaults.
- Add a local video analysis script that exports per-frame EAR/MAR/decision data for tuning.
- Extend frontend study companion status to show current study/rest state and the latest fatigue reminder.

## Impact

- Backend fatigue detector state machine and plugin behavior.
- Fatigue-related configuration values.
- Unit tests for fatigue detection and alarm cooldown.
- A local script for video-based tuning evidence.
- Frontend study companion display only; no database migration is required.
