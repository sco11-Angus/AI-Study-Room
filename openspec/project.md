# AI Study Room OpenSpec Context

## Product

AI Study Room is a real-time video analysis and monitoring system for shared study rooms. It combines camera streams, computer-vision detectors, a Vue management dashboard, persistent alarms, and DingTalk notifications to turn detected risks into an auditable response loop.

## Architecture

- Backend: Python, Flask, OpenCV, YOLOv8n, Dlib, SQLAlchemy.
- Streaming: RTMP through Nginx-RTMP and the backend stream scheduler.
- Frontend: Vue 3, Element Plus, Pinia, and WebSocket/MJPEG video delivery.
- Deployment: Docker and Jenkins.

## OpenSpec Rules

- Every new module or cross-module behavior starts as an active change in `openspec/changes/<change-id>/`.
- A change must contain `proposal.md`, `design.md`, `tasks.md`, and delta specs for every affected capability before implementation begins.
- `npm run spec:validate` must pass before implementation and before a change is archived.
- Capability contracts live in `openspec/specs/<capability>/spec.md`; `feature_list.json` remains the source of truth for delivery status.
- Completed changes are archived only after implementation evidence, tests, and progress records have been updated.

## Repository Map

- `openspec/specs/spec.md`: capability index and ownership map.
- `openspec/specs/<capability>/spec.md`: accepted capability contract.
- `openspec/changes/`: active changes and OpenSpec-managed archives.
- `openspec/proposals/`: legacy reference material only; do not create new proposals here.
- `openspec/tasks/`: original assignment material and collaboration guidance.
- `openspec/progress/`: verified state and engineering handoff notes.
