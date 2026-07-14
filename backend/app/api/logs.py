"""日志查询API — 提供告警日志的查看和筛选功能。"""
import json
import os
import re
from datetime import datetime

from flask import Blueprint, jsonify, request

from ..config import Config

bp = Blueprint("logs", __name__, url_prefix="/api/logs")


def _parse_log_line(line: str) -> dict | None:
    """解析告警日志行。"""
    pattern = (
        r"\[(?P<timestamp>[^\]]+)\]\s+"
        r"(?P<event_type>[A-Z_]+)\s+"
        r"id=(?P<id>\d+)\s+"
        r"type=(?P<type>[^\s]+)\s+"
        r"level=(?P<level>\d+)\s+"
        r"region=(?P<region>\d+)\s+"
        r"camera=(?P<camera>\d+)\s+"
        r"face_match=(?P<face_match>[^\s]+)\s+"
        r"actor=(?P<actor>[^\s]+)\s+"
        r"behavior=(?P<behavior>[^\s]+)\s+"
        r"message=(?P<message>[^s]+?)\s+"
        r"snapshot_url=(?P<snapshot_url>[^\s]+)\s+"
        r"extra=(?P<extra>.+)"
    )
    match = re.match(pattern, line)
    if not match:
        try:
            parts = line.split(" ", 6)
            if len(parts) >= 3:
                return {
                    "timestamp": parts[0][1:-1],
                    "event_type": parts[1],
                    "raw": line,
                }
        except Exception:
            pass
        return None

    groups = match.groupdict()
    extra = {}
    if groups.get("extra"):
        try:
            extra = json.loads(groups["extra"])
        except json.JSONDecodeError:
            extra = {"raw": groups["extra"]}

    return {
        "timestamp": groups.get("timestamp", ""),
        "event_type": groups.get("event_type", ""),
        "id": int(groups.get("id", 0)),
        "type": groups.get("type", ""),
        "level": int(groups.get("level", 0)),
        "region": int(groups.get("region", 0)),
        "camera": int(groups.get("camera", 0)),
        "face_match": groups.get("face_match", ""),
        "actor": groups.get("actor", ""),
        "behavior": groups.get("behavior", ""),
        "message": groups.get("message", ""),
        "snapshot_url": groups.get("snapshot_url", ""),
        "extra": extra,
    }


def _get_log_directory() -> str:
    """获取日志目录路径。"""
    return os.path.join(os.path.dirname(__file__), "..", "..", "logs")


def _get_log_files() -> list[str]:
    """获取所有日志文件列表。"""
    log_dir = _get_log_directory()
    if not os.path.exists(log_dir):
        return []
    files = []
    for f in os.listdir(log_dir):
        if f.startswith("alarm_") and f.endswith(".log"):
            files.append(f)
    return sorted(files, reverse=True)


@bp.get("/")
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
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 50))

    log_dir = _get_log_directory()
    log_files = _get_log_files()

    if date_str:
        log_files = [f for f in log_files if f == f"alarm_{date_str}.log"]

    all_entries = []
    for filename in log_files:
        filepath = os.path.join(log_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = _parse_log_line(line)
                    if entry:
                        entry["file"] = filename
                        all_entries.append(entry)
        except Exception:
            continue

    if alarm_type:
        all_entries = [e for e in all_entries if e.get("type") == alarm_type]
    if level is not None:
        all_entries = [e for e in all_entries if e.get("level") == int(level)]

    all_entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    start = (page - 1) * limit
    end = start + limit
    total = len(all_entries)
    paginated = all_entries[start:end]

    return jsonify({
        "code": 0,
        "message": "ok",
        "data": {
            "entries": paginated,
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
    files = _get_log_files()
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

    log_dir = _get_log_directory()
    log_files = _get_log_files()

    if date_str:
        log_files = [f for f in log_files if f == f"alarm_{date_str}.log"]

    total_count = 0
    type_stats = {}
    level_stats = {}

    for filename in log_files:
        filepath = os.path.join(log_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = _parse_log_line(line)
                    if entry:
                        total_count += 1
                        alarm_type = entry.get("type", "unknown")
                        type_stats[alarm_type] = type_stats.get(alarm_type, 0) + 1
                        level = entry.get("level", 0)
                        level_stats[level] = level_stats.get(level, 0) + 1
        except Exception:
            continue

    return jsonify({
        "code": 0,
        "message": "ok",
        "data": {
            "total_count": total_count,
            "type_stats": type_stats,
            "level_stats": level_stats,
            "date_range": {
                "earliest": log_files[-1].replace("alarm_", "").replace(".log", "") if log_files else None,
                "latest": log_files[0].replace("alarm_", "").replace(".log", "") if log_files else None,
            },
        },
    })
