# Capability Index

This file is the navigation index for accepted OpenSpec capability contracts. Detailed, testable requirements live in `openspec/specs/<capability>/spec.md`.

| Capability | Contract | Primary ownership |
| --- | --- | --- |
| stream-scheduler | `stream-scheduler/spec.md` | backend stream scheduling and camera health |
| region-config | `region-config/spec.md` | frontend drawing and backend region persistence |
| intrusion-detect | `intrusion-detect/spec.md` | person detection, geometry, and intrusion alarms |
| seat-status | `seat-status/spec.md` | study state and fatigue activation |
| fire-smoke-detect | `fire-smoke-detect/spec.md` | fire/smoke inference and false-positive suppression |
| alarm-closeloop | `alarm-closeloop/spec.md` | snapshots, persistence, dashboard, notification, and confirmation |

## Change Policy

New functionality must be proposed under `openspec/changes/<verb-noun-change-id>/`. The proposal supplies delta specs; after acceptance and verification, `openspec archive` merges those deltas into the capability contracts above.
