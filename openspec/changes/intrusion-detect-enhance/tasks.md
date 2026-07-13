## 1. Data Model and API

- [x] 1.1 Add `SeatReservation` with a unique `region_id`, `member_id`, `enabled`, and audit timestamps.
- [x] 1.2 Add the `seat_reservation` DDL to `init.sql` for MySQL deployment.
- [x] 1.3 Keep SQLite development initialization through `Base.metadata.create_all()`; production MySQL applies the idempotent `init.sql` table definition.
- [x] 1.4 Add `GET /api/members?face_enrolled=true` for members with usable face features.
- [x] 1.5 Add reservation list, idempotent bind/update, and unbind APIs with seat/member validation and intrusion hot reload.
- [x] 1.6 Register the new blueprints and add reservation API tests for validation, lifecycle, and hot reload.

## 2. Seat Identity Detection

- [x] 2.1 Load active identity checks from `SeatReservation` joined with `Region` and `Member`, independent of `seat_status`.
- [x] 2.2 Track each person in each reserved seat with lightweight IoU matching and independent dwell timers.
- [x] 2.3 Use full-frame face detection and face-center-to-person-box association before `encode_from_rect()`; retain a legacy fake/test fallback.
- [x] 2.4 Treat the reserved member as allowed and every other known member or stranger as `occupy` after the configured dwell time.
- [x] 2.5 Reset a timer when a person explicitly exits a seat and expire temporarily missing tracks after three inference frames.
- [x] 2.6 Standardize `unauthorized_seat` evidence and replace the outdated long-occupancy alarm wording.

## 3. Tests

- [x] 3.1 Cover reserved-member pass, known non-reserved member, stranger, simultaneous owner plus stranger, exit/re-entry reset, hot bind, and unbind.
- [x] 3.2 Cover reservation API validation, list, update, delete, and engine hot reload.
- [x] 3.3 Cover the human-readable non-reserved-seat alarm description.

## 4. Frontend Integration

- [x] 4.1 Add a face-enrolled member selector for saved `seat` regions in RegionConfig.
- [x] 4.2 Show current binding and provide bind/unbind actions that refresh reservation state without a page reload.
- [x] 4.3 Keep reservation controls hidden for `danger_zone` regions.

## 5. Verification

- [x] 5.1 Run SQLite focused regression: intrusion, identity, reservations, face, fatigue, and alarm center tests.
- [x] 5.2 Run `npm.cmd --prefix frontend run build`.
- [x] 5.3 Run `npm run spec:validate` and `./init.cmd`.
- [ ] 5.4 Perform live local-camera acceptance: draw a seat, bind member A, confirm A is allowed, confirm B/stranger raises an alarm, then unbind and confirm identity checking stops.
