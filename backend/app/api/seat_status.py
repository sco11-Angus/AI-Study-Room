"""自习状态宣告接口 — 激活/挂起疲劳算法 (§4, §9)。"""
from flask import Blueprint, request

from ..stream.scheduler import get_scheduler
from .response import err, ok

bp = Blueprint("seat_status", __name__, url_prefix="/api/seat-status")

_VALID_STATUSES = {"idle", "studying", "resting"}
SessionLocal = None


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
    user_id = payload.get("user_id")
    region_id = payload.get("region_id")
    status = payload.get("status")

    if user_id is None or region_id is None or status is None:
        return err("user_id, region_id and status are required"), 400
    if status not in _VALID_STATUSES:
        return err("status must be one of idle/studying/resting"), 400

    try:
        user_id = int(user_id)
        region_id = int(region_id)
    except (TypeError, ValueError):
        return err("user_id and region_id must be integers"), 400

    Region, SeatStatus = _models()
    session = _session()
    try:
        region = session.get(Region, region_id)
        if region is None:
            return err("region not found", code=404, data={"region_id": region_id}), 404
        if region.type and region.type != "seat":
            return err("region must be a seat to switch study status"), 400

        row = (
            session.query(SeatStatus)
            .filter(SeatStatus.user_id == user_id, SeatStatus.region_id == region_id)
            .first()
        )
        if row is None:
            row = SeatStatus(user_id=user_id, region_id=region_id, status=status)
            session.add(row)
        else:
            row.status = status
        session.commit()
        data = {
            "id": row.id,
            "user_id": row.user_id,
            "region_id": row.region_id,
            "status": row.status,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    _notify_fatigue_plugin(region_id=region_id, status=status, user_id=user_id)
    return ok(data)


def _notify_fatigue_plugin(region_id: int, status: str, user_id: int) -> None:
    """Notify the live inference engine when one is running."""
    scheduler = get_scheduler()
    engine = getattr(scheduler, "engine", None) if scheduler else None
    if engine is None:
        return

    engine.on_config_changed(
        "fatigue",
        {"region_id": region_id, "status": status, "user_id": user_id},
    )
    engine.on_config_changed(
        "intrusion",
        {"region_id": region_id, "status": status, "user_id": user_id},
    )
    engine.set_enabled("fatigue", _has_active_studying_region())


def _has_active_studying_region() -> bool:
    _, SeatStatus = _models()
    session = _session()
    try:
        return session.query(SeatStatus).filter(SeatStatus.status == "studying").first() is not None
    finally:
        session.close()


def _session():
    global SessionLocal
    if SessionLocal is None:
        from ..models.database import SessionLocal as factory
        SessionLocal = factory
    return SessionLocal()


def _models():
    from ..models.entities import Region, SeatStatus

    return Region, SeatStatus
