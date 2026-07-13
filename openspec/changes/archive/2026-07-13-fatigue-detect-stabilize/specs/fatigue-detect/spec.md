# Fatigue Detection

## ADDED Requirements

### Requirement: Temporal fatigue filtering

The system SHALL classify fatigue only after temporal evidence is sufficient for the configured fatigue type.

#### Scenario: Short blink does not alert
- **GIVEN** a studying seat has face landmarks
- **WHEN** EAR is below the sleepy threshold for less than the configured sleepy duration and then returns above threshold
- **THEN** the system SHALL treat the event as a blink and SHALL NOT emit a fatigue alarm

#### Scenario: Continuous closed eyes alert as sleepy
- **GIVEN** a studying seat has face landmarks
- **WHEN** EAR remains below the sleepy threshold for at least the configured sleepy duration
- **THEN** the system SHALL emit a fatigue alarm with `extra.kind` equal to `sleepy`

#### Scenario: Yawn requires window evidence
- **GIVEN** a studying seat has face landmarks
- **WHEN** MAR exceeds the yawn threshold in fewer frames than the configured yawn window hit threshold
- **THEN** the system SHALL NOT emit a yawn alarm
- **WHEN** MAR exceeds the threshold enough times within the configured yawn window
- **THEN** the system SHALL emit a fatigue alarm with `extra.kind` equal to `yawn`

### Requirement: Fatigue alert cooldown

The system SHALL suppress repeated fatigue alarms for the same seat and fatigue kind during the configured cooldown interval.

#### Scenario: Repeated fatigue during cooldown
- **GIVEN** a studying seat already emitted a `sleepy` fatigue alarm
- **WHEN** the same seat remains sleepy before cooldown expires
- **THEN** the system SHALL NOT emit another `sleepy` alarm for that seat

### Requirement: Fatigue metrics for tuning

The system SHALL include fatigue tuning metrics in every emitted fatigue alarm.

#### Scenario: Alarm contains metrics
- **GIVEN** a fatigue alarm is emitted
- **THEN** `extra` SHALL include `ear`, `mar`, `closed_duration`, `yawn_hits`, and `yawn_window`

### Requirement: Offline fatigue tuning script

The system SHALL provide a local script that analyzes a video file and writes per-frame fatigue metrics without persisting alarms.

#### Scenario: Analyze local video
- **GIVEN** a valid local video and Dlib landmark model
- **WHEN** the tuning script runs
- **THEN** it SHALL write frame timestamp, EAR, MAR, and decision rows to a CSV file

### Requirement: Study companion fatigue status

The frontend SHALL show the current self-study status and the latest fatigue reminder summary.

#### Scenario: Latest fatigue reminder visible
- **GIVEN** the backend has a recent fatigue alarm for the current seat
- **WHEN** the user opens the study companion view
- **THEN** the view SHALL display whether the reminder was `sleepy` or `yawn`
