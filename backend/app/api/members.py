"""Read-only member APIs used by seat reservation configuration."""
from flask import Blueprint, request

from ..models.database import SessionLocal
from ..models.entities import Member
from .response import ok

bp = Blueprint("members", __name__, url_prefix="/api/members")


@bp.get("")
def list_members():
    """List members; face_enrolled=true returns only usable reservation targets."""
    face_enrolled = request.args.get("face_enrolled", "").lower() == "true"
    session = SessionLocal()
    try:
        query = session.query(Member)
        if face_enrolled:
            query = query.filter(Member.feature.isnot(None), Member.feature != "")
        rows = query.order_by(Member.member_id.asc()).all()
        return ok([
            {
                "member_id": row.member_id,
                "name": row.name or f"member-{row.member_id}",
                "face_enrolled": bool(row.feature and row.feature.strip()),
            }
            for row in rows
        ])
    finally:
        session.close()
