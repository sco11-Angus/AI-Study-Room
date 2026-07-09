"""Flask 应用工厂 — 集成 Swagger/OpenAPI 文档 + WebSocket (§9, §10.3)。"""
from flask import Flask, jsonify
from flask_cors import CORS
from flask_sock import Sock
from flasgger import Swagger

from .config import Config

sock = Sock()


def create_app(config: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    # CORS 白名单（前端 5173）
    CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"])
    
    sock.init_app(app)
    Swagger(app, template={
        "info": {
            "title": "智慧自习室 AI 管家 API",
            "version": "1.0.0",
            "description": "智能自习室管理系统后端接口文档，包含摄像头管理、防区配置、告警查询、人脸识别等模块。",
        },
        "tags": [
            {"name": "Camera", "description": "摄像头注册、查询与流管理"},
            {"name": "Region", "description": "防区/座位区域配置（多边形绘制、安全距离、停留时间）"},
            {"name": "SeatStatus", "description": "自习状态切换（自习/休息），控制疲劳检测启停"},
            {"name": "Alarm", "description": "告警记录查询与钉钉确认回调"},
            {"name": "Face", "description": "人脸识别与活体检测结果查询"},
            {"name": "FireSmoke", "description": "烟火检测接入说明：模型由推理引擎调度，告警以 type=fire_smoke 进入告警中心"},
            {"name": "Stream", "description": "视频帧与实时告警 WebSocket 通道"},
        ],
        "definitions": {
            "ApiResponse": {
                "type": "object",
                "properties": {
                    "code": {"type": "integer", "example": 0},
                    "message": {"type": "string", "example": "success"},
                    "data": {"type": "object"},
                },
            },
            "Camera": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 0},
                    "name": {"type": "string", "example": "自习室主摄像头"},
                    "stream_url": {"type": "string", "example": "rtmp://host/live/test"},
                    "resolution": {"type": "string", "example": "1920x1080"},
                    "status": {"type": "string", "enum": ["online", "offline"], "example": "online"},
                },
            },
            "Region": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 1},
                    "camera_id": {"type": "integer", "example": 0},
                    "user_id": {"type": "integer", "example": 1},
                    "name": {"type": "string", "example": "烟火检测区域A"},
                    "type": {"type": "string", "enum": ["danger_zone", "seat"], "example": "danger_zone"},
                    "polygon": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "integer"}},
                        "example": [[100, 100], [600, 100], [600, 500], [100, 500]],
                    },
                    "x_distance": {"type": "integer", "example": 50},
                    "y_stay_time": {"type": "integer", "example": 10},
                },
            },
            "AlarmEvent": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 12},
                    "region_id": {"type": "integer", "example": 1},
                    "camera_id": {"type": "integer", "example": 0},
                    "type": {
                        "type": "string",
                        "enum": ["intrusion", "fire_smoke", "occupy", "fatigue", "fight"],
                        "example": "fire_smoke",
                    },
                    "snapshot_url": {"type": "string", "example": "/api/alarms/snapshots/fire_smoke_1.jpg"},
                    "face_match": {"type": "string", "example": "stranger"},
                    "level": {"type": "integer", "example": 1},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "notified", "confirmed", "escalated"],
                        "example": "pending",
                    },
                    "extra": {"$ref": "#/definitions/FireSmokeAlarmExtra"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "confirmed_at": {"type": "string", "format": "date-time"},
                },
            },
            "FireSmokeAlarmExtra": {
                "type": "object",
                "properties": {
                    "detected_class": {"type": "string", "enum": ["fire", "smoke"], "example": "smoke"},
                    "fire_smoke_conf": {"type": "number", "format": "float", "example": 0.83},
                    "avg_conf": {"type": "number", "format": "float", "example": 0.57},
                    "window": {"type": "integer", "example": 30},
                    "threshold": {"type": "number", "format": "float", "example": 0.45},
                    "frame_idx": {"type": "integer", "example": 120},
                },
            },
            "FaceResult": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["member", "stranger", "face_spoof"]},
                    "member_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "paths": {
            "/ws/alarms": {
                "get": {
                    "tags": ["Stream", "Alarm", "FireSmoke"],
                    "summary": "告警 WebSocket 订阅",
                    "description": "前端看板通过该 WebSocket 接收所有告警事件；烟火检测命中后会推送 type=fire_smoke 的 AlarmEvent JSON。",
                    "responses": {"101": {"description": "Switching Protocols"}},
                }
            },
            "/ws/video_feed/{camera_id}": {
                "get": {
                    "tags": ["Stream", "Camera", "FireSmoke"],
                    "summary": "视频帧 WebSocket 订阅",
                    "description": "按 camera_id 订阅 StreamScheduler 复用解码后的 JPEG 帧；烟火检测和前端预览共享同一路摄像头。",
                    "parameters": [
                        {"name": "camera_id", "in": "path", "type": "integer", "required": True}
                    ],
                    "responses": {"101": {"description": "Switching Protocols"}},
                }
            },
            "/ws/face_recognition": {
                "get": {
                    "tags": ["Stream", "Face"],
                    "summary": "人脸识别结果 WebSocket 订阅",
                    "responses": {"101": {"description": "Switching Protocols"}},
                }
            },
        },
    })

    # 初始化数据库表
    from .models.database import init_db
    init_db()

    # 注册各 API 蓝图 (§9.1)
    from .api import cameras, regions, seat_status, alarms, ws, video_feed
    app.register_blueprint(cameras.bp)
    app.register_blueprint(regions.bp)
    app.register_blueprint(seat_status.bp)
    app.register_blueprint(alarms.bp)
    app.register_blueprint(ws.bp)

    # WebSocket 路由通过 sock.route 注册（非 blueprint）
    ws.register_ws_routes(sock)
    video_feed.register_ws_routes(sock)

    # 全局异常处理器
    @app.errorhandler(Exception)
    def handle_exception(e):
        """未捕获异常统一返回 {code:500,...}，不泄漏堆栈。"""
        return jsonify({
            "code": 500,
            "message": "Internal Server Error",
            "data": None
        }), 500

    return app
