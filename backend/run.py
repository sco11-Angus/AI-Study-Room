"""后端启动入口 (§11)。生产部署使用 gunicorn。"""
from app import create_app
from app.stream.engine import InferenceEngine
from app.stream.scheduler import StreamScheduler, set_scheduler

app = create_app()

# ---- 启动拉流调度器（WebSocket 视频流依赖）----
engine = InferenceEngine()
scheduler = StreamScheduler(engine)
scheduler.add_camera(camera_id=0, stream_name="test")
scheduler.start_all()
set_scheduler(scheduler)

if __name__ == "__main__":
    # Swagger 文档: http://localhost:5000/apidocs
    app.run(host="0.0.0.0", port=5000, debug=True)
