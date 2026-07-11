"""Region CRUD APIs used by the frontend drawing tool."""
import json

from flask import Blueprint, jsonify, request

from ..models.database import SessionLocal
from ..models.entities import Region
from ..stream.scheduler import get_scheduler

bp = Blueprint("regions", __name__, url_prefix="/api/regions")

REGION_TYPES = {"danger_zone", "seat"}


def _serialize_region(region: Region) -> dict:
    return {
        "id": region.id,
        "camera_id": region.camera_id,
        "user_id": region.user_id,
        "name": region.name,
        "type": region.type,
        "polygon": json.loads(region.polygon or "[]"),
        "x_distance": region.x_distance,
        "y_stay_time": region.y_stay_time,
    }


def _validate_payload(payload: dict, partial: bool = False) -> tuple[dict, str | None]:
    data: dict = {}

    if not partial or "camera_id" in payload:
        try:
            data["camera_id"] = int(payload.get("camera_id"))
        except (TypeError, ValueError):
            return {}, "camera_id must be an integer"

    if "user_id" in payload:
        user_id = payload.get("user_id")
        data["user_id"] = None if user_id in (None, "") else int(user_id)

    if not partial or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return {}, "name is required"
        data["name"] = name

    if not partial or "type" in payload:
        region_type = str(payload.get("type") or "").strip()
        if region_type not in REGION_TYPES:
            return {}, "type must be one of: danger_zone, seat"
        data["type"] = region_type

    if not partial or "polygon" in payload:
        polygon = payload.get("polygon")
        if not isinstance(polygon, list) or len(polygon) < 3:
            return {}, "polygon must contain at least 3 points"
        # 前端以归一化坐标 [0,1] 提交，保留 float，不截断为整数
        normalized = []
        for point in polygon:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                return {}, "polygon point must be [x, y]"
            try:
                normalized.append([float(point[0]), float(point[1])])
            except (TypeError, ValueError):
                return {}, "polygon coordinates must be numbers"
        data["polygon"] = json.dumps(normalized)

    if not partial or "x_distance" in payload:
        try:
            x_distance = int(payload.get("x_distance", 0))
        except (TypeError, ValueError):
            return {}, "x_distance must be an integer"
        if x_distance < 0:
            return {}, "x_distance must be >= 0"
        data["x_distance"] = x_distance

    if not partial or "y_stay_time" in payload:
        try:
            y_stay_time = int(payload.get("y_stay_time", 0))
        except (TypeError, ValueError):
            return {}, "y_stay_time must be an integer"
        if y_stay_time < 0:
            return {}, "y_stay_time must be >= 0"
        data["y_stay_time"] = y_stay_time

    return data, None


def _notify_intrusion_changed() -> None:
    scheduler = get_scheduler()
    if scheduler is not None:
        scheduler.engine.on_config_changed("intrusion", {})


@bp.get("")
def list_regions():
    camera_id = request.args.get("camera_id", type=int)
    session = SessionLocal()
    try:
        query = session.query(Region)
        if camera_id is not None:
            query = query.filter(Region.camera_id == camera_id)
        rows = query.order_by(Region.id.asc()).all()
        return jsonify(code=0, message="success", data=[_serialize_region(r) for r in rows])
    finally:
        session.close()


@bp.post("")
def create_region():
    payload = request.get_json(force=True) or {}
    data, error = _validate_payload(payload)
    if error:
        return jsonify(code=1, message=error, data=None), 400

    session = SessionLocal()
    try:
        region = Region(**data)
        session.add(region)
        session.commit()
        session.refresh(region)
        result = _serialize_region(region)
        _notify_intrusion_changed()
        return jsonify(code=0, message="success", data=result)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@bp.put("/<int:region_id>")
def update_region(region_id: int):
    payload = request.get_json(force=True) or {}
    data, error = _validate_payload(payload, partial=True)
    if error:
        return jsonify(code=1, message=error, data=None), 400

    session = SessionLocal()
    try:
        region = session.get(Region, region_id)
        if region is None:
            return jsonify(code=404, message="region not found", data={"id": region_id}), 404
        for key, value in data.items():
            setattr(region, key, value)
        session.commit()
        session.refresh(region)
        result = _serialize_region(region)
        _notify_intrusion_changed()
        return jsonify(code=0, message="success", data=result)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@bp.delete("/<int:region_id>")
def delete_region(region_id: int):
    session = SessionLocal()
    try:
        region = session.get(Region, region_id)
        if region is None:
            return jsonify(code=404, message="region not found", data={"id": region_id}), 404
        session.delete(region)
        session.commit()
        _notify_intrusion_changed()
        return jsonify(code=0, message="success", data={"id": region_id})
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
