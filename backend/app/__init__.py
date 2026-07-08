"""Flask 应用工厂 — 集成 Swagger/OpenAPI 文档 + WebSocket (§9, §10.3)。"""
from flask import Flask
from flask_cors import CORS
from flask_sock import Sock
from flasgger import Swagger

from .config import Config

sock = Sock()


def create_app(config: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    CORS(app)
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
        ],
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
    video_feed.register_ws_routes(sock)
    ws.register_ws_routes(sock)

    return app
