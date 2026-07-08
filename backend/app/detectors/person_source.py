"""人员框来源 — 复用 B 的检测结果，杜绝重复加载 YOLO (任务书 D2 / 协作红线②)。

协作红线："人员框只算一次"。D 的打架检测**不得**重复加载 YOLO，
只能从推理引擎的共享上下文取 B 每帧算好的人员框。

约定 (需与 A/B 对齐)：
    B 的人员检测器在 detect() 内，把本帧人员框写入引擎共享上下文：
        engine.shared_ctx.set(camera_id, frame_idx, boxes)
    D 通过 SharedContextProvider 按 (camera_id, frame_idx) 取回，零重复推理。

Box 统一格式：(x1, y1, x2, y2) 像素坐标，float 或 int 均可。
"""
from abc import ABC, abstractmethod
from typing import Protocol

from .base import Frame

Box = tuple[float, float, float, float]


class SharedContext(Protocol):
    """引擎共享上下文协议 — A 的引擎需提供此能力供 B 写、D 读。

    仅缓存"当前帧"人员框；按 (camera_id, frame_idx) 命中，避免跨帧串用。
    """

    def get_person_boxes(self, camera_id: int, frame_idx: int) -> list[Box]:
        ...


class PersonBoxProvider(ABC):
    """人员框来源抽象 — 屏蔽"框从哪来"，业务逻辑不依赖具体来源。"""

    @abstractmethod
    def get_boxes(self, frame: Frame) -> list[Box]:
        """返回本帧人员框列表；无人则空列表。"""
        ...


class SharedContextProvider(PersonBoxProvider):
    """从引擎共享上下文取 B 算好的人员框 (生产/联调，合规首选)。

    B 尚未接入共享上下文时返回空列表 —— D 视觉侧自然给 0 分，
    不误报也不重复推理；待 B 上线写入后即自动生效。
    """

    def __init__(self, ctx: SharedContext | None = None):
        self._ctx = ctx

    def bind(self, ctx: SharedContext) -> None:
        """引擎装配时注入共享上下文。"""
        self._ctx = ctx

    def get_boxes(self, frame: Frame) -> list[Box]:
        if self._ctx is None:
            return []
        return self._ctx.get_person_boxes(frame.camera_id, frame.frame_idx)


def build_person_provider(source: str, ctx: SharedContext | None = None) -> PersonBoxProvider:
    """按 Config.FIGHT_PERSON_SOURCE 构造人员框来源。

    当前仅支持 "shared"（复用 B，合规）。保留参数以便后续扩展来源类型。
    """
    if source == "shared":
        return SharedContextProvider(ctx)
    raise ValueError(f"不支持的人员框来源: {source!r}（当前仅支持 'shared'）")
