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


class FaceBoxProvider(PersonBoxProvider):
    """复用 B 的 dlib 人脸检测（FaceMatcher.detect_faces）作为人员框来源。

    项目现状：无独立人体 YOLO 检测器在运行，B 的人员框共享上下文也未落地。
    打架检测的视觉信号（近距离聚集 + 高速运动）本质只需"人在哪"的框，
    人脸框可作为人员框的代理：两人贴身打斗时人脸也贴近、随身体剧烈位移。

    零新依赖：FaceMatcher(dlib) 已在运行。人脸检测为单例，不重复加载模型。
    局限：背对/侧脸/低头时可能漏检——配合音频侧双模确认可容忍。
    """

    def __init__(self):
        self._matcher = None

    def _ensure_matcher(self):
        if self._matcher is None:
            from .face import FaceMatcher

            self._matcher = FaceMatcher()
        return self._matcher

    def get_boxes(self, frame: Frame) -> list[Box]:
        try:
            matcher = self._ensure_matcher()
            rects = matcher.detect_faces(frame.image)
        except Exception:
            return []
        boxes: list[Box] = []
        for r in rects or []:
            try:
                boxes.append((float(r.left()), float(r.top()),
                              float(r.right()), float(r.bottom())))
            except AttributeError:
                # 已是 (x1,y1,x2,y2) 元组
                boxes.append(tuple(float(v) for v in r[:4]))
        return boxes


class YoloPersonProvider(PersonBoxProvider):
    """YOLOv8n 人体检测作为人员框来源 (COCO person 类)。

    复用项目已有的 ultralytics + yolov8n.pt（street 检测器同一份权重），
    直接给出人体框，适配打斗场景（侧脸/低头/遮挡时人脸检不到，人体仍在）。
    权重解析与 StreetDetector._resolve_weights_path 保持一致的搜索顺序。
    """

    _PERSON_CLS = 0  # COCO class id: person

    def __init__(self, weights_path: str | None = None, conf: float = 0.3):
        self._weights_path = weights_path
        self._conf = float(conf)
        self._model = None

    def _resolve_weights(self):
        from pathlib import Path

        from ..config import Config

        configured = Path(self._weights_path or "yolov8n.pt")
        if configured.is_absolute():
            return configured
        backend_root = Path(__file__).resolve().parents[2]
        repo_root = backend_root.parent
        candidates = [
            backend_root / "model_weights" / configured,
            Path(Config.MODEL_DIR) / configured,
            backend_root / Config.MODEL_DIR / configured,
            repo_root / Config.MODEL_DIR / configured,
            backend_root / configured,
            repo_root / configured,
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    def _ensure_model(self):
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(str(self._resolve_weights()))
        return self._model

    def get_boxes(self, frame: Frame) -> list[Box]:
        try:
            model = self._ensure_model()
            results = model(frame.image, verbose=False)
        except Exception:
            return []
        boxes: list[Box] = []
        for result in results if isinstance(results, (list, tuple)) else [results]:
            det = getattr(result, "boxes", None)
            if det is None:
                continue
            xyxy = det.xyxy
            cls = det.cls
            conf = det.conf
            for attr in ("cpu",):
                xyxy = getattr(xyxy, attr, lambda: xyxy)() if hasattr(xyxy, attr) else xyxy
                cls = getattr(cls, attr, lambda: cls)() if hasattr(cls, attr) else cls
                conf = getattr(conf, attr, lambda: conf)() if hasattr(conf, attr) else conf
            xyxy = xyxy.numpy() if hasattr(xyxy, "numpy") else xyxy
            cls = cls.numpy() if hasattr(cls, "numpy") else cls
            conf = conf.numpy() if hasattr(conf, "numpy") else conf
            for (x1, y1, x2, y2), c, p in zip(xyxy, cls, conf):
                if int(c) != self._PERSON_CLS or float(p) < self._conf:
                    continue
                boxes.append((float(x1), float(y1), float(x2), float(y2)))
        return boxes


def build_person_provider(source: str, ctx: SharedContext | None = None) -> PersonBoxProvider:
    """按 Config.FIGHT_PERSON_SOURCE 构造人员框来源。

    - "shared"：复用 B 的引擎共享上下文（合规首选，需 B 写入才生效）。
    - "face"：复用 B 的 dlib 人脸检测作为人员框代理（零新依赖即可跑通）。
    - "yolo"：YOLOv8n 人体检测（适配打斗场景，复用 street 的 yolov8n.pt）。
    """
    if source == "shared":
        return SharedContextProvider(ctx)
    if source == "face":
        return FaceBoxProvider()
    if source == "yolo":
        return YoloPersonProvider()
    raise ValueError(f"不支持的人员框来源: {source!r}（支持 'shared' / 'face' / 'yolo'）")
