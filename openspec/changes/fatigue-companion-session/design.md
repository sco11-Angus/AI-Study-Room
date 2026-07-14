## Context

`SeatReservation` already binds a seat to an enrolled `Member` for intrusion
identity checks. `SeatStatus` currently stores only a user, seat, and status.
`FatiguePlugin` loads every studying status and selects an in-seat face, but
falls back to any frame face and cannot distinguish an owner from another
person.

## Decisions

### D1: A seat status is a current study session

`SeatStatus` gains `mode` (`demo` by default) and nullable `member_id`.
`POST /api/seat-status` accepts `user_id`, `region_id`, `status`, `mode`, and
`member_id`. At most one row for a region may be `studying`; starting a new
study session sets any prior studying row for that region to `idle` in the
same transaction.

`demo` accepts no member and starts detector eligibility immediately.
`verified` requires an enabled reservation and a matching, face-enrolled
member. `resting` and `idle` stop eligibility and reset detector state.

### D2: Fatigue uses strict seat-local face selection

Every normalized seat polygon is scaled from the decoded frame dimensions.
No in-seat face resets the detector. More than one in-seat face pauses the
seat as `ambiguous_face`. A face outside the polygon is never used as a
fallback.

For verified sessions, `FaceMatcher` must return `member:<member_id>` for the
single in-seat face before EAR/MAR state advances. Mismatch and unknown faces
pause as `identity_mismatch`; they do not generate fatigue alarms. Existing
IntrusionPlugin remains responsible for the separate `occupy` alarm.

### D3: Companion reminder delivery is separate from dashboard urgency

Fatigue alarms keep `level=1` so existing DingTalk notification and durable
alarm persistence remain intact. Their `extra.presentation` is `companion`.
The normal alarm WebSocket still carries the historical event, but Dashboard
must classify `fatigue` as informational: list it in history and never create
an active red region, beep, or flash.

A new `/ws/companion?user_id=&region_id=` subscription receives only fatigue
events whose `extra.user_id` and `region_id` match. This is functional routing
for the current unauthenticated demo; production authorization is explicitly
out of scope.

### D4: Companion uses explicit session selection

The page selects camera, seat, user ID, mode, and (for verified mode) enrolled
member. It displays stream readiness, reservation, status, identity state,
detector eligibility, pause reason, latest reminder, and DingTalk
configuration. It does not create or edit reservations.

## Risks

- Dlib recognition can be unavailable or uncertain. Verified mode fails
  closed: it shows a paused reason and does not run fatigue metrics.
- Existing production databases need the two nullable columns. Startup applies
  an additive compatibility migration; `init.sql` documents the full schema.
- The companion WebSocket has no user authentication because the application
  currently has no login/session layer. It is appropriate only for the local
  demonstration deployment.
