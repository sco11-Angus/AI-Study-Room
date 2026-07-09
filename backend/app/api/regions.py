"""防区/座位接口 — 前端画区参数持久化 (§5.1, §5.2, §9)。"""
import json

from flask import Blueprint, request
from .response import ok, err

from ..models.database import SessionLocal
from ..models.entities import Region

bp = Blueprint("regions", __name__, url_prefix="/api/regions")


@bp.get("")
def list_regions():
    """查询某摄像头下防区
    ---
    tags: [Region]
    parameters:
      - {name: camera_id, in: query, type: integer, required: true}
    responses:
      200:
        description: 防区列表
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: success}
            data: {type: array, items: {$ref: '#/definitions/Region'}}
    """
    camera_id = request.args.get("camera_id", type=int)
    if camera_id is None:
        return err("camera_id is required", code=1)

    session = SessionLocal()
    try:
        regions = session.query(Region).filter(Region.camera_id == camera_id).all()
        data = []
        for region in regions:
            polygon = []
            try:
                polygon = json.loads(region.polygon) if region.polygon else []
            except Exception:
                polygon = []

            data.append(
                {
                    "id": region.id,
                    "camera_id": region.camera_id,
                    "name": region.name,
                    "type": region.type,
                    "polygon": polygon,
                    "x_distance": region.x_distance,
                    "y_stay_time": region.y_stay_time,
                }
            )
        return ok(data)
    finally:
        session.close()


@bp.post("")
def create_region():
    """创建防区 (polygon + x_distance + y_stay_time)
    ---
    tags: [Region]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [camera_id, name, type, polygon]
          properties:
            camera_id: {type: integer}
            name: {type: string}
            type: {type: string, enum: [danger_zone, seat]}
            polygon: {type: array, items: {type: array, items: {type: number}}}
            x_distance: {type: integer, description: 安全距离阈值(像素), default: 50}
            y_stay_time: {type: integer, description: 允许停留时间(秒), default: 10}
    responses:
      200:
        description: 创建成功
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: success}
            data: {$ref: '#/definitions/Region'}
    """
    payload = request.get_json(force=True)
    if not payload:
        return err("invalid payload", code=1)

    camera_id = payload.get("camera_id")
    name = payload.get("name")
    region_type = payload.get("type")
    polygon = payload.get("polygon")

    if camera_id is None or not name or not region_type or not polygon:
        return err("camera_id, name, type, and polygon are required", code=1)
    if not isinstance(polygon, list) or len(polygon) < 3:
        return err("polygon must be an array with at least 3 points", code=1)

    session = SessionLocal()
    try:
        region = Region(
            camera_id=camera_id,
            name=name,
            type=region_type,
            polygon=json.dumps(polygon, ensure_ascii=False),
            x_distance=payload.get("x_distance", 50),
            y_stay_time=payload.get("y_stay_time", 10),
        )
        session.add(region)
        session.commit()
        session.refresh(region)
        return ok(
            {
                "id": region.id,
                "camera_id": region.camera_id,
                "name": region.name,
                "type": region.type,
                "polygon": polygon,
                "x_distance": region.x_distance,
                "y_stay_time": region.y_stay_time,
            }
        )
    finally:
        session.close()


@bp.put("/<int:region_id>")
def update_region(region_id: int):
    """更新防区参数
    ---
    tags: [Region]
    parameters:
      - {name: region_id, in: path, type: integer, required: true}
      - in: body
        name: body
        schema:
          type: object
          properties:
            name: {type: string}
            polygon: {type: array}
            x_distance: {type: integer}
            y_stay_time: {type: integer}
    responses:
      200:
        description: 更新成功
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: success}
            data: {$ref: '#/definitions/Region'}
    """
    payload = request.get_json(force=True)
    if not payload:
        return err("invalid payload", code=1)

    session = SessionLocal()
    try:
        region = session.get(Region, region_id)
        if region is None:
            return err("region not found", code=1)

        if "name" in payload:
            region.name = payload["name"]
        if "polygon" in payload:
            polygon = payload["polygon"]
            if not isinstance(polygon, list) or len(polygon) < 3:
                return err("polygon must be an array with at least 3 points", code=1)
            region.polygon = json.dumps(polygon, ensure_ascii=False)
        if "x_distance" in payload:
            region.x_distance = payload["x_distance"]
        if "y_stay_time" in payload:
            region.y_stay_time = payload["y_stay_time"]
        if "type" in payload:
            region.type = payload["type"]

        session.commit()
        return ok(
            {
                "id": region.id,
                "camera_id": region.camera_id,
                "name": region.name,
                "type": region.type,
                "polygon": json.loads(region.polygon) if region.polygon else [],
                "x_distance": region.x_distance,
                "y_stay_time": region.y_stay_time,
            }
        )
    finally:
        session.close()


@bp.delete("/<int:region_id>")
def delete_region(region_id: int):
    """删除防区
    ---
    tags: [Region]
    parameters:
      - {name: region_id, in: path, type: integer, required: true}
    responses:
      200:
        description: 删除成功
        schema:
          type: object
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: success}
            data: {type: object}
    """
    session = SessionLocal()
    try:
        region = session.get(Region, region_id)
        if region is None:
            return err("region not found", code=1)
        session.delete(region)
        session.commit()
        return ok({"id": region_id})
    finally:
        session.close()
