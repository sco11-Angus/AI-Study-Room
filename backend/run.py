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
    # from app.detectors.fire_smoke import FireSmokePlugin
    # from app.detectors.fight import FightPlugin
    # from app.detectors.fatigue import FatiguePlugin
    # from app.detectors.intrusion import IntrusionPlugin
    # from app.detectors.person_source import SharedContextProvider
    from app.config import Config
    from app.stream.engine import InferenceEngine
    from app.stream.scheduler import StreamScheduler, set_scheduler
    # from app.services.storage_manager import get_storage_manager

    print("[run] ===== 启动推理引擎 =====", flush=True)
    engine = InferenceEngine(max_workers=2)
    # engine.register(IntrusionPlugin(shared_ctx=engine.shared_ctx))
    engine.register(FaceDetector(skip_frames=3, cooldown=1.0))
    # engine.register(FatiguePlugin())
    # engine.register(FireSmokePlugin())
    # engine.register(FightPlugin(person_provider=SharedContextProvider(engine.shared_ctx)))
    engine.setup_all()
    print(f"[run] 已注册检测器: {engine.detectors}", flush=True)

    scheduler = StreamScheduler(engine)

    # ---- 多摄像头支持 ----
    # 优先级: STREAM_URLS > 数据库所有摄像头 > 单摄像头配置
    stream_urls_env = os.getenv("STREAM_URLS", "").strip()
    db_cams = _load_db_cameras()

    if stream_urls_env:
        # 格式: "rtmp://server/live/cam1,rtmp://server/live/cam2,0=本地摄像头"
        # 或: "name1,name2,name3"（共用 RTMP 服务器和 /live/ 前缀）
        urls = [u.strip() for u in stream_urls_env.split(",") if u.strip()]
        for i, url in enumerate(urls):
            cam_id = Config.STREAM_CAMERA_ID + i
            if url.isdigit():
                # 纯数字 → 本地摄像头索引
                scheduler.add_camera(
                    camera_id=cam_id,
                    stream_name=f"local_{url}",
                    local_camera=int(url),
                )
            elif "://" in url:
                # 完整 URL
                scheduler.add_camera(camera_id=cam_id, stream_url=url)
            else:
                # 纯名称 → 拼接 RTMP 路径
                full_url = f"rtmp://{Config.RTMP_SERVER}:{Config.RTMP_PORT}/live/{url}"
                scheduler.add_camera(camera_id=cam_id, stream_url=full_url)
    elif db_cams:
        # 从数据库加载所有摄像头
        for cam_id, cam_url, cam_name in db_cams:
            if cam_url:
                scheduler.add_camera(camera_id=cam_id, stream_url=cam_url)
            else:
                scheduler.add_camera(camera_id=cam_id, stream_name=cam_name or "test")
        print(f"[run] 从数据库加载 {len(db_cams)} 个摄像头", flush=True)
    else:
        # 回退：单摄像头配置
        camera_id = Config.STREAM_CAMERA_ID
        scheduler.add_camera(
            camera_id=camera_id,
            stream_name=Config.STREAM_NAME or None,
            local_camera=Config.STREAM_LOCAL_CAMERA,
            stream_url=Config.STREAM_URL or None,
        )

    scheduler.start_all()
    set_scheduler(scheduler)

    # print("[run] ===== 启动存储管理器 =====", flush=True)
    # storage_manager = get_storage_manager()
    # storage_manager.start()
    # stats = storage_manager.get_storage_stats()
    # print(f"[run] 存储状态: 磁盘使用率={stats['disk_usage_percent']}% "
    #       f"抓拍={stats['snapshot_size_mb']}MB 视频片段={stats['clip_size_mb']}MB", flush=True)


def _load_db_cameras() -> list[tuple[int, str, str]]:
    """从数据库加载所有摄像头，返回 [(camera_id, stream_url, name), ...]。
    数据库连接失败或无记录时返回空列表。
    """
    try:
        from app.models.database import SessionLocal
        from app.models.entities import Camera
        session = SessionLocal()
        try:
            cameras = session.query(Camera).order_by(Camera.id).all()
            result = []
            for c in cameras:
                url = (c.stream_url or "").strip()
                name = (c.name or f"cam_{c.id}").strip()
                result.append((c.id, url, name))
            return result
        finally:
            session.close()
    except Exception as e:
        print(f"[run] 数据库摄像头查询失败: {e}", flush=True)
        return []


if __name__ == "__main__":
    start_services()
    port = int(os.getenv("PORT", 5000))
    print(f"[run] ===== 启动Web服务 (端口: {port}) =====", flush=True)
    # threaded=True: 避免 3 条 WebSocket 长连接(video_feed/alarms/face)互相阻塞
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
