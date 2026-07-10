"""Feed one image through the fire/smoke plugin long enough to test alarm output."""
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

from app.config import Config
from app.detectors.base import Frame
from app.detectors.fire_smoke import FireSmokePlugin


logging.getLogger("app.detectors.fire_smoke").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="torch.meshgrid*")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test fire/smoke AlarmEvent output on one image.")
    parser.add_argument(
        "image",
        nargs="?",
        default=str(REPO_ROOT / "test_photos" / "fire_test.jpg"),
        help="Image path. Defaults to test_photos/fire_test.jpg.",
    )
    parser.add_argument("--camera-id", type=int, default=5, help="Camera id to put into the test Frame.")
    parser.add_argument("--region-id", type=int, default=1, help="Region id to put into emitted alarms.")
    parser.add_argument(
        "--frames",
        type=int,
        default=Config.FIRE_WINDOW,
        help=f"Number of repeated frames to feed. Defaults to FIRE_WINDOW={Config.FIRE_WINDOW}.",
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

    plugin = FireSmokePlugin(region_id=args.region_id)
    with redirect_stdout(io.StringIO()):
        plugin.setup()

    events = []
    with redirect_stdout(io.StringIO()):
        for idx in range(args.frames):
            events.extend(
                plugin.detect(
                    Frame(
                        image=image,
                        ts=float(idx),
                        camera_id=args.camera_id,
                        frame_idx=idx,
                    )
                )
            )

    print(f"image: {image_path}")
    print(f"frames: {args.frames}")
    print(f"events: {[event.to_dict() for event in events]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
