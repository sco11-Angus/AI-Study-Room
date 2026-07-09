"""后端启动入口 (§11)。生产部署使用 gunicorn。"""
import logging
import sys

from app import create_app
from app.detectors.face import FaceDetector
from app.detectors.fatigue import FatiguePlugin
from app.stream.engine import InferenceEngine
from app.stream.scheduler import StreamScheduler, set_scheduler

# 确保 INFO 级别日志能输出
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s:%(name)s: %(message)s")

app = create_app()

# ---- 启动拉流调度器（WebSocket 视频流依赖）----
print("[run] ===== 启动推理引擎 =====", flush=True)
engine = InferenceEngine()
engine.register(FaceDetector(skip_frames=10, cooldown=1.0))
engine.register(FatiguePlugin())
engine.setup_all()
print(f"[run] 已注册检测器: {engine.detectors}", flush=True)

scheduler = StreamScheduler(engine)
scheduler.add_camera(camera_id=0, stream_name="test")
scheduler.start_all()
set_scheduler(scheduler)

if __name__ == "__main__":
    # Swagger 文档: http://localhost:5000/apidocs
    app.run(host="0.0.0.0", port=5000, debug=True)
