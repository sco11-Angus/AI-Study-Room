"""Analyze a local video and export EAR/MAR fatigue metrics to CSV."""
from __future__ import annotations

import argparse
import csv
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config
from app.detectors.fatigue import FatigueDetector


def _shape_to_landmarks(shape) -> np.ndarray:
    return np.array([(shape.part(i).x, shape.part(i).y) for i in range(68)], dtype=np.float32)


def analyze_video(video_path: str, output_path: str, model_path: str | None = None) -> int:
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")

    predictor_path = model_path or os.path.join(Config.MODEL_DIR, "shape_predictor_68_face_landmarks.dat")
    if not os.path.exists(predictor_path):
        raise FileNotFoundError(
            "missing Dlib landmark model: "
            f"{predictor_path}; put shape_predictor_68_face_landmarks.dat under backend/model_weights "
            "or pass --model"
        )

    import dlib

    face_detector = dlib.get_frontal_face_detector()
    shape_predictor = dlib.shape_predictor(predictor_path)
    fatigue = FatigueDetector()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"unable to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    rows = 0
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "frame_idx",
                "ts",
                "faces",
                "ear",
                "mar",
                "closed_duration",
                "yawn_hits",
                "yawn_window",
                "decision",
            ],
        )
        writer.writeheader()

        frame_idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ts = frame_idx / fps
            rgb = frame[..., ::-1].copy()
            faces = list(face_detector(rgb, 1))
            landmarks = None
            if faces:
                face = max(faces, key=lambda rect: max(0, rect.width()) * max(0, rect.height()))
                landmarks = _shape_to_landmarks(shape_predictor(rgb, face))
            result = fatigue.detect(landmarks, ts)
            metrics = result.__dict__ if result else fatigue.last_metrics
            writer.writerow({
                "frame_idx": frame_idx,
                "ts": round(ts, 3),
                "faces": len(faces),
                "ear": metrics.get("ear", 0.0),
                "mar": metrics.get("mar", 0.0),
                "closed_duration": metrics.get("closed_duration", 0.0),
                "yawn_hits": metrics.get("yawn_hits", 0),
                "yawn_window": metrics.get("yawn_window", fatigue.yawn_window),
                "decision": result.kind if result else "",
            })
            rows += 1
            frame_idx += 1

    cap.release()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="local video path")
    parser.add_argument("-o", "--output", default="fatigue_metrics.csv", help="CSV output path")
    parser.add_argument("--model", help="Dlib shape_predictor_68_face_landmarks.dat path")
    args = parser.parse_args()

    rows = analyze_video(args.video, args.output, args.model)
    print(f"FATIGUE_VIDEO_ANALYSIS_OK rows={rows} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
