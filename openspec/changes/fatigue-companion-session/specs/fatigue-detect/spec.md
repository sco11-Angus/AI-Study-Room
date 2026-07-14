# Fatigue Detection

## ADDED Requirements

### Requirement: Session-aware fatigue eligibility

The system SHALL run fatigue inference only for an active studying session and
only when exactly one face is inside that session's seat polygon.

#### Scenario: Outside face does not activate a seat
- **GIVEN** a demo study session is active
- **WHEN** every detected face is outside its seat polygon
- **THEN** the system SHALL reset the seat fatigue timer and SHALL NOT emit a fatigue alarm

#### Scenario: Multiple faces pause fatigue
- **GIVEN** an active study session has two or more faces inside its seat polygon
- **WHEN** the frame is processed
- **THEN** the system SHALL pause fatigue inference with reason `ambiguous_face`

### Requirement: Verified-session identity gate

The system SHALL require the reserved member identity before fatigue inference
advances for a verified study session.

#### Scenario: Reserved member enables verified fatigue
- **GIVEN** a verified studying session whose member matches the enabled reservation
- **WHEN** the sole in-seat face matches that member
- **THEN** the system SHALL evaluate EAR and MAR for that seat

#### Scenario: Unknown or mismatched face pauses verified fatigue
- **GIVEN** a verified studying session
- **WHEN** the sole in-seat face is unknown or matches another member
- **THEN** the system SHALL reset the fatigue timer and SHALL NOT emit a fatigue alarm

### Requirement: Frame-size-aware seat geometry

The system SHALL evaluate normalized seat polygons against the decoded frame's
actual width and height.

#### Scenario: Resolution changes
- **GIVEN** a normalized seat polygon
- **WHEN** the stream resolution changes
- **THEN** in-seat face selection SHALL use the new frame dimensions
