"""Seed a minimal demo setup for fatigue detection.

Run inside the backend container or from backend/ with the same DATABASE_URI.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Config
from app.models.database import SessionLocal, init_db
from app.models.entities import AppUser, Camera, Region, SeatStatus


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--camera-id", type=int, default=0)
    parser.add_argument("--region-id", type=int, default=5)
    parser.add_argument(
        "--status",
        choices=("idle", "studying", "resting"),
        default="studying",
    )
    parser.add_argument("--stream-name", default="test")
    parser.add_argument("--rtmp-server", default=Config.RTMP_SERVER)
    parser.add_argument("--rtmp-port", type=int, default=Config.RTMP_PORT)
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        camera = db.get(Camera, args.camera_id) or Camera(id=args.camera_id)
        camera.name = "demo-camera"
        camera.stream_url = (
            f"rtmp://{args.rtmp_server}:{args.rtmp_port}/live/{args.stream_name}"
        )
        camera.resolution = "640x360"
        camera.status = "active"

        user = db.get(AppUser, args.user_id) or AppUser(id=args.user_id)
        user.nickname = "demo-user"

        region = db.get(Region, args.region_id) or Region(id=args.region_id)
        region.camera_id = args.camera_id
        region.user_id = args.user_id
        region.name = "demo-seat"
        region.type = "seat"
        region.polygon = json.dumps([[0, 0], [640, 0], [640, 360], [0, 360]])
        region.x_distance = 0
        region.y_stay_time = 0

        status = (
            db.query(SeatStatus)
            .filter(
                SeatStatus.user_id == args.user_id,
                SeatStatus.region_id == args.region_id,
            )
            .one_or_none()
        )
        if status is None:
            status = SeatStatus(user_id=args.user_id, region_id=args.region_id)
        status.status = args.status

        db.add_all([camera, user, region, status])
        db.commit()
        print(
            "seeded demo fatigue setup: "
            f"user_id={args.user_id}, region_id={args.region_id}, status={args.status}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
