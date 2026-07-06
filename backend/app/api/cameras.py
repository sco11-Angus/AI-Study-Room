"""摄像头接口 (§9.1)。"""
from flask import Blueprint, jsonify

bp = Blueprint("cameras", __name__, url_prefix="/api/cameras")


@bp.get("")
def list_cameras():
    """摄像头列表及流地址
    ---
    tags: [Camera]
    responses:
      200: {description: 摄像头列表}
    """
    # TODO: 查询 camera 表，返回 stream_url / resolution / status
    return jsonify(code=0, message="ok", data=[])
