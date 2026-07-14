"""街道场景检测器 — 沙盘识别路的车辆/行人当前画面计数（street-monitoring）。

设计要点（见 openspec/changes/street-monitoring/design.md）：
- 仅在识别路（camera_ids）上执行 YOLOv8n 推理，由 InferenceEngine 按 camera_ids 过滤。
- 计数是逐帧连续状态，不产 AlarmEvent，经 broadcast_street_stats() 走 /ws/street 旁路推送。
- 输出归一化坐标（中心点 x,y + 宽高 w,h），与前端渲染分辨率解耦，复用人脸框绘制套路。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..config import Config
from .base import AlarmEvent, Detector, Frame

logger = logging.getLogger(__name__)

# COCO 类 id -> 街道白名单类别名。其余类别忽略。
STREET_CLASSES: dict[int, str] = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

# 识别路 camera_id（对齐 沙盘_rtsp_streams.md 序号）：
#  3 行人检测 / 2 停车场出口 / 11 停车场入口 / 9 隧道车辆数量
STREET_CAMERA_IDS = [3, 2, 11, 9]


class StreetDetector(Detector):
    """沙盘街道识别路：yolov8n 当前画面计数 + 归一化检测框，经旁路通道推送。"""

    name = "street"
    camera_ids = STREET_CAMERA_IDS

    def __init__(
        self,
        weights_path: str | None = None,
        conf: float = 0.25,
        camera_ids: list[int] | None = None,
    ):
        self._weights_path = weights_path
        self._conf = float(conf)
        self._model: Any | None = None
        if camera_ids is not None:
            self.camera_ids = camera_ids

    def setup(self) -> None:
        weights = self._resolve_weights_path()
        if not weights.exists():
            raise FileNotFoundError(f"[street] model weights not found: {weights}")

        from ultralytics import YOLO

        self._model = YOLO(str(weights))
        logger.info("[street] yolov8n weights loaded: %s (识别路=%s)", weights, self.camera_ids)

    def detect(self, frame: Frame) -> list[AlarmEvent]:
        if self._model is None:
            return []

        counts = {name: 0 for name in STREET_CLASSES.values()}
        boxes: list[dict[str, Any]] = []
        cam = frame.camera_id

        results = self._infer(frame.image)
        for result in _iter_results(results):
            det_boxes = getattr(result, "boxes", None)
            if det_boxes is None:
                continue
            # xywhn: 归一化中心点 [x,y,w,h]（供前端画框）
            xywhn = _to_list(getattr(det_boxes, "xywhn", []))
            confs = _to_list(getattr(det_boxes, "conf", []))
            classes = _to_list(getattr(det_boxes, "cls", []))

            for xywh, conf, cls_id in zip(xywhn, confs, classes):
                cls_name = STREET_CLASSES.get(int(cls_id))
                if cls_name is None:
                    continue
                conf = float(conf)
                if conf < self._conf:
                    continue
                counts[cls_name] += 1
                x, y, w, h = (float(v) for v in xywh)
                boxes.append({
                    "cls": cls_name,
                    "x": round(x, 4),
                    "y": round(y, 4),
                    "w": round(w, 4),
                    "h": round(h, 4),
                    "conf": round(conf, 3),
                })

        from ..api.ws import broadcast_street_stats

        broadcast_street_stats({
            "type": "street",
            "camera_id": cam,
            "ts": frame.ts,
            "counts": counts,
            "boxes": boxes,
        })

        # 计数为连续状态，不进告警中心
        return []

    def _infer(self, image: Any) -> Any:
        try:
            return self._model(image, verbose=False)
        except TypeError:
            return self._model(image)

    def _resolve_weights_path(self) -> Path:
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
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]


def _iter_results(results: Any) -> list:
    if results is None:
        return []
    if isinstance(results, (list, tuple)):
        return list(results)
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
