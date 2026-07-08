"""防区/座位接口 — 前端画区参数持久化 (§5.1, §5.2, §9)。"""
from flask import Blueprint, jsonify, request
from .response import ok, err

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
    return ok([])


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
            polygon: {type: array, items: {type: array, items: {type: integer}}}
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
    # TODO: 校验并写入 region 表；polygon 由归一化坐标映射回原始分辨率
    return ok(payload)


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
    return ok({"id": region_id})


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
    return ok({"id": region_id})
