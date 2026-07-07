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
    Swagger(app, template={"info": {"title": "智慧自习室 AI 管家 API", "version": "1.0.0"}})

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

    return app
