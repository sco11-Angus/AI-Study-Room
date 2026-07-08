"""应用配置 — 关键参数汇总（系统设计说明书 §12）。"""
import os


class Config:
    # 流处理与调度 (§3)
    SKIP_N = int(os.getenv("SKIP_N", 5))              # 每 N 帧推理一次
    RTMP_SERVER = os.getenv("RTMP_SERVER", "49.233.71.82")
    RTMP_PORT = int(os.getenv("RTMP_PORT", 9090))

    # 疲劳检测 (§4.3)
    EAR_THRESH = float(os.getenv("EAR_THRESH", 0.2))  # 闭眼阈值
    EAR_DURATION = float(os.getenv("EAR_DURATION", 2))  # 闭眼持续(秒)
    MAR_THRESH = float(os.getenv("MAR_THRESH", 0.6))  # 打哈欠阈值

    # 烟火检测 (§6.2)
    FIRE_WINDOW = int(os.getenv("FIRE_WINDOW", 30))   # 滑动窗口帧数
    FIRE_CONF = float(os.getenv("FIRE_CONF", 0.45))   # 平均置信度阈值

    # 音视频融合打架检测 (任务书 D)
    FIGHT_FUSE_THRESH = float(os.getenv("FIGHT_FUSE_THRESH", 0.6))  # 融合分告警阈值
    FIGHT_W_VIS = float(os.getenv("FIGHT_W_VIS", 0.6))    # 视觉分权重
    FIGHT_W_AUD = float(os.getenv("FIGHT_W_AUD", 0.4))    # 音频分权重
    FIGHT_DURATION = float(os.getenv("FIGHT_DURATION", 3))  # 候选持续确认(秒)
    FIGHT_ALIGN_TOL = float(os.getenv("FIGHT_ALIGN_TOL", 2))  # 音视频时间对齐容差(秒)
    FIGHT_LEVEL = int(os.getenv("FIGHT_LEVEL", 2))        # 告警分级(人身安全高优先)
    # 人员框来源: shared=复用 B 的引擎共享上下文(生产, 合规); 不重复加载 YOLO
    FIGHT_PERSON_SOURCE = os.getenv("FIGHT_PERSON_SOURCE", "shared")

    # 音频管线 (任务书 D1)
    AUDIO_WINDOW = float(os.getenv("AUDIO_WINDOW", 1.0))  # 分析窗口(秒)
    AUDIO_SR = int(os.getenv("AUDIO_SR", 16000))          # 重采样率(单声道)

    # 告警升级 (§7.4)
    ESCALATE_TIMEOUT = int(os.getenv("ESCALATE_TIMEOUT", 180))  # 秒

    # 钉钉 Webhook (§7.4)
    DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")

    # 数据库 (§8)
    DATABASE_URI = os.getenv("DATABASE_URI", "sqlite:///study_room.db")

    # 模型权重 / 抓拍
    MODEL_DIR = os.getenv("MODEL_DIR", "model_weights")
    SNAPSHOT_DIR = os.getenv(
        "SNAPSHOT_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "snapshots")),
    )
