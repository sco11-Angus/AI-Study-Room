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
    tags: [Camera]
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
