"""摄像头接口 (§9.1)。"""
from flask import Blueprint, jsonify
from .response import ok

from ..models.database import SessionLocal
from ..models.entities import Camera

bp = Blueprint("cameras", __name__, url_prefix="/api/cameras")


@bp.get("")
def list_cameras():
    """摄像头列表及流地址
    ---
    tags: [Camera, FireSmoke]
    summary: List camera sources
    description: Other modules use camera_id and stream_url from this endpoint to bind a video source to the fire/smoke detector and the live preview stream.
    responses:
      200:
        description: 摄像头列表
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: success}
            data: {type: array, items: {$ref: '#/definitions/Camera'}}
    definitions:
      Camera:
        type: object
        properties:
          id: {type: integer}
          name: {type: string}
          stream_url: {type: string}
          resolution: {type: string}
          status: {type: string}
    """
    session = SessionLocal()
    try:
        cameras = session.query(Camera).all()
        data = [
            {
                'id': cam.id,
                'name': cam.name,
                'stream_url': cam.stream_url,
                'resolution': cam.resolution,
                'status': cam.status,
            }
            for cam in cameras
        ]
        return ok(data)
    finally:
        session.close()


@bp.get("/<int:camera_id>/stream-status")
def get_stream_status(camera_id: int):
    """Get live scheduler status for one camera.
    ---
    tags: [Camera, Stream]
    summary: Get stream scheduler status
    description: >
      Diagnostic endpoint for live preview, snapshot capture, and playback.
      It reports whether StreamScheduler is running, whether the camera is
      registered/online, and whether a decoded JPEG frame is already available
      in the scheduler ring buffer.
    parameters:
      - name: camera_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Scheduler status for the camera.
    """
    from ..stream.scheduler import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:
        return ok({
            "scheduler_started": False,
            "camera_id": camera_id,
            "registered": False,
            "online": False,
            "has_frame": False,
            "latest_frame_bytes": 0,
            "ring_buffer_len": 0,
            "pre_buffer_len": 0,
            "camera_ids": [],
        })

    cam = scheduler.get_camera(camera_id)
    if cam is None:
        return ok({
            "scheduler_started": True,
            "camera_id": camera_id,
            "registered": False,
            "online": False,
            "has_frame": False,
            "latest_frame_bytes": 0,
            "ring_buffer_len": 0,
            "pre_buffer_len": 0,
            "camera_ids": scheduler.camera_ids,
        })

    jpg = cam.latest_frame()
    return ok({
        "scheduler_started": True,
        "camera_id": camera_id,
        "registered": True,
        "online": bool(cam.online),
        "stream_name": cam.stream_name,
        "stream_url": str(cam.stream_url),
        "has_frame": jpg is not None,
        "latest_frame_bytes": len(jpg) if jpg else 0,
        "ring_buffer_len": len(cam.ring_buffer),
        "pre_buffer_len": len(cam.pre_buffer),
        "camera_ids": scheduler.camera_ids,
    })
