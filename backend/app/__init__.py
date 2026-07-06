"""Flask 应用工厂 — 集成 Swagger/OpenAPI 文档 (§9, §10.3)。"""
from flask import Flask
from flask_cors import CORS
from flasgger import Swagger

from .config import Config


def create_app(config: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    CORS(app)
    Swagger(app, template={"info": {"title": "智慧自习室 AI 管家 API", "version": "1.0.0"}})

    # 注册各 API 蓝图 (§9.1)
    from .api import cameras, regions, seat_status, alarms, ws, video_feed
    app.register_blueprint(cameras.bp)
    app.register_blueprint(regions.bp)
    app.register_blueprint(seat_status.bp)
    app.register_blueprint(alarms.bp)
    app.register_blueprint(ws.bp)
    app.register_blueprint(video_feed.bp)

    return app
