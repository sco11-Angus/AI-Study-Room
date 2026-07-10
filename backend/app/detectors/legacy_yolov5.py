"""Compatibility wrapper for the legacy YOLOv5 fire/smoke checkpoint."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import cv2
import numpy as np
import torch
import torchvision


@dataclass
class _Boxes:
    conf: list[float]
    cls: list[int]


class LegacyYolov5FireSmokeModel:
    """Loads and runs the repository-local legacy YOLOv5 fire/smoke model."""

    def __init__(
        self,
        weights_path: Path,
        source_dir: Path,
        image_size: int = 640,
        conf_thres: float = 0.25,
        iou_thres: float = 0.45,
        device: str = "cpu",
    ):
        self.weights_path = Path(weights_path)
        self.source_dir = Path(source_dir)
        self.image_size = int(image_size)
        self.conf_thres = float(conf_thres)
        self.iou_thres = float(iou_thres)
        self.device = _select_device(device)
        self.model = self._load_model()
        self.names = getattr(self.model, "names", {0: "fire", 1: "smoke"})

    def __call__(self, image: np.ndarray, **_: Any) -> list[Any]:
        if image is None:
            return []

        img, ratio, pad = _letterbox(image, self.image_size)
        img = img[:, :, ::-1].transpose(2, 0, 1)
        img = np.ascontiguousarray(img)
        tensor = torch.from_numpy(img).to(self.device).float() / 255.0
        if tensor.ndimension() == 3:
            tensor = tensor.unsqueeze(0)

        with torch.no_grad():
            pred = self.model(tensor)[0]
            det = _non_max_suppression(pred, self.conf_thres, self.iou_thres)[0]

        confs: list[float] = []
        classes: list[int] = []
        if det is not None and len(det):
            det = det.detach().cpu()
            det[:, :4] = _scale_coords(det[:, :4], ratio, pad, image.shape)
            for row in det:
                confs.append(float(row[4]))
                classes.append(int(row[5]))

        return [SimpleNamespace(boxes=_Boxes(conf=confs, cls=classes), names=self.names)]

    def _load_model(self) -> Any:
        if not self.source_dir.exists():
            raise FileNotFoundError(f"legacy YOLOv5 source directory not found: {self.source_dir}")

        with _legacy_yolov5_import_path(self.source_dir):
            from models.experimental import attempt_load

            original_load = torch.load

            def trusted_local_load(*args: Any, **kwargs: Any) -> Any:
                kwargs.setdefault("weights_only", False)
                return original_load(*args, **kwargs)

            try:
                torch.load = trusted_local_load  # type: ignore[assignment]
                model = attempt_load(str(self.weights_path), map_location=self.device)
            finally:
                torch.load = original_load  # type: ignore[assignment]

        model.to(self.device).float().eval()
        return model


def _select_device(device: str) -> torch.device:
    if device and device.lower() != "cpu" and torch.cuda.is_available():
        return torch.device(f"cuda:{device}" if device.isdigit() else device)
    return torch.device("cpu")


@contextmanager
def _legacy_yolov5_import_path(source_dir: Path) -> Iterable[None]:
    source = str(source_dir.resolve())
    inserted = False
    if source not in sys.path:
        sys.path.insert(0, source)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(source)
            except ValueError:
                pass


def _letterbox(
    image: np.ndarray,
    new_shape: int,
    color: tuple[int, int, int] = (114, 114, 114),
) -> tuple[np.ndarray, tuple[float, float], tuple[float, float]]:
    shape = image.shape[:2]
    target = (new_shape, new_shape)
    r = min(target[0] / shape[0], target[1] / shape[1])
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = target[1] - new_unpad[0], target[0] - new_unpad[1]
    dw /= 2
    dh /= 2

    if shape[::-1] != new_unpad:
        image = cv2.resize(image, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    image = cv2.copyMakeBorder(image, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return image, (r, r), (dw, dh)


def _non_max_suppression(
    prediction: torch.Tensor,
    conf_thres: float,
    iou_thres: float,
) -> list[torch.Tensor | None]:
    nc = prediction.shape[2] - 5
    output: list[torch.Tensor | None] = [None] * prediction.shape[0]
    candidates = prediction[..., 4] > conf_thres

    for image_idx, pred in enumerate(prediction):
        pred = pred[candidates[image_idx]]
        if not pred.shape[0]:
            continue

        pred[:, 5:] *= pred[:, 4:5]
        boxes = _xywh2xyxy(pred[:, :4])
        if nc > 1:
            cls_idx, cls_col = (pred[:, 5:] > conf_thres).nonzero(as_tuple=False).T
            detections = torch.cat((boxes[cls_idx], pred[cls_idx, cls_col + 5, None], cls_col[:, None].float()), 1)
        else:
            conf, cls_col = pred[:, 5:].max(1, keepdim=True)
            detections = torch.cat((boxes, conf, cls_col.float()), 1)[conf.view(-1) > conf_thres]

        if not detections.shape[0]:
            continue

        offsets = detections[:, 5:6] * 4096
        keep = torchvision.ops.nms(detections[:, :4] + offsets, detections[:, 4], iou_thres)
        output[image_idx] = detections[keep[:300]]

    return output


def _xywh2xyxy(x: torch.Tensor) -> torch.Tensor:
    y = torch.zeros_like(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2
    y[:, 1] = x[:, 1] - x[:, 3] / 2
    y[:, 2] = x[:, 0] + x[:, 2] / 2
    y[:, 3] = x[:, 1] + x[:, 3] / 2
    return y


def _scale_coords(
    coords: torch.Tensor,
    ratio: tuple[float, float],
    pad: tuple[float, float],
    original_shape: tuple[int, ...],
) -> torch.Tensor:
    coords[:, [0, 2]] -= pad[0]
    coords[:, [1, 3]] -= pad[1]
    coords[:, [0, 2]] /= ratio[0]
    coords[:, [1, 3]] /= ratio[1]
    coords[:, 0].clamp_(0, original_shape[1])
    coords[:, 1].clamp_(0, original_shape[0])
    coords[:, 2].clamp_(0, original_shape[1])
    coords[:, 3].clamp_(0, original_shape[0])
    return coords
