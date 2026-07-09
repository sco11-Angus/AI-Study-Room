"""Alarm query, snapshot, and DingTalk confirmation APIs."""
import json
import os

from flask import Blueprint, Response, jsonify, request, send_from_directory
from flasgger import swag_from

from ..config import Config

bp = Blueprint("alarms", __name__, url_prefix="/api/alarms")
ALLOWED_ALARM_TYPES = {"intrusion", "fire_smoke", "occupy", "fatigue", "fight"}


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


@bp.post("/test-capture")
def create_test_capture_alarm():
    """Capture one stream frame and raise a task-E test alarm.
    ---
    tags:
      - Alarm
    summary: Capture stream frame and raise test alarm
    description: >
      Local/manual integration helper for task E while upstream stream and
      detector modules are still being integrated. The endpoint pulls one frame
      from an RTMP/RTSP/video source, saves it through AlarmService, persists an
      alarm_event row, broadcasts WebSocket payloads, and triggers DingTalk for
      level >= 1 alarms. Production continuous pull-stream scheduling remains
      owned by the stream scheduler module.
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [camera_id, region_id]
          properties:
            stream_url:
              type: string
              description: Optional stream URL. If omitted, camera.stream_url is used.
              example: rtmp://49.233.71.82:9090/live/test
            camera_id:
              type: integer
              example: 1
            region_id:
              type: integer
              example: 1
            type:
              type: string
              enum: [intrusion, fire_smoke, occupy, fatigue, fight]
              default: fight
            level:
              type: integer
              description: 0=private, 1=normal, 2+=high/escalated.
              default: 2
            actor:
              type: string
              description: Person/member name shown in the DingTalk card.
              example: 小明
            behavior:
              type: string
              description: Behavior/reason shown in the DingTalk card.
              example: 推搡同学，疑似发生肢体冲突
            face_match:
              type: string
              example: member:7
            extra:
              type: object
              additionalProperties: true
            timeout:
              type: number
              default: 8.0
            warmup_frames:
              type: integer
              default: 2
    responses:
      200:
        description: Alarm raised successfully.
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: ok}
            data:
              $ref: '#/definitions/AlarmEvent'
      400:
        description: Invalid request or stream capture failure.
        schema:
          $ref: '#/definitions/AlarmErrorResponse'
      409:
        description: Alarm was suppressed by region/type cooldown deduplication.
    """
    payload = request.get_json(silent=True) or {}

    try:
        region_id, camera_id, stream_url = _resolve_capture_target(payload)
        alarm_type = str(payload.get("type") or "fight").strip()
        if alarm_type not in ALLOWED_ALARM_TYPES:
            raise ValueError(f"type must be one of {sorted(ALLOWED_ALARM_TYPES)}")

        default_level = 2 if alarm_type == "fight" else 1
        level = _parse_int(payload.get("level", default_level), "level")
        timeout = _parse_float(payload.get("timeout", 8.0), "timeout")
        warmup_frames = _parse_int(payload.get("warmup_frames", 2), "warmup_frames")
        extra = _build_capture_extra(payload)
    except ValueError as exc:
        return jsonify(code=400, message=str(exc), data=None), 400

    from ..services.stream_capture import StreamCaptureError, capture_frame

    try:
        frame = capture_frame(stream_url, timeout=timeout, warmup_frames=warmup_frames, camera_id=camera_id)
    except StreamCaptureError as exc:
        return jsonify(code=400, message=str(exc), data=None), 400

    from ..detectors.base import AlarmEvent
    from ..services.alarm import get_alarm_service

    event = AlarmEvent(
        type=alarm_type,
        region_id=region_id,
        camera_id=camera_id,
        level=level,
        face_match=str(payload.get("face_match") or extra.get("face_match") or ""),
        extra=extra,
        snapshot=frame,
    )
    result = get_alarm_service().raise_alarm(event, frame=frame)
    if result is None:
        return jsonify(code=409, message="alarm deduplicated", data=None), 409
    return jsonify(code=0, message="ok", data=result)


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


def _resolve_capture_target(payload: dict) -> tuple[int, int, str]:
    region_id = _optional_int(payload.get("region_id"), "region_id")
    camera_id = _optional_int(payload.get("camera_id"), "camera_id")
    stream_url = str(payload.get("stream_url") or "").strip()

    needs_resolve = region_id is None or camera_id is None or not stream_url
    if needs_resolve:
        from ..models.database import SessionLocal
        from ..models.entities import Camera, Region

        session = SessionLocal()
        try:
            if region_id is not None and (camera_id is None or not stream_url):
                region = session.get(Region, region_id)
                if region is None:
                    raise ValueError(f"region_id {region_id} not found")
                if camera_id is None:
                    camera_id = int(region.camera_id or 0)

            if camera_id is not None and region_id is None:
                region = (
                    session.query(Region)
                    .filter(Region.camera_id == camera_id)
                    .order_by(Region.id.asc())
                    .first()
                )
                if region is None:
                    raise ValueError(f"no region found for camera_id {camera_id}")
                region_id = int(region.id)

            if camera_id is not None and not stream_url:
                camera = session.get(Camera, camera_id)
                if camera is None:
                    raise ValueError(f"camera_id {camera_id} not found")
                stream_url = str(camera.stream_url or "").strip()
        finally:
            session.close()

    if camera_id is None or camera_id < 0:
        raise ValueError("camera_id is required")
    if region_id is None or region_id < 0:
        raise ValueError("region_id is required")
    if not stream_url:
        raise ValueError("stream_url is required")
    return region_id, camera_id, stream_url


def _build_capture_extra(payload: dict) -> dict:
    raw_extra = payload.get("extra")
    if raw_extra is None:
        extra = {}
    elif isinstance(raw_extra, dict):
        extra = dict(raw_extra)
    else:
        raise ValueError("extra must be an object")

    for key in ("actor", "behavior", "face_match", "fuse", "vis_score", "aud_score"):
        if payload.get(key) is not None:
            extra[key] = payload[key]
    extra.setdefault("source", "task_e_test_capture")
    return extra


def _optional_int(value, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    return _parse_int(value, field_name)


def _parse_int(value, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _parse_float(value, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if result <= 0:
        raise ValueError(f"{field_name} must be positive")
    return result


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
