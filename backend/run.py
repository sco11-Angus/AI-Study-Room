"""后端启动入口 (§11)。生产部署使用 gunicorn。"""
import logging
import sys

from app import create_app

# 确保 INFO 级别日志能输出
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s:%(name)s: %(message)s")

app = create_app()


def start_services():
    """启动推理引擎和拉流调度器。"""
    from app.detectors.face import FaceDetector
    from app.detectors.fire_smoke import FireSmokePlugin
    from app.detectors.fight import FightPlugin
    from app.stream.engine import InferenceEngine
    from app.stream.scheduler import StreamScheduler, set_scheduler

    print("[run] ===== 启动推理引擎 =====", flush=True)
    engine = InferenceEngine()
    engine.register(FaceDetector(skip_frames=10, cooldown=1.0))
    engine.register(FireSmokePlugin())
    engine.register(FightPlugin())
    engine.setup_all()
    print(f"[run] 已注册检测器: {engine.detectors}", flush=True)

    scheduler = StreamScheduler(engine)
    scheduler.add_camera(camera_id=5, stream_name="test")
    scheduler.start_all()
    set_scheduler(scheduler)


if __name__ == "__main__":
    start_services()
    app.run(host="0.0.0.0", port=5000, debug=False)
