"""告警接口 — 查询与钉钉确认回调 (§7, §9)。"""
from flask import Blueprint, jsonify, request
from .response import ok

bp = Blueprint("alarms", __name__, url_prefix="/api/alarms")


@bp.get("")
def list_alarms():
    """告警列表查询
    ---
    tags: [Alarm]
    parameters:
      - {name: status, in: query, type: string, enum: [pending, notified, confirmed, escalated]}
    responses:
      200:
        description: 告警列表
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: success}
            data: {type: array, items: {$ref: '#/definitions/AlarmEvent'}}
    """
    status = request.args.get("status")
    return ok([])


@bp.post("/<int:alarm_id>/confirm")
def confirm_alarm(alarm_id: int):
    """安全员确认处理（钉钉卡片回调）— 停止升级计时 (§7.4)
    ---
    tags: [Alarm]
    parameters:
      - {name: alarm_id, in: path, type: integer, required: true}
    responses:
      200:
        description: 已确认
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: success}
            data: {type: object}
    """
    # TODO: 标记 status=confirmed, 记录 confirmed_at, 取消 ESCALATE_TIMEOUT 计时
    return ok({"id": alarm_id})
