"""Alarm query, snapshot, and DingTalk confirmation APIs."""
import json
import os

from flask import Blueprint, Response, jsonify, request, send_from_directory

from ..config import Config

bp = Blueprint("alarms", __name__, url_prefix="/api/alarms")


@bp.get("")
def list_alarms():
    """List alarm records for the alarm center dashboard.
    ---
    tags:
      - Alarm
    summary: List alarm events
    description: >
      Query persisted alarm_event records for dashboards and other modules.
      Frontend dashboards can combine this REST list with the /ws/alarms
      WebSocket stream for realtime red-flash and buzzer behavior.
    parameters:
      - name: status
        in: query
        type: string
        required: false
        enum: [pending, notified, confirmed, escalated]
        description: Optional alarm status filter.
    responses:
      200:
        description: Alarm list ordered by created_at descending.
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: ok}
            data:
              type: array
              items:
                $ref: '#/definitions/AlarmEvent'
    definitions:
      AlarmEvent:
        type: object
        properties:
          id: {type: integer, example: 19}
          region_id: {type: integer, example: 3}
          camera_id: {type: integer, example: 1}
          type:
            type: string
            enum: [intrusion, fire_smoke, occupy, fatigue, fight]
            example: fight
          snapshot_url:
            type: string
            example: /api/alarms/snapshots/alarm_123_3_fight.jpg
          face_match:
            type: string
            description: member:<id> or stranger.
            example: stranger
          level:
            type: integer
            description: 0=private weak reminder, 1=normal, 2+=high/escalated.
            example: 2
          status:
            type: string
            enum: [pending, notified, confirmed, escalated]
            example: confirmed
          extra:
            type: object
            description: Detector-specific context, such as actor, behavior, fuse scores, boxes.
            additionalProperties: true
          created_at:
            type: string
            format: date-time
            example: "2026-07-09T14:30:00"
          confirmed_at:
            type: string
            format: date-time
            nullable: true
            example: "2026-07-09T14:31:12"
      AlarmConfirmResponse:
        type: object
        properties:
          code: {type: integer, example: 0}
          message: {type: string, example: ok}
          data:
            type: object
            properties:
              id: {type: integer, example: 19}
              status: {type: string, example: confirmed}
      AlarmErrorResponse:
        type: object
        properties:
          code: {type: integer, example: 404}
          message: {type: string, example: alarm not found}
          data:
            type: object
            properties:
              id: {type: integer, example: 404}
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
    """Confirm an alarm from an API client.
    ---
    tags:
      - Alarm
    summary: Confirm alarm by JSON API
    description: >
      Mark alarm_event.status as confirmed, set confirmed_at, set ack_at on
      related notification_log rows, and cancel the pending DingTalk escalation
      timer in the current backend process when it still exists.
    parameters:
      - name: alarm_id
        in: path
        type: integer
        required: true
        description: Alarm event ID.
    responses:
      200:
        description: Alarm confirmed.
        schema:
          $ref: '#/definitions/AlarmConfirmResponse'
      404:
        description: Alarm not found.
        schema:
          $ref: '#/definitions/AlarmErrorResponse'
    """
    payload, status_code = _confirm_alarm(alarm_id)
    return jsonify(**payload), status_code


@bp.get("/<int:alarm_id>/confirm")
def confirm_alarm_page(alarm_id: int):
    """Browser-friendly confirmation endpoint for DingTalk ActionCard.
    ---
    tags:
      - Alarm
    summary: Confirm alarm from DingTalk ActionCard
    description: >
      DingTalk ActionCard singleURL points here. It performs the same close-loop
      confirmation as POST /api/alarms/{alarm_id}/confirm, then returns a small
      text/html page such as "Alarm 19 confirmed / You can close this page."
    produces:
      - text/html
    parameters:
      - name: alarm_id
        in: path
        type: integer
        required: true
        description: Alarm event ID.
    responses:
      200:
        description: Alarm confirmed HTML page.
        schema:
          type: string
          example: "<h1>Alarm 19 confirmed</h1><p>You can close this page.</p>"
      404:
        description: Alarm not found HTML page.
        schema:
          type: string
          example: "<h1>Alarm 404 not found</h1><p>Please check the alarm center.</p>"
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
def get_snapshot(filename: str):
    """Serve an alarm snapshot image.
    ---
    tags:
      - Alarm
    summary: Get alarm snapshot
    description: >
      Returns a snapshot file saved by AlarmService.raise_alarm(). AlarmEvent
      snapshot_url values point to this endpoint.
    produces:
      - image/jpeg
      - image/png
      - application/octet-stream
    parameters:
      - name: filename
        in: path
        type: string
        required: true
        description: Snapshot filename under Config.SNAPSHOT_DIR.
    responses:
      200:
        description: Snapshot file.
        schema:
          type: file
      404:
        description: Snapshot not found.
    """
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
