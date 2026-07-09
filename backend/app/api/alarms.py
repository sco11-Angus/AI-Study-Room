"""告警接口 — 查询与钉钉确认回调 (§7, §9)。"""
import json
import os

from flask import Blueprint, Response, jsonify, request, send_from_directory
from flasgger import swag_from

from ..config import Config

bp = Blueprint("alarms", __name__, url_prefix="/api/alarms")


@bp.get("")
def list_alarms():
    """告警列表查询
    ---
    tags: [Alarm, FireSmoke]
    summary: List persisted alarm events
    description: Fire/smoke detector hits are persisted here as AlarmEvent records with type=fire_smoke and fire/smoke confidence details in extra.
    parameters:
      - {name: status, in: query, type: string, enum: [pending, notified, confirmed, escalated], description: Optional alarm status filter}
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
    from ..models.database import SessionLocal
    from ..models.entities import AlarmEvent

    session = SessionLocal()
    try:
        query = session.query(AlarmEvent)
        if status:
            query = query.filter(AlarmEvent.status == status)
        records = query.order_by(AlarmEvent.created_at.desc()).all()
        return jsonify(code=0, message="ok", data=[_serialize_alarm(r) for r in records])
    finally:
        session.close()


@bp.post("/<int:alarm_id>/confirm")
def confirm_alarm(alarm_id: int):
    """安全员确认处理（钉钉卡片回调）— 停止升级计时 (§7.4)
    ---
    tags: [Alarm, FireSmoke]
    summary: Confirm an alarm
    description: Confirms an alarm and stops DingTalk escalation. Fire/smoke alarms use the same confirmation endpoint.
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
    payload, status_code = _confirm_alarm(alarm_id)
    return jsonify(**payload), status_code


@bp.get("/<int:alarm_id>/confirm")
def confirm_alarm_page(alarm_id: int):
    """Browser-friendly DingTalk alarm confirmation page.
    ---
    tags: [Alarm, FireSmoke]
    summary: Confirm an alarm from a browser link
    description: DingTalk ActionCard buttons can open this endpoint. Fire/smoke alarms use it to mark the same AlarmEvent as confirmed.
    parameters:
      - {name: alarm_id, in: path, type: integer, required: true}
    responses:
      200:
        description: Alarm confirmed and an HTML success page is returned
        content:
          text/html:
            schema: {type: string}
      404:
        description: Alarm was not found
        content:
          text/html:
            schema: {type: string}
    """
    payload, status_code = _confirm_alarm(alarm_id)
    if status_code == 200:
        body = f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Alarm Confirmed</title></head>
<body><h1>Alarm {alarm_id} confirmed</h1><p>You can close this page.</p></body>
</html>"""
    else:
        body = f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Alarm Not Found</title></head>
<body><h1>Alarm {alarm_id} not found</h1><p>Please check the alarm center.</p></body>
</html>"""
    return Response(body, status=status_code, mimetype="text/html")


@bp.get("/snapshots/<path:filename>")
@swag_from({
    "tags": ["Alarm", "FireSmoke"],
    "summary": "Get an alarm snapshot image",
    "description": (
        "Returns the saved snapshot referenced by AlarmEvent.snapshot_url. "
        "Fire/smoke alarms can use this image for review and DingTalk cards."
    ),
    "parameters": [
        {"name": "filename", "in": "path", "type": "string", "required": True},
    ],
    "responses": {
        200: {
            "description": "Snapshot image bytes",
            "content": {
                "image/jpeg": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        },
        404: {"description": "Snapshot not found"},
    },
})
def get_snapshot(filename: str):
    """访问告警抓拍图。"""
    return send_from_directory(os.path.abspath(Config.SNAPSHOT_DIR), filename)


def _confirm_alarm(alarm_id: int) -> tuple[dict, int]:
    from ..services.dingtalk import get_notifier

    confirmed = get_notifier().confirm(alarm_id)
    if not confirmed:
        return {"code": 404, "message": "alarm not found", "data": {"id": alarm_id}}, 404
    return {"code": 0, "message": "ok", "data": {"id": alarm_id, "status": "confirmed"}}, 200


def _serialize_alarm(record) -> dict:
    extra = {}
    if record.extra:
        try:
            extra = json.loads(record.extra)
        except json.JSONDecodeError:
            extra = {}
    return {
        "id": record.id,
        "region_id": record.region_id,
        "camera_id": record.camera_id,
        "type": record.type,
        "snapshot_url": record.snapshot_url or "",
        "face_match": record.face_match or "",
        "level": record.level,
        "status": record.status,
        "extra": extra,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "confirmed_at": record.confirmed_at.isoformat() if record.confirmed_at else None,
    }
