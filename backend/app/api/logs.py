"""告警日志查询 API — 直接读数据库 alarm_event 表（含截图/回放）。"""
import json
import os
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from ..config import Config

bp = Blueprint("logs", __name__, url_prefix="/api/logs")


def _serialize_log(record) -> dict:
    """把 AlarmEvent 记录序列化为日志页需要的结构。"""
    extra = {}
    if record.extra:
        try:
            extra = json.loads(record.extra)
        except (json.JSONDecodeError, TypeError):
            extra = {}
    return {
        "id": record.id,
        "timestamp": record.created_at.strftime("%Y-%m-%d %H:%M:%S") if record.created_at else "",
        "type": record.type,
        "level": record.level,
        "region": record.region_id,
        "camera": record.camera_id,
        "face_match": record.face_match or "",
        "message": record.message or "",
        "actor": extra.get("actor", ""),
        "behavior": extra.get("behavior", ""),
        "snapshot_url": record.snapshot_url or "",
        "clip_url": record.clip_url or "",
        "status": record.status,
        "extra": extra,
    }




@bp.get("/")
def list_logs_trailing_slash():
    return list_logs()


@bp.get("")
def list_logs():
    """获取告警日志列表。
    ---
    tags:
      - Log
    summary: 获取告警日志列表
    description: 获取所有告警日志文件列表，支持按日期筛选。
    parameters:
      - name: date
        in: query
        type: string
        format: date
        required: false
        description: 日期筛选，格式 YYYY-MM-DD
      - name: type
        in: query
        type: string
        required: false
        description: 告警类型筛选
      - name: level
        in: query
        type: integer
        required: false
        description: 告警级别筛选
      - name: page
        in: query
        type: integer
        default: 1
        description: 页码
      - name: limit
        in: query
        type: integer
        default: 50
        description: 每页数量
    responses:
      200:
        description: 日志列表
    """
    date_str = request.args.get("date")
    alarm_type = request.args.get("type")
    level = request.args.get("level")
    camera_id = request.args.get("camera_id")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 50))

    from ..models.database import SessionLocal
    from ..models.entities import AlarmEvent

    session = SessionLocal()
    try:
        query = session.query(AlarmEvent)
        if alarm_type:
            query = query.filter(AlarmEvent.type == alarm_type)
        if level is not None and level != "":
            query = query.filter(AlarmEvent.level == int(level))
        if camera_id not in (None, "", "all"):
            try:
                query = query.filter(AlarmEvent.camera_id == int(camera_id))
            except (TypeError, ValueError):
                pass
        if date_str:
            # 当日 [date, date+1)
            try:
                day = datetime.strptime(date_str, "%Y-%m-%d")
                query = query.filter(
                    AlarmEvent.created_at >= day,
                    AlarmEvent.created_at < day + timedelta(days=1),
                )
            except ValueError:
                pass

        total = query.count()
        records = (
            query.order_by(AlarmEvent.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        entries = [_serialize_log(r) for r in records]
    finally:
        session.close()

    return jsonify({
        "code": 0,
        "message": "ok",
        "data": {
            "entries": entries,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
        },
    })


@bp.get("/files")
def list_log_files():
    """获取日志文件列表。
    ---
    tags:
      - Log
    summary: 获取日志文件列表
    description: 获取所有告警日志文件名。
    responses:
      200:
        description: 文件列表
    """
    # 日志已改为读数据库，不再有独立日志文件；保留端点兼容旧调用。
    files = []
    return jsonify({
        "code": 0,
        "message": "ok",
        "data": files,
    })


@bp.get("/stats")
def get_log_stats():
    """获取日志统计信息。
    ---
    tags:
      - Log
    summary: 获取日志统计信息
    description: 获取告警日志的统计数据，包括总数、按类型统计等。
    parameters:
      - name: date
        in: query
        type: string
        format: date
        required: false
        description: 日期筛选
    responses:
      200:
        description: 统计信息
    """
    date_str = request.args.get("date")

    from ..models.database import SessionLocal
    from ..models.entities import AlarmEvent

    session = SessionLocal()
    try:
        query = session.query(AlarmEvent)
        if date_str:
            try:
                day = datetime.strptime(date_str, "%Y-%m-%d")
                query = query.filter(
                    AlarmEvent.created_at >= day,
                    AlarmEvent.created_at < day + timedelta(days=1),
                )
            except ValueError:
                pass
        records = query.all()
    finally:
        session.close()

    total_count = len(records)
    type_stats = {}
    level_stats = {}
    for r in records:
        type_stats[r.type] = type_stats.get(r.type, 0) + 1
        level_stats[r.level] = level_stats.get(r.level, 0) + 1

    return jsonify({
        "code": 0,
        "message": "ok",
        "data": {
            "total_count": total_count,
            "type_stats": type_stats,
            "level_stats": level_stats,
        },
    })


def _remove_media_file(url: str, base_dir: str) -> None:
    """按 /api/alarms/{snapshots|clips}/<file> URL 删除对应磁盘文件。"""
    if not url:
        return
    filename = os.path.basename(url.split("?")[0])
    if not filename:
        return
    path = os.path.join(os.path.abspath(base_dir), filename)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass  # 文件删不掉不阻塞记录删除


@bp.delete("/<int:alarm_id>")
def delete_log(alarm_id: int):
    """删除一条告警日志：同时删除数据库记录 + 截图/回放文件。
    ---
    tags:
      - Log
    summary: 删除告警日志（含数据库记录与媒体文件）
    parameters:
      - name: alarm_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: 删除成功
      404:
        description: 告警不存在
    """
    from ..models.database import SessionLocal
    from ..models.entities import AlarmEvent

    session = SessionLocal()
    try:
        record = session.query(AlarmEvent).filter(AlarmEvent.id == alarm_id).first()
        if record is None:
            return jsonify({"code": 404, "message": "告警不存在", "data": {"id": alarm_id}}), 404
        snapshot_url = record.snapshot_url
        clip_url = record.clip_url
        session.delete(record)
        session.commit()
    finally:
        session.close()

    # 记录删除后再清理磁盘媒体文件
    _remove_media_file(snapshot_url, Config.SNAPSHOT_DIR)
    _remove_media_file(clip_url, Config.CLIP_DIR)

    return jsonify({"code": 0, "message": "ok", "data": {"id": alarm_id}})
