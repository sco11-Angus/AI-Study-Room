"""Long-lived seat reservation bindings for identity intrusion detection."""
from flask import Blueprint, request

from ..models.database import SessionLocal
from ..models.entities import Member, Region, SeatReservation
from ..stream.scheduler import get_scheduler
from .response import err, ok

bp = Blueprint("seat_reservations", __name__, url_prefix="/api/seat-reservations")


def _serialize(row: SeatReservation, member: Member | None = None) -> dict:
    return {
        "id": row.id,
        "region_id": row.region_id,
        "member_id": row.member_id,
        "member_name": (member.name if member else None) or f"member-{row.member_id}",
        "enabled": bool(row.enabled),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _notify_intrusion_changed() -> None:
    scheduler = get_scheduler()
    engine = getattr(scheduler, "engine", None) if scheduler else None
    if engine is not None:
        engine.on_config_changed("intrusion", {})


@bp.get("")
def list_reservations():
    camera_id = request.args.get("camera_id", type=int)
    session = SessionLocal()
    try:
        query = session.query(SeatReservation, Member, Region).join(
            Member, SeatReservation.member_id == Member.member_id
        ).join(Region, SeatReservation.region_id == Region.id)
        if camera_id is not None:
            query = query.filter(Region.camera_id == camera_id)
        rows = query.order_by(SeatReservation.region_id.asc()).all()
        return ok([_serialize(reservation, member) for reservation, member, _region in rows])
    finally:
        session.close()


@bp.put("/<int:region_id>")
def upsert_reservation(region_id: int):
    payload = request.get_json(force=True) or {}
    try:
        member_id = int(payload.get("member_id"))
    except (TypeError, ValueError):
        return err("member_id must be an integer"), 400

    session = SessionLocal()
    try:
        region = session.get(Region, region_id)
        if region is None:
            return err("region not found", code=404, data={"region_id": region_id}), 404
        if region.type != "seat":
            return err("reservation can only bind a seat region"), 400

        member = session.get(Member, member_id)
        if member is None:
            return err("member not found", code=404, data={"member_id": member_id}), 404
        if not member.feature or not member.feature.strip():
            return err("reservation member must have a face feature"), 400

        row = session.query(SeatReservation).filter_by(region_id=region_id).first()
        if row is None:
            row = SeatReservation(region_id=region_id, member_id=member_id, enabled=True)
            session.add(row)
        else:
            row.member_id = member_id
            row.enabled = True
        session.commit()
        session.refresh(row)
        result = _serialize(row, member)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    _notify_intrusion_changed()
    return ok(result)


@bp.delete("/<int:region_id>")
def delete_reservation(region_id: int):
    session = SessionLocal()
    try:
        row = session.query(SeatReservation).filter_by(region_id=region_id).first()
        if row is None:
            return err("reservation not found", code=404, data={"region_id": region_id}), 404
        session.delete(row)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    _notify_intrusion_changed()
    return ok({"region_id": region_id})
