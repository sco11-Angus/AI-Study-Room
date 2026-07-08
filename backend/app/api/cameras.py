"""摄像头接口 (§9.1)。"""
from flask import Blueprint, jsonify
from .response import ok

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
    # TODO: 查询 camera 表，返回 stream_url / resolution / status
    return ok([])
