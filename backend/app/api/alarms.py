"""Alarm query, snapshot, and DingTalk confirmation APIs."""
import json
import os
from pathlib import Path
from datetime import datetime
from html import escape
import cv2
import numpy as np
from flask import Blueprint, Response, jsonify, request, send_from_directory
from flasgger import swag_from

from ..config import Config

bp = Blueprint("alarms", __name__, url_prefix="/api/alarms")
ALLOWED_ALARM_TYPES = {"intrusion", "fire_smoke", "occupy", "fatigue", "fight", "face_recognition", "face_spoof"}


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
            enum: [intrusion, fire_smoke, occupy, fatigue, fight, face_recognition, face_spoof]
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
        records = query.order_by(AlarmEvent.created_at.desc()).limit(20).all()
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
              enum: [intrusion, fire_smoke, occupy, fatigue, fight, face_recognition, face_spoof]
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


@bp.post("/fire-smoke/detect")
def detect_fire_smoke_image():
    """Run the grafted fire/smoke model through the backend.
    ---
    tags:
      - Alarm
      - FireSmoke
    summary: Detect fire/smoke in one image
    description: >
      Backend-facing integration endpoint for the grafted legacy YOLOv5
      fire/smoke model. Upload an image file with multipart/form-data field
      "image", or send JSON with image_path. Set frames to FIRE_WINDOW when
      you want to exercise the 30-frame debounce logic; set raise_alarm=true
      to persist and broadcast produced fire_smoke AlarmEvents.
    consumes:
      - multipart/form-data
      - application/json
    parameters:
      - name: image
        in: formData
        type: file
        required: false
      - name: body
        in: body
        required: false
        schema:
          type: object
          properties:
            image_path:
              type: string
              example: test_photos/fire_test.jpg
            camera_id:
              type: integer
              default: 5
            region_id:
              type: integer
              default: 0
            frames:
              type: integer
              default: 1
            raise_alarm:
              type: boolean
              default: false
    responses:
      200:
        description: Detection result.
      400:
        description: Invalid image or request parameters.
    """
    payload = request.get_json(silent=True) or {}
    try:
        image = _read_request_image(payload)
        camera_id = _parse_int(_request_value(payload, "camera_id", 5), "camera_id")
        region_id = _optional_int(_request_value(payload, "region_id", None), "region_id")
        frames = _parse_int(_request_value(payload, "frames", 1), "frames")
        should_raise = _parse_bool(_request_value(payload, "raise_alarm", False))
    except ValueError as exc:
        return jsonify(code=400, message=str(exc), data=None), 400

    from ..services.fire_smoke import detect_fire_smoke_image as run_detection

    try:
        data = run_detection(
            image,
            camera_id=camera_id,
            region_id=region_id,
            frames=frames,
            raise_alarm=should_raise,
        )
    except Exception as exc:
        return jsonify(code=500, message=f"fire_smoke detection failed: {exc}", data=None), 500
    return jsonify(code=0, message="ok", data=data)


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
      confirmation as POST /api/alarms/{alarm_id}/confirm, then returns a
      text/html detail page with message, snapshot, clip link, and key context.
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
          example: "<h1>Alarm 19 confirmed</h1><p>告警已确认...</p>"
      404:
        description: Alarm not found HTML page.
        schema:
          type: string
          example: "<h1>Alarm 404 not found</h1><p>Please check the alarm center.</p>"
    """
    payload, status_code = _confirm_alarm(alarm_id)
    if status_code == 200:
        body = _render_confirm_page(alarm_id)
    else:
        body = _render_not_found_page(alarm_id)
    return Response(body, status=status_code, mimetype="text/html")


@bp.get("/clips/<path:filename>")
@swag_from({
    "tags": ["Alarm"],
    "summary": "Get an alarm video clip",
    "description": (
        "Returns the saved video clip referenced by AlarmEvent.clip_url. "
        "Supports HTTP Range requests for seeking."
    ),
    "parameters": [
        {"name": "filename", "in": "path", "type": "string", "required": True},
    ],
    "responses": {
        200: {
            "description": "Video clip bytes",
            "content": {
                "video/mp4": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        },
        206: {
            "description": "Partial content for range requests",
        },
        404: {"description": "Clip not found"},
    },
})
def get_clip(filename: str):
    """Serve an alarm video clip.
    ---
    tags:
      - Alarm
    summary: Get alarm video clip
    description: >
      Returns a video clip saved by ClipRecorder. AlarmEvent
      clip_url values point to this endpoint. Supports HTTP Range
      for seeking/progress bar.
    produces:
      - video/mp4
    parameters:
      - name: filename
        in: path
        type: string
        required: true
        description: Clip filename under Config.CLIP_DIR.
    responses:
      200:
        description: Full clip file.
        schema:
          type: file
      206:
        description: Partial clip for range request.
      404:
        description: Clip not found.
    """
    clip_path = os.path.join(os.path.abspath(Config.CLIP_DIR), filename)
    if not os.path.exists(clip_path):
        return jsonify(code=404, message="clip not found", data=None), 404
    return send_from_directory(os.path.abspath(Config.CLIP_DIR), filename)


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


def _render_confirm_page(alarm_id: int) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Alarm {alarm_id} confirmed</title>
  <style>
    body {{ font-family: Arial, "Microsoft YaHei", sans-serif; max-width: 520px; margin: 72px auto; padding: 0 20px; color: #1f2933; text-align: center; }}
    h1 {{ font-size: 24px; margin-bottom: 12px; }}
    p {{ color: #52616b; line-height: 1.6; }}
    .ok {{ color: #0f766e; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>Alarm {alarm_id} confirmed</h1>
  <p class="ok">告警已确认。</p>
  <p>状态已同步到告警中心，可以关闭此页面。</p>
</body>
</html>"""


