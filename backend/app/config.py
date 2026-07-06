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

    # 告警升级 (§7.4)
    ESCALATE_TIMEOUT = int(os.getenv("ESCALATE_TIMEOUT", 180))  # 秒

    # 钉钉 Webhook (§7.4)
    DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")

    # 数据库 (§8)
    DATABASE_URI = os.getenv("DATABASE_URI", "sqlite:///study_room.db")

    # 模型权重 / 抓拍
    MODEL_DIR = os.getenv("MODEL_DIR", "model_weights")
    SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", "snapshots")
