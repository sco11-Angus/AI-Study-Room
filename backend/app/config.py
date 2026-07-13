"""应用配置 — 关键参数汇总（系统设计说明书 §12）。"""
import os
from pathlib import Path
from urllib.parse import quote_plus

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False


env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


def _load_env_file() -> None:
    """加载仓库根目录 .env，支持 KEY= 和 PowerShell 的 $env:KEY= 写法。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env_path = os.path.join(root, ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith("$env:"):
                key = key[len("$env:") :]
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip('"').strip("'")


_load_env_file()


def _default_database_uri() -> str:
    """Use SQLite locally unless DB_* settings explicitly request MySQL."""
    has_mysql_env = any(
        os.getenv(key)
        for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")
    )
    if not has_mysql_env:
        return "sqlite:///study_room.db"

    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    name = os.getenv("DB_NAME", "study_room")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


class Config:
    # 流处理与调度 (§3)
    SKIP_N = int(os.getenv("SKIP_N", 5))              # 每 N 帧推理一次
    # 推理帧尺寸：防区多边形以归一化坐标 [0,1] 入库，加载时 × 该尺寸还原为像素
    FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", 640))
    FRAME_HEIGHT = int(os.getenv("FRAME_HEIGHT", 480))
    RTMP_SERVER = os.getenv("RTMP_SERVER", "49.233.71.82")
    RTMP_PORT = int(os.getenv("RTMP_PORT", 9090))
    STREAM_CAMERA_ID = int(os.getenv("STREAM_CAMERA_ID", os.getenv("CAMERA_ID", 5)))
    STREAM_NAME = os.getenv("STREAM_NAME", "").strip()
    STREAM_URL = os.getenv("STREAM_URL", "").strip()
    _stream_local_camera = os.getenv("STREAM_LOCAL_CAMERA", "").strip()
    STREAM_LOCAL_CAMERA = int(_stream_local_camera) if _stream_local_camera else None

    # 疲劳检测 (§4.3)
    EAR_THRESH = float(os.getenv("EAR_THRESH", 0.2))  # 闭眼阈值
    EAR_DURATION = float(os.getenv("EAR_DURATION", 2))  # 闭眼持续(秒)
    MAR_THRESH = float(os.getenv("MAR_THRESH", 0.6))  # 打哈欠阈值
    FATIGUE_ALERT_LEVEL = int(os.getenv("FATIGUE_ALERT_LEVEL", 1))

    # 烟火检测 (§6.2)
    FIRE_WINDOW = int(os.getenv("FIRE_WINDOW", 30))   # 滑动窗口帧数
    FIRE_CONF = float(os.getenv("FIRE_CONF", 0.45))   # 平均置信度阈值
    FIRE_SMOKE_WEIGHTS = os.getenv("FIRE_SMOKE_WEIGHTS", "fire_smoke.pt")
    FIRE_SMOKE_LEGACY_YOLOV5_DIR = os.getenv(
        "FIRE_SMOKE_LEGACY_YOLOV5_DIR",
        "fire-smoke-detect-yolov4-master/yolov5",
    )
    FIRE_SMOKE_MODEL_LOADER = os.getenv("FIRE_SMOKE_MODEL_LOADER", "legacy").strip().lower()
    FIRE_SMOKE_IMG_SIZE = int(os.getenv("FIRE_SMOKE_IMG_SIZE", 640))
    FIRE_SMOKE_DETECT_CONF = float(os.getenv("FIRE_SMOKE_DETECT_CONF", 0.25))
    FIRE_SMOKE_IOU = float(os.getenv("FIRE_SMOKE_IOU", 0.45))
    FIRE_SMOKE_DEVICE = os.getenv("FIRE_SMOKE_DEVICE", "cpu")
    FIRE_SMOKE_REGION_ID = int(os.getenv("FIRE_SMOKE_REGION_ID", 0))
    # 强制走 legacy YOLOv5 加载器（嫁接的 best.pt 与 ultralytics YOLOv8 不兼容）
    FIRE_SMOKE_FORCE_LEGACY = os.getenv("FIRE_SMOKE_FORCE_LEGACY", "true").lower() == "true"

    # 音视频融合打架检测 (任务书 D)
    FIGHT_FUSE_THRESH = float(os.getenv("FIGHT_FUSE_THRESH", 0.6))  # 融合分告警阈值
    FIGHT_W_VIS = float(os.getenv("FIGHT_W_VIS", 0.6))    # 视觉分权重
    FIGHT_W_AUD = float(os.getenv("FIGHT_W_AUD", 0.4))    # 音频分权重
    FIGHT_DURATION = float(os.getenv("FIGHT_DURATION", 3))  # 候选持续确认(秒)
    FIGHT_ALIGN_TOL = float(os.getenv("FIGHT_ALIGN_TOL", 2))  # 音视频时间对齐容差(秒)
    FIGHT_LEVEL = int(os.getenv("FIGHT_LEVEL", 2))        # 告警分级(人身安全高优先)
    # 人员框来源: face=复用 B 的 dlib 人脸检测(默认, 零新依赖即可跑通);
    #            shared=复用 B 的引擎共享上下文(需 B 写入才生效, 合规首选)
    FIGHT_PERSON_SOURCE = os.getenv("FIGHT_PERSON_SOURCE", "face")

    # 音频管线 (任务书 D1)
    AUDIO_WINDOW = float(os.getenv("AUDIO_WINDOW", 1.0))  # 分析窗口(秒)
    AUDIO_SR = int(os.getenv("AUDIO_SR", 16000))          # 重采样率(单声道)

    # 情感分析增强打架检测 (任务书 D2)
    #  情绪作"闸门"而非加分项：无愤怒/恐惧时压制视觉冲突分，滤掉欢呼/嬉闹误报。
    EMOTION_ENABLE = os.getenv("EMOTION_ENABLE", "false").lower() == "true"  # 灰度开关
    EMOTION_DEVICE = os.getenv("EMOTION_DEVICE", "cpu")   # cpu / gpu(cuda)
    # HSEmotion 模型名: enet_b0_8_best_vgaf(默认,8类,首次自动下载权重到 ~/.hsemotion)
    EMOTION_MODEL_NAME = os.getenv("EMOTION_MODEL_NAME", "enet_b0_8_best_vgaf")
    # 闸门系数: vis' = vis * (EMOTION_GATE_FLOOR + (1-FLOOR) * emo_gate)
    #  emo_gate=0(无负面情绪) 时视觉分打 FLOOR 折; emo_gate=1 时保留全分。
    EMOTION_GATE_FLOOR = float(os.getenv("EMOTION_GATE_FLOOR", 0.4))
    # 音频侧: aud = W_EMO*声学情绪(尖叫/怒吼) + (1-W_EMO)*响度托底
    AUDIO_EMO_WEIGHT = float(os.getenv("AUDIO_EMO_WEIGHT", 0.7))
    YAMNET_MODEL_PATH = os.getenv("YAMNET_MODEL_PATH", "")  # 留空=音频情绪暂用纯声学

    # 告警升级 (§7.4)
    ESCALATE_TIMEOUT = int(os.getenv("ESCALATE_TIMEOUT", 180))  # 秒

    # 钉钉 Webhook (§7.4)
    DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
    DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")
    DINGTALK_LEADER_WEBHOOK = os.getenv("DINGTALK_LEADER_WEBHOOK", "")
    DINGTALK_LEADER_SECRET = os.getenv("DINGTALK_LEADER_SECRET", "")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

    # 统一部署模式 - 用于多人共享访问
    DEPLOY_MODE = os.getenv("DEPLOY_MODE", "local")

    # 数据库 (§8)
    DB_HOST = os.getenv("DB_HOST", os.getenv("MYSQL_HOST", "localhost"))
    DB_PORT = os.getenv("DB_PORT", os.getenv("MYSQL_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", os.getenv("MYSQL_USER", "root"))
    DB_PASSWORD = os.getenv("DB_PASSWORD", os.getenv("MYSQL_PASSWORD", ""))
    DB_NAME = os.getenv("DB_NAME", os.getenv("MYSQL_DATABASE", "study_room"))
    DB_CHARSET = os.getenv("DB_CHARSET", os.getenv("MYSQL_CHARSET", "utf8mb4"))
    DATABASE_URI = os.getenv(
        "DATABASE_URI",
        f"mysql+mysqlconnector://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}@"
        f"{DB_HOST}:{DB_PORT}/{DB_NAME}?charset={DB_CHARSET}"
    )


    # 模型权重 / 抓拍
    MODEL_DIR = os.getenv("MODEL_DIR", "model_weights")
    SNAPSHOT_DIR = os.getenv(
        "SNAPSHOT_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "snapshots")),
    )

    # 活体检测（主动/被动信号分离融合）
    LIVENESS_ENABLED = os.getenv("LIVENESS_ENABLED", "true").lower() == "true"
    LIVENESS_THRESHOLD = float(os.getenv("LIVENESS_THRESHOLD", 0.40))
    LIVENESS_HISTORY_SIZE = int(os.getenv("LIVENESS_HISTORY_SIZE", 30))
    LIVENESS_EAR_BLINK_THRESH = float(os.getenv("LIVENESS_EAR_BLINK_THRESH", 0.25))

    # EMA 平滑系数（0~1，越大响应越快，越小越平滑）
    LIVENESS_EMA_ALPHA = float(os.getenv("LIVENESS_EMA_ALPHA", 0.3))

    # 反欺骗模型 Ensemble 权重
    ANTISPOOF_WEIGHT_ONNX = float(os.getenv("ANTISPOOF_WEIGHT_ONNX", 0.5))
    ANTISPOOF_WEIGHT_PTH = float(os.getenv("ANTISPOOF_WEIGHT_PTH", 0.5))

    # 违规抓拍回放 (任务书 G)
    CLIP_PRE_SECONDS = int(os.getenv("CLIP_PRE_SECONDS", 5))    # 违规前录制秒数
    CLIP_POST_SECONDS = int(os.getenv("CLIP_POST_SECONDS", 5))   # 违规后录制秒数
    CLIP_FPS = int(os.getenv("CLIP_FPS", 15))                    # 片段帧率
    CLIP_DIR = os.getenv(
        "CLIP_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "clips")),
    )
    CLIP_MAX_DAYS = int(os.getenv("CLIP_MAX_DAYS", 7))           # 片段保留天数

    # AI 日报 (任务书 G)
    LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() == "true"
    LLM_API_URL = os.getenv("LLM_API_URL", "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen-turbo")

    # 存储管理 (针对小服务器优化)
    STORAGE_WARNING_THRESHOLD = int(os.getenv("STORAGE_WARNING_THRESHOLD", 80))    # 磁盘使用率警告阈值(%)
    STORAGE_CRITICAL_THRESHOLD = int(os.getenv("STORAGE_CRITICAL_THRESHOLD", 90))  # 磁盘使用率临界阈值(%)
    SNAPSHOT_MAX_DAYS = int(os.getenv("SNAPSHOT_MAX_DAYS", 3))                    # 抓拍保留天数
    LOG_MAX_DAYS = int(os.getenv("LOG_MAX_DAYS", 7))                              # 日志保留天数
    AUTO_CLEANUP_INTERVAL = int(os.getenv("AUTO_CLEANUP_INTERVAL", 3600))         # 自动清理间隔(秒)
