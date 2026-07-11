"""Verify task E against the real database configured in .env.

This script is intentionally small and explicit:
- loads DATABASE_URI from repo .env, including PowerShell-style $env: lines;
- applies the nullable columns required by the alarm close-loop workflow;
- seeds minimal camera/region/guard rows when absent;
- raises real alarm records, writes notification logs, confirms one alarm,
  and escalates another without calling an external DingTalk webhook.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise RuntimeError(".env not found")

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("$env:"):
            key = key[len("$env:") :]
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def patch_schema(engine) -> None:
    statements = [
        "ALTER TABLE alarm_event MODIFY confirmed_at DATETIME NULL",
        "ALTER TABLE notification_log MODIFY ack_at DATETIME NULL",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def seed_minimum(engine) -> tuple[int, int]:
    with engine.begin() as conn:
        camera_id = conn.execute(text("SELECT id FROM camera ORDER BY id LIMIT 1")).scalar()
        if camera_id is None:
            result = conn.execute(
                text(
                    "INSERT INTO camera (name, stream_url, resolution, status, created_at) "
                    "VALUES (:name, :stream_url, :resolution, :status, NOW())"
                ),
                {
                    "name": "TaskE Verify Camera",
                    "stream_url": "rtmp://49.233.71.82:9090/live/task-e",
                    "resolution": "640x360",
                    "status": "online",
                },
            )
            camera_id = result.lastrowid

        region_id = conn.execute(text("SELECT id FROM region ORDER BY id LIMIT 1")).scalar()
        if region_id is None:
            result = conn.execute(
                text(
                    "INSERT INTO region "
                    "(camera_id, user_id, name, type, polygon, x_distance, y_stay_time, created_at) "
                    "VALUES (:camera_id, NULL, :name, :type, :polygon, :x_distance, :y_stay_time, NOW())"
                ),
                {
                    "camera_id": camera_id,
                    "name": "TaskE Verify Region",
                    "type": "danger_zone",
                    "polygon": json.dumps([[0, 0], [100, 0], [100, 100], [0, 100]]),
                    "x_distance": 50,
                    "y_stay_time": 10,
                },
            )
            region_id = result.lastrowid

        for role, name in (("primary", "TaskE Primary Guard"), ("leader", "TaskE Leader Guard")):
            guard_id = conn.execute(
                text("SELECT id FROM guard WHERE role = :role ORDER BY priority, id LIMIT 1"),
                {"role": role},
            ).scalar()
            if guard_id is None:
                conn.execute(
                    text(
                        "INSERT INTO guard (name, dingtalk_id, role, priority) "
                        "VALUES (:name, :dingtalk_id, :role, :priority)"
                    ),
                    {
                        "name": name,
                        "dingtalk_id": f"task-e-{role}",
                        "role": role,
                        "priority": 0,
                    },
                )

    return int(camera_id), int(region_id)


class CapturingBroadcaster:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> int:
        self.payloads.append(payload)
        return 1


def run_alarm_flow(camera_id: int, region_id: int) -> dict:
    from app.detectors.base import AlarmEvent
    from app.models.database import SessionLocal
    from app.models.entities import AlarmEvent as AlarmRecord
    from app.models.entities import NotificationLog
    from app.services.alarm import AlarmService
    from app.services.dingtalk import DingTalkNotifier

    notifier = DingTalkNotifier(webhook="", leader_webhook="", timeout=0, session_factory=SessionLocal)
    broadcaster = CapturingBroadcaster()
    service = AlarmService(cooldown=0, notifier=notifier, broadcaster=broadcaster)
    run_id = f"task-e-real-db-{int(time.time())}"

    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    fight = service.raise_alarm(
        AlarmEvent(
            type="fight",
            region_id=region_id,
            camera_id=camera_id,
            level=2,
            extra={"source": "task_e_real_db_verify", "run_id": run_id, "case": "confirm"},
        ),
        frame=frame,
    )
    assert fight is not None
    assert notifier.confirm(fight["id"]) is True

    intrusion = service.raise_alarm(
        AlarmEvent(
            type="intrusion",
            region_id=region_id,
            camera_id=camera_id,
            level=1,
            extra={"source": "task_e_real_db_verify", "run_id": run_id, "case": "escalate"},
        )
    )
    assert intrusion is not None
    notifier._escalate(intrusion["id"])

    fatigue = service.raise_alarm(
        AlarmEvent(
            type="fatigue",
            region_id=region_id,
            camera_id=camera_id,
            level=0,
            extra={"source": "task_e_real_db_verify", "run_id": run_id, "case": "private_only"},
        )
    )
    assert fatigue is not None

    session = SessionLocal()
    try:
        fight_record = session.get(AlarmRecord, fight["id"])
        intrusion_record = session.get(AlarmRecord, intrusion["id"])
        fatigue_record = session.get(AlarmRecord, fatigue["id"])
        assert fight_record.status == "confirmed"
        assert fight_record.confirmed_at is not None
        assert intrusion_record.status == "escalated"
        assert intrusion_record.level >= 2
        assert fatigue_record.status == "pending"

        logs = (
            session.query(NotificationLog)
            .filter(NotificationLog.alarm_id.in_([fight["id"], intrusion["id"], fatigue["id"]]))
            .order_by(NotificationLog.alarm_id, NotificationLog.stage)
            .all()
        )
        stages = [(log.alarm_id, log.stage, log.ack_at is not None) for log in logs]
        assert (fight["id"], "primary", True) in stages
        assert (intrusion["id"], "primary", False) in stages
        assert (intrusion["id"], "escalated", False) in stages
        assert all(log.alarm_id != fatigue["id"] for log in logs)
    finally:
        session.close()

    return {
        "run_id": run_id,
        "alarm_ids": {
            "confirmed_fight": fight["id"],
            "escalated_intrusion": intrusion["id"],
            "private_fatigue": fatigue["id"],
        },
        "broadcast_count": len(broadcaster.payloads),
    }


def main() -> None:
    load_env()
    uri = os.environ.get("DATABASE_URI")
    if not uri:
        raise RuntimeError("DATABASE_URI is missing")
    engine = create_engine(uri, pool_pre_ping=True)
    with engine.connect() as conn:
        db_name = conn.execute(text("SELECT DATABASE()")).scalar()
    print(f"connected database: {db_name}")
    print("tables: " + ",".join(inspect(engine).get_table_names()))

    patch_schema(engine)
    camera_id, region_id = seed_minimum(engine)
    print(f"seed camera_id={camera_id}, region_id={region_id}")

    result = run_alarm_flow(camera_id, region_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("TASK_E_REAL_DB_VERIFY_OK")


if __name__ == "__main__":
    main()
