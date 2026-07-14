# Alarm Close Loop

## ADDED Requirements

### Requirement: Companion fatigue presentation

The system SHALL persist and DingTalk-notify fatigue alarms while presenting
them as companion reminders instead of dashboard emergency states.

#### Scenario: Fatigue reminder is non-urgent on dashboard
- **GIVEN** a fatigue alarm is emitted
- **THEN** it SHALL be retained in alarm history
- **AND** it SHALL NOT cause a dashboard red region, flash, or beep

#### Scenario: Matching companion receives reminder
- **GIVEN** a companion subscribes for a user and seat
- **WHEN** a matching fatigue alarm is emitted
- **THEN** that companion SHALL receive the reminder event with its fatigue metrics
