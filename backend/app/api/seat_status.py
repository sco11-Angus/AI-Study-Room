"""Study-session APIs that control fatigue eligibility for one seat."""
import json

from flask import Blueprint, request

from ..config import Config
from ..stream.scheduler import get_scheduler
from .response import err, ok

bp = Blueprint("seat_status", __name__, url_prefix="/api/seat-status")

_VALID_STATUSES = {"idle", "studying", "resting"}
_VALID_MODES = {"demo", "verified"}
SessionLocal = None


@bp.get("/companion")
def companion_status():
    """Return the selected user's current companion session and reminder."""
    user_id = request.args.get("user_id", type=int)
    region_id = request.args.get("region_id", type=int)
    if user_id is None or region_id is None:
        return err("user_id and region_id are required"), 400

    Region, SeatStatus, SeatReservation, Member = _models()
    from ..models.entities import AlarmEvent

    session = _session()
    try:
        row = (
            session.query(SeatStatus)
            .filter(SeatStatus.user_id == user_id, SeatStatus.region_id == region_id)
            .order_by(SeatStatus.updated_at.desc(), SeatStatus.id.desc())
            .first()
        )
        region = session.get(Region, region_id)
        reservation_row = (
            session.query(SeatReservation, Member)
            .join(Member, SeatReservation.member_id == Member.member_id)
            .filter(SeatReservation.region_id == region_id, SeatReservation.enabled.is_(True))
            .first()
        )
        latest = _latest_fatigue_for_session(session, AlarmEvent, region_id, user_id)
        runtime = _fatigue_runtime_state(region_id)
        return ok({
            "user_id": user_id,
            "region_id": region_id,
            "camera_id": region.camera_id if region else None,
            "status": row.status if row else "idle",
            "mode": (row.mode if row and row.mode else "demo"),
            "member_id": row.member_id if row else None,
            "reservation": _serialize_reservation(reservation_row),
            "runtime": runtime,
            "stream_online": _stream_online(region.camera_id if region else None),
            "dingtalk_configured": bool(Config.DINGTALK_WEBHOOK),
            "latest_fatigue": latest,
        })
    finally:
        session.close()


@bp.post("")
def switch_status():
    """Start, pause, or end one explicit demo/verified study session."""
    payload = request.get_json(force=True) or {}
    user_id = payload.get("user_id")
    region_id = payload.get("region_id")
    status = payload.get("status")
    mode = payload.get("mode", "demo")
    member_id = payload.get("member_id")

    if user_id is None or region_id is None or status is None:
        return err("user_id, region_id and status are required"), 400
    if status not in _VALID_STATUSES:
        return err("status must be one of idle/studying/resting"), 400
    if mode not in _VALID_MODES:
        return err("mode must be one of demo/verified"), 400
    try:
        user_id = int(user_id)
        region_id = int(region_id)
        member_id = int(member_id) if member_id is not None else None
    except (TypeError, ValueError):
        return err("user_id, region_id and member_id must be integers"), 400

    Region, SeatStatus, SeatReservation, Member = _models()
    session = _session()
    try:
        region = session.get(Region, region_id)
        if region is None:
            return err("region not found", code=404, data={"region_id": region_id}), 404
        if region.type != "seat":
            return err("region must be a seat to switch study status"), 400

        if status == "studying" and mode == "verified":
            validation_error = _validate_verified_session(
                session, SeatReservation, Member, region_id, member_id,
            )
            if validation_error:
                return err(validation_error), 400

        row = (
            session.query(SeatStatus)
            .filter(SeatStatus.user_id == user_id, SeatStatus.region_id == region_id)
            .order_by(SeatStatus.updated_at.desc(), SeatStatus.id.desc())
            .first()
        )
        if row is None:
            row = SeatStatus(user_id=user_id, region_id=region_id)
            session.add(row)

        # The table retains simple state history, but exactly one session for a
        # seat may actively study at a time.
        if status == "studying":
            session.query(SeatStatus).filter(
                SeatStatus.region_id == region_id,
                SeatStatus.status == "studying",
                SeatStatus.id != row.id,
            ).update({SeatStatus.status: "idle"}, synchronize_session=False)

        row.status = status
        row.mode = mode
        row.member_id = member_id if mode == "verified" else None
        session.commit()
        session.refresh(row)
        data = _serialize_session(row, region)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    _notify_fatigue_plugin(data)
    return ok(data)


def _validate_verified_session(session, SeatReservation, Member, region_id: int, member_id: int | None) -> str | None:
    if member_id is None:
        return "verified mode requires member_id"
    reservation = (
        session.query(SeatReservation)
        .filter(SeatReservation.region_id == region_id, SeatReservation.enabled.is_(True))
        .first()
    )
    if reservation is None:
        return "verified mode requires an enabled seat reservation"
    if reservation.member_id != member_id:
        return "verified member_id must match the seat reservation"
    member = session.get(Member, member_id)
    if member is None or not (member.feature or "").strip():
        return "verified member must have a face feature"
    return None


def _latest_fatigue_for_session(session, AlarmEvent, region_id: int, user_id: int):
    alarms = (
        session.query(AlarmEvent)
        .filter(AlarmEvent.type == "fatigue", AlarmEvent.region_id == region_id)
        .order_by(AlarmEvent.created_at.desc())
        .limit(20)
        .all()
    )
    for alarm in alarms:
        extra = _parse_extra(alarm.extra)
        if extra.get("user_id") != user_id:
            continue
        return {
            "id": alarm.id,
            "type": alarm.type,
            "level": alarm.level,
            "status": alarm.status,
            "extra": extra,
            "created_at": alarm.created_at.isoformat() if alarm.created_at else None,
        }
    return None


def _serialize_reservation(row):
    if not row:
        return None
    reservation, member = row
    return {
        "member_id": reservation.member_id,
        "member_name": member.name or f"member-{reservation.member_id}",
        "enabled": bool(reservation.enabled),
    }


def _serialize_session(row, region):
    return {
        "id": row.id,
        "user_id": row.user_id,
        "region_id": row.region_id,
        "camera_id": region.camera_id,
        "status": row.status,
        "mode": row.mode or "demo",
        "member_id": row.member_id,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _parse_extra(value):
    try:
        return json.loads(value) if value else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _notify_fatigue_plugin(session_data: dict) -> None:
    scheduler = get_scheduler()
    engine = getattr(scheduler, "engine", None) if scheduler else None
    if engine is None:
        return
    engine.on_config_changed("fatigue", session_data)
    engine.set_enabled("fatigue", _has_active_studying_region())


def _fatigue_runtime_state(region_id: int) -> dict:
    scheduler = get_scheduler()
    engine = getattr(scheduler, "engine", None) if scheduler else None
    detector = getattr(engine, "_detectors", {}).get("fatigue") if engine else None
    getter = getattr(detector, "get_runtime_state", None)
    return getter(region_id) if callable(getter) else {"eligible": False, "reason": "engine_unavailable"}


def _stream_online(camera_id: int | None) -> bool:
    scheduler = get_scheduler()
    if scheduler is None or camera_id is None:
        return False
    return bool(scheduler.status().get(camera_id, False))


def _has_active_studying_region() -> bool:
    _, SeatStatus, _, _ = _models()
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
    from ..models.entities import Member, Region, SeatReservation, SeatStatus

    return Region, SeatStatus, SeatReservation, Member
