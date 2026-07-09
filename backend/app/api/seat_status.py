"""自习状态宣告接口 — 激活/挂起疲劳算法 (§4, §9)。"""
from flask import Blueprint, jsonify, request
from .response import ok

bp = Blueprint("seat_status", __name__, url_prefix="/api/seat-status")


@bp.post("")
def switch_status():
    """用户切换自习/休息状态
    ---
    tags: [SeatStatus, Region]
    summary: Switch seat study status
    description: This endpoint controls study/rest state for fatigue logic. It is not a fire/smoke switch, but it shares region_id with region-based alarm display.
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [user_id, region_id, status]
          properties:
            user_id: {type: integer}
            region_id: {type: integer}
            status: {type: string, enum: [idle, studying, resting]}
    responses:
      200:
        description: 状态已更新
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: success}
            data: {type: object}
    """
    payload = request.get_json(force=True)
    # TODO: studying -> 激活该 region 疲劳检测; resting -> 挂起并释放算力 (§4.2)
    return ok(payload)
