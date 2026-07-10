"""Run the fire/smoke model on one image and print raw detections."""
from __future__ import annotations

import argparse
import io
import logging
import sys
import warnings
from contextlib import redirect_stdout
from pathlib import Path

import cv2

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.detectors.fire_smoke import FireSmokePlugin


logging.getLogger("app.detectors.fire_smoke").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="torch.meshgrid*")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test fire/smoke model output on one image.")
    parser.add_argument(
        "image",
        nargs="?",
        default=str(REPO_ROOT / "test_photos" / "fire_test.jpg"),
        help="Image path. Defaults to test_photos/fire_test.jpg.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_path = Path(args.image)
    if not image_path.is_absolute():
        image_path = REPO_ROOT / image_path

    image = cv2.imread(str(image_path))
    if image is None:
        print(f"Could not read image: {image_path}", file=sys.stderr)
        return 1

    plugin = FireSmokePlugin()
    with redirect_stdout(io.StringIO()):
        plugin.setup()
        result = plugin._model(image)[0]

    detections = [
        {
            "class": result.names[int(cls)],
            "confidence": round(float(conf), 3),
        }
        for cls, conf in zip(result.boxes.cls, result.boxes.conf)
    ]

    print(f"image: {image_path}")
    print(f"detections: {detections}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
