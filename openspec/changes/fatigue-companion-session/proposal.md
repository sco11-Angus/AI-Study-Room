## Why

The current fatigue flow starts from `seat_status=studying`, but does not know
whether the detected face belongs to the studying person.  It also falls back
to an arbitrary full-frame face when a face is outside the seat.  Reservation
identity checks live separately in `seat_reservation`, so operators cannot
tell why fatigue is active or paused.

Fatigue is a personal study reminder. It should remain auditable and notify
DingTalk, while the monitoring dashboard must not treat it as a red-flash,
high-urgency incident.

## What Changes

- Treat `seat_status` as the current study session and add `mode` (`demo` or
  `verified`) plus an optional enrolled `member_id`.
- Keep `seat_reservation` as the durable owner binding. A verified session
  requires its member to match the seat reservation.
- Activate fatigue only for one unambiguous in-seat face. Demo sessions do not
  require identity; verified sessions require a matching member face.
- Persist and DingTalk-notify fatigue alarms, but present them as companion
  reminders rather than dashboard red-alert states.
- Replace the companion's hidden first-camera/first-seat and hard-coded user
  selection with explicit session controls and observable runtime status.

## Capabilities

### Modified Capabilities

- `fatigue-detect`: add seat-bounded face selection and verified identity
  gating.
- `seat-status`: make a status row an explicit demo or verified study session.
- `alarm-closeloop`: route fatigue to the companion reminder channel while
  preserving persistence and DingTalk notification.

## Impact

- Backend seat-status API, fatigue detector, alarm dispatch, WebSocket routes,
  ORM schema, and MySQL bootstrap SQL change together.
- The companion and dashboard frontend views gain distinct fatigue-reminder
  behavior.
- Existing reservation and intrusion behavior remains the source of truth for
  unauthorized-seat alerts.
