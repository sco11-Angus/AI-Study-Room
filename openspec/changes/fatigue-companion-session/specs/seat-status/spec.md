# Seat Status

## ADDED Requirements

### Requirement: Explicit study session modes

The system SHALL support `demo` and `verified` study sessions for seat status.

#### Scenario: Demo session starts without reservation
- **WHEN** a client sets a seat to `studying` with mode `demo`
- **THEN** the system SHALL activate demo fatigue eligibility for that seat

#### Scenario: Verified session validates reservation
- **WHEN** a client sets a seat to `studying` with mode `verified`
- **THEN** the system SHALL require an enabled reservation and a matching enrolled member

### Requirement: One active study session per seat

The system SHALL allow at most one `studying` session for a seat at a time.

#### Scenario: New study session replaces old session
- **GIVEN** a seat already has a studying session
- **WHEN** another client starts a study session for that seat
- **THEN** the previous session SHALL become `idle` before the new session is active
