"""烟雾/明火检测 - YOLO 推理 + 连续帧置信度防误报 (系统设计说明书 §6)."""
from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from ..config import Config
from .base import AlarmEvent, Detector, Frame

logger = logging.getLogger(__name__)

class FireSmokePlugin(Detector):
    name = "fire_smoke"

class FireSmokeDetector:
    """对 fire/smoke 置信度做滑动窗口确认."""

    def __init__(self):
        self._window: deque[float] = deque(maxlen=Config.FIRE_WINDOW)

    @property
    def average_confidence(self) -> float:
        if not self._window:
            return 0.0
        return sum(self._window) / len(self._window)



    def feed(self, conf: float) -> bool:
        """送入本帧 fire/smoke 最大置信度，返回是否判定为有效灾情."""
        conf = max(0.0, min(float(conf), 1.0))
        self._window.append(conf)
        if len(self._window) < Config.FIRE_WINDOW:
            return False
        return self.average_confidence > Config.FIRE_CONF


class FireSmokePlugin(Detector):
    """烟火检测插件 - 注册进统一推理引擎，不创建线程或推理循环."""

    name = "fire_smoke"

    def __init__(
        self,
        region_id: int | None = None,
        model: Any | None = None,
        weights_path: str | None = None,
        target_classes: Iterable[str] = ("fire", "smoke"),
    ):
        self.region_id = Config.FIRE_SMOKE_REGION_ID if region_id is None else region_id
        self._model = model
        self._weights_path = weights_path
        self._target_classes = {name.lower() for name in target_classes}
        self._debouncer = FireSmokeDetector()

    def setup(self) -> None:
        """加载 YOLO 烟火权重；测试可注入 fake model 跳过真实加载."""
        if self._model is not None:
            logger.info("[fire_smoke] 使用已注入模型，跳过权重加载")
            return

        weights = self._resolve_weights_path()
        if not weights.exists():
            raise FileNotFoundError(f"[fire_smoke] 模型权重不存在: {weights}")
        if weights.stat().st_size <= 0:
            raise RuntimeError(f"[fire_smoke] 模型权重为空文件: {weights}")

        try:
            from ultralytics import YOLO

            self._model = YOLO(str(weights))
            logger.info("[fire_smoke] YOLO 权重加载完成: %s", weights)
        except Exception as exc:
            logger.warning("[fire_smoke] Ultralytics YOLO 加载失败，尝试旧 YOLOv5 适配: %s", exc)
            self._model = self._load_legacy_yolov5(weights)
            logger.info("[fire_smoke] legacy YOLOv5 权重加载完成: %s", weights)

    def detect(self, frame: Frame) -> list[AlarmEvent]:
        if self._model is None:
            return []

        results = self._infer(frame.image)
        conf, cls_name = self._max_fire_smoke_conf(results)
        if not self._debouncer.feed(conf):
            return []

        avg = self._debouncer.average_confidence
        logger.warning(
            "[fire_smoke] 烟火告警 camera=%s region=%s conf=%.3f avg=%.3f",
            frame.camera_id,
            self.region_id,
            conf,
            avg,
        )
        return [
            AlarmEvent(
                type="fire_smoke",
                region_id=self.region_id,
                camera_id=frame.camera_id,
                ts=frame.ts,
                level=1,
                confidence=conf,
                snapshot=frame.image,
                extra={
                    "detected_class": cls_name,
                    "fire_smoke_conf": round(conf, 3),
                    "avg_conf": round(avg, 3),
                    "window": Config.FIRE_WINDOW,
                    "threshold": Config.FIRE_CONF,
                    "frame_idx": frame.frame_idx,
                },
            )
        ]

    def _infer(self, image: Any) -> Any:
        try:
            return self._model(image, verbose=False)
        except TypeError:
            return self._model(image)

    def _resolve_weights_path(self) -> Path:
        configured = Path(self._weights_path or Config.FIRE_SMOKE_WEIGHTS)
        if configured.is_absolute():
            return configured

        backend_root = Path(__file__).resolve().parents[2]
        repo_root = backend_root.parent
        candidates = [
            Path(Config.MODEL_DIR) / configured,
            backend_root / Config.MODEL_DIR / configured,
            repo_root / Config.MODEL_DIR / configured,
            backend_root / configured,
            repo_root / configured,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[1]

    def _load_legacy_yolov5(self, weights: Path) -> Any:
        from .legacy_yolov5 import LegacyYolov5FireSmokeModel

        return LegacyYolov5FireSmokeModel(
            weights_path=weights,
            source_dir=self._resolve_legacy_yolov5_dir(),
            image_size=Config.FIRE_SMOKE_IMG_SIZE,
            conf_thres=Config.FIRE_SMOKE_DETECT_CONF,
            iou_thres=Config.FIRE_SMOKE_IOU,
            device=Config.FIRE_SMOKE_DEVICE,
        )

    def _resolve_legacy_yolov5_dir(self) -> Path:
        configured = Path(Config.FIRE_SMOKE_LEGACY_YOLOV5_DIR)
        if configured.is_absolute():
            return configured

        backend_root = Path(__file__).resolve().parents[2]
        repo_root = backend_root.parent
        candidates = [
            backend_root / configured,
            repo_root / configured,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[-1]

    def _max_fire_smoke_conf(self, results: Any) -> tuple[float, str | None]:
        best_conf = 0.0
        best_class = None
        for result in _iter_results(results):
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue

            confs = _to_list(getattr(boxes, "conf", []))
            classes = _to_list(getattr(boxes, "cls", []))
            names = getattr(result, "names", None) or getattr(self._model, "names", {})
            for cls_id, conf in zip(classes, confs):
                class_name = _class_name(names, cls_id)
                if class_name.lower() not in self._target_classes:
                    continue
                conf = float(conf)
                if conf > best_conf:
                    best_conf = conf
                    best_class = class_name
        return best_conf, best_class

def _iter_results(results: Any) -> Iterable[Any]:
    if results is None:
        return []
    if isinstance(results, (list, tuple)):
        return results
    return [results]


def _to_list(values: Any) -> list:
    if values is None:
        return []
    if hasattr(values, "detach"):
        values = values.detach()
    if hasattr(values, "cpu"):
        values = values.cpu()
    if hasattr(values, "numpy"):
        values = values.numpy()
    if hasattr(values, "tolist"):
        values = values.tolist()
    if isinstance(values, tuple):
        values = list(values)
    if isinstance(values, list):
        return values
    return [values]

def _class_name(names: Any, cls_id: Any) -> str:
    idx = int(cls_id)
    if isinstance(names, dict):
        return str(names.get(idx, idx))
    if isinstance(names, (list, tuple)) and 0 <= idx < len(names):
        return str(names[idx])
    return str(idx)
