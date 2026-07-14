## 1. Session Model and API

- [x] 1.1 Add `mode` and `member_id` to SeatStatus plus additive SQLite/MySQL compatibility migration and bootstrap SQL.
- [x] 1.2 Validate demo and verified study-session requests, reservation/member consistency, and one-active-session-per-seat behavior.
- [x] 1.3 Return session, reservation, stream, and fatigue runtime state from the companion status endpoint.

## 2. Fatigue Identity Gating

- [x] 2.1 Load active sessions with their seat polygons and reservation information.
- [x] 2.2 Scale polygons using each decoded frame and reject zero or multiple in-seat faces.
- [x] 2.3 Implement verified face-match gating and expose deterministic pause reasons.
- [x] 2.4 Preserve EAR/MAR temporal filtering and enrich fatigue evidence with mode and identity state.

## 3. Reminder Delivery and Frontend

- [x] 3.1 Add companion-scoped fatigue WebSocket delivery while keeping persistence and DingTalk notification.
- [x] 3.2 Exclude fatigue from Dashboard active red-region, flash, and beep logic while retaining history rows.
- [x] 3.3 Rebuild companion controls around explicit camera, seat, user, mode, and verified-member selection.

## 4. Verification and Records

- [x] 4.1 Add focused backend tests for demo, verified, outside-face, multi-face, rest, cooldown, API validation, and routing.
- [x] 4.2 Add frontend build validation and dashboard/companion behavior checks.
- [x] 4.3 Run strict OpenSpec validation, standard startup validation, and record live RTMP acceptance prerequisites.
