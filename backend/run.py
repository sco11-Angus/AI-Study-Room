"""后端启动入口 (§11)。生产部署使用 gunicorn。"""
import logging
import os
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
    from app.detectors.fatigue import FatiguePlugin
    from app.detectors.intrusion import IntrusionPlugin
    from app.detectors.person_source import SharedContextProvider
    from app.config import Config
    from app.stream.engine import InferenceEngine
    from app.stream.scheduler import StreamScheduler, set_scheduler
    from app.services.storage_manager import get_storage_manager

    print("[run] ===== 启动推理引擎 =====", flush=True)
    engine = InferenceEngine()
    # 入侵检测：跑 YOLO 检测人，并把人员框写入 engine.shared_ctx 供打架检测复用
    engine.register(IntrusionPlugin(shared_ctx=engine.shared_ctx))
    engine.register(FaceDetector(skip_frames=10, cooldown=1.0))
    engine.register(FatiguePlugin())
    engine.register(FireSmokePlugin())
    # 打架检测复用入侵检测写入 shared_ctx 的全身人体框（人员框只算一次）
    engine.register(FightPlugin(person_provider=SharedContextProvider(engine.shared_ctx)))
    engine.setup_all()
    print(f"[run] 已注册检测器: {engine.detectors}", flush=True)

    # 摄像头 ID：优先用环境变量显式指定；否则取数据库首个摄像头的真实 id，
    # 避免 scheduler 注册的 camera_id 与数据库/前端不一致导致"摄像头不存在"。
    camera_id = Config.STREAM_CAMERA_ID
    if not os.getenv("STREAM_CAMERA_ID") and not os.getenv("CAMERA_ID"):
        try:
            from app.models.database import SessionLocal
            from app.models.entities import Camera
            session = SessionLocal()
            try:
                cam = session.query(Camera).order_by(Camera.id).first()
                if cam:
                    camera_id = cam.id
                    print(f"[run] 采用数据库摄像头 id={camera_id}", flush=True)
            finally:
                session.close()
        except Exception as e:
            print(f"[run] 读取数据库摄像头失败，回退 camera_id={camera_id}: {e}", flush=True)

    scheduler = StreamScheduler(engine)
    scheduler.add_camera(
        camera_id=camera_id,
        stream_name=Config.STREAM_NAME or None,
        local_camera=Config.STREAM_LOCAL_CAMERA,
        stream_url=Config.STREAM_URL or None,
    )
    scheduler.start_all()
    set_scheduler(scheduler)

    print("[run] ===== 启动存储管理器 =====", flush=True)
    storage_manager = get_storage_manager()
    storage_manager.start()
    stats = storage_manager.get_storage_stats()
    print(f"[run] 存储状态: 磁盘使用率={stats['disk_usage_percent']}% 抓拍={stats['snapshot_size_mb']}MB 视频片段={stats['clip_size_mb']}MB", flush=True)


if __name__ == "__main__":
    start_services()
    app.run(host="0.0.0.0", port=5000, debug=False)
