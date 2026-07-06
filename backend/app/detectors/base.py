"""Detector 插件接口 — 统一帧格式与检测器基类（任务书 A1）。

B/C/D 所有检测器统一实现此接口。接口冻结后不得随意修改签名。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Frame:
    """统一帧格式 — 所有检测器入参。

    由调度器 A3 每 SKIP_N 帧构造一次，传入 InferenceEngine.dispatch()。
    """

    image: np.ndarray  # BGR 图像（原始分辨率）
    ts: float          # 帧时间戳（秒，time.time()）
    camera_id: int     # 摄像头 ID
    frame_idx: int     # 全局帧序号


@dataclass
class AlarmEvent:
    """告警事件 — 检测器产出，由推理引擎透传给 E 的 AlarmService。

    E（告警中心）负责入库、抓拍、推送等闭环动作。
    """

    region_id: int                     # 关联防区 ID
    type: str                          # 告警类型：intrusion / fire_smoke / fatigue
    confidence: float = 0.0            # 置信度（可选）
    snapshot: np.ndarray | None = None # 抓拍帧（可选，传入 AlarmService）
    face_crop: np.ndarray | None = None# 裁剪面部（可选）
    extra: dict[str, Any] = field(default_factory=dict)  # 扩展字段


class Detector(ABC):
    """检测器基类 — B/C/D 所有检测器必须继承。

    硬约束（Code Review 逐项检查）：
    - 禁止内部创建 Thread / ThreadPoolExecutor / while True 推理循环。
    - 所有推理由 InferenceEngine 调度。
    """

    # ---- 子类必须覆盖 ----
    name: str                       # 唯一标识，如 "intrusion"、"fire_smoke"、"fatigue"
    enabled: bool = True            # 供 C 的 seat_status 动态启停

    @abstractmethod
    def setup(self) -> None:
        """加载模型权重（引擎启动时调用一次）。

        在此方法中完成模型加载、GPU 预热等初始化操作。
        """
        ...

    @abstractmethod
    def detect(self, frame: Frame) -> list[AlarmEvent]:
        """对单帧执行推理，返回 0 或多个告警事件。

        由 InferenceEngine.dispatch() 按注册顺序串行调用。
        """
        ...

    def on_config_changed(self, cfg: dict[str, Any]) -> None:
        """防区 / 参数热更新（可选实现）。

        当管理端修改防区多边形、阈值等配置时由引擎调用。
        """
        pass