def _render_not_found_page(alarm_id: int) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Alarm Not Found</title></head>
<body><h1>Alarm {alarm_id} not found</h1><p>Please check the alarm center.</p></body>
</html>"""


def _load_alarm_payload(alarm_id: int) -> dict | None:
    from ..models.database import SessionLocal
    from ..models.entities import AlarmEvent

    session = SessionLocal()
    try:
        record = session.get(AlarmEvent, alarm_id)
        if record is None:
            return None
        return _serialize_alarm(record)
    finally:
        session.close()


def _public_http_url(path_or_url: str) -> str:
    if not path_or_url:
        return ""
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    if Config.PUBLIC_BASE_URL:
        path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
        return f"{Config.PUBLIC_BASE_URL}{path}"
    return path_or_url


def _fallback_message(alarm: dict) -> str:
    extra = alarm.get("extra") or {}
    actor = extra.get("actor") or extra.get("person") or extra.get("student") or "未知人员"
    behavior = extra.get("behavior") or extra.get("action") or extra.get("reason") or "触发告警规则"
    return f"{actor}因{behavior}触发{alarm.get('type') or '告警'}"


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


@bp.get("/daily-report")
def get_daily_report():
    """Get daily monitoring report.
    ---
    tags:
      - Alarm
    summary: Get daily monitoring report
    description: >
      Generate and return the daily monitoring report with statistics,
      top alarms, recommendations, and detailed alarm list.
    parameters:
      - name: date
        in: query
        type: string
        format: date
        required: false
        description: Date in YYYY-MM-DD format. Defaults to yesterday.
      - name: format
        in: query
        type: string
        enum: [json, markdown]
        default: json
        description: Output format.
    responses:
      200:
        description: Daily report.
    """
    from ..services.daily_report import get_report_service

    date_str = request.args.get("date")
    out_format = request.args.get("format", "json")

    report_date = None
    if date_str:
        try:
            report_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify(code=400, message="invalid date format, use YYYY-MM-DD"), 400

    service = get_report_service()

    if out_format == "markdown":
        md = service.generate_markdown(report_date)
        return Response(md, mimetype="text/markdown")

    report = service.generate_report(report_date)
    return jsonify(code=0, message="ok", data=report)


@bp.get("/storage-status")
def get_storage_status():
    from ..services.storage_manager import get_storage_manager

    try:
        stats = get_storage_manager().get_storage_stats()
        return jsonify(code=0, message="ok", data=stats)
    except Exception as e:
        return jsonify(code=500, message=f"failed to get storage status: {str(e)}"), 500


def _request_value(payload: dict, key: str, default):
    if key in request.form:
        return request.form.get(key)
    return payload.get(key, default)


def _read_request_image(payload: dict) -> np.ndarray:
    upload = request.files.get("image")
    if upload is not None:
        data = upload.read()
        if not data:
            raise ValueError("uploaded image is empty")
        array = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("uploaded image could not be decoded")
        return image

    image_path = str(payload.get("image_path") or request.form.get("image_path") or "").strip()
    if not image_path:
        raise ValueError("image file or image_path is required")
    path = Path(image_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"image_path could not be read: {path}")
    return image


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    raise ValueError("raise_alarm must be a boolean")


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
        "clip_url": record.clip_url or "",
        "face_match": record.face_match or "",
        "message": record.message or "",
        "level": record.level,
        "status": record.status,
        "extra": extra,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "confirmed_at": record.confirmed_at.isoformat() if record.confirmed_at else None,
    }
