"""告警接口 — 查询与钉钉确认回调 (§7, §9)。"""
import json
import os

from flask import Blueprint, jsonify, request, send_from_directory

from ..config import Config

bp = Blueprint("alarms", __name__, url_prefix="/api/alarms")


@bp.get("")
def list_alarms():
    """告警列表查询
    ---
    tags: [Alarm]
    parameters:
      - {name: status, in: query, type: string, enum: [pending, notified, confirmed, escalated]}
    responses:
      200: {description: 告警列表}
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
    tags: [Alarm]
    responses:
      200: {description: 已确认}
    """
    from ..services.dingtalk import get_notifier

    confirmed = get_notifier().confirm(alarm_id)
    if not confirmed:
        return jsonify(code=404, message="alarm not found", data={"id": alarm_id}), 404
    return jsonify(code=0, message="ok", data={"id": alarm_id, "status": "confirmed"})


@bp.get("/snapshots/<path:filename>")
def get_snapshot(filename: str):
    """访问告警抓拍图。"""
    return send_from_directory(os.path.abspath(Config.SNAPSHOT_DIR), filename)


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
