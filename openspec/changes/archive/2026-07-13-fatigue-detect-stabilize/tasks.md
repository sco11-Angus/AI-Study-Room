## 1. Specification

- [x] 1.1 Add fatigue-detect delta spec covering temporal filtering, cooldown, metrics, tuning script, and frontend status.
- [x] 1.2 Run `npm.cmd run spec:validate` successfully before implementation.

## 2. Backend Algorithm

- [x] 2.1 Extend fatigue configuration with yawn window, yawn hit threshold, alert cooldown, and preset mode.
- [x] 2.2 Update `FatigueDetector` to expose EAR/MAR metrics, blink reset behavior, and yawn sliding-window voting.
- [x] 2.3 Update `FatiguePlugin` to apply per-seat/kind cooldown and include metrics in `AlarmEvent.extra`.
- [x] 2.4 Preserve `studying` activation and `resting`/`idle` cleanup behavior.

## 3. Tuning Tool

- [x] 3.1 Add a local video analysis script that writes per-frame EAR/MAR/decision CSV output.
- [x] 3.2 Ensure the script fails clearly if the Dlib landmark model or video path is missing.

## 4. Frontend Status

- [x] 4.1 Show current study/rest state and latest fatigue reminder in the self-study companion view.
- [x] 4.2 Show a clear hint when backend reports no DingTalk webhook or no recent reminder is available.

## 5. Validation

- [x] 5.1 Add/extend unit tests for blink, yawn window, cooldown, extra metrics, and resting cleanup.
- [x] 5.2 Run focused backend fatigue/alarm tests.
- [x] 5.3 Run frontend production build.
- [x] 5.4 Run `.\init.cmd`.
- [x] 5.5 Update `feature_list.json` and progress records with real validation evidence.
