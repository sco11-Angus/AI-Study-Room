"""One-shot stream capture helpers for Task E local integration testing."""
from __future__ import annotations

import time

import cv2
import numpy as np


class StreamCaptureError(RuntimeError):
    """Raised when a frame cannot be captured from a stream source."""


def capture_frame(
    stream_url: str,
    timeout: float = 8.0,
    warmup_frames: int = 2,
    camera_id: int = 0,
) -> np.ndarray:
    """Capture one frame from an RTMP/RTSP/video source.

    This is intentionally a one-shot utility for Task E tests. The production
    pull loop remains owned by the stream scheduler in module A.

    If the stream scheduler is already pulling from this camera, we'll try to
    get the latest frame from the ring buffer first to avoid opening a second
    RTMP connection.
    """
    if not stream_url:
        raise StreamCaptureError("stream_url is required")
    if timeout <= 0:
        raise StreamCaptureError("timeout must be positive")
    if warmup_frames < 0:
        raise StreamCaptureError("warmup_frames must be >= 0")

    frame = _try_get_from_scheduler(camera_id, timeout)
    if frame is not None:
        return frame

    cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            raise StreamCaptureError(f"failed to open stream: {stream_url}")

        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(timeout * 1000))
        deadline = time.time() + timeout
        captured: np.ndarray | None = None
        ok_frames = 0

        while time.time() < deadline:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue

            captured = frame
            ok_frames += 1
            if ok_frames > warmup_frames:
                return frame

        if captured is not None:
            return captured
        raise StreamCaptureError(f"timed out capturing frame from stream: {stream_url}")
    finally:
        cap.release()


def _try_get_from_scheduler(camera_id: int, timeout: float) -> np.ndarray | None:
    """Try to get the latest frame from the stream scheduler's ring buffer.

    This avoids opening a second RTMP connection when the scheduler is already
    pulling from the same camera.
    """
    try:
        from ..stream.scheduler import get_scheduler

        scheduler = get_scheduler()
        if scheduler is None:
            return None

        cam = scheduler.get_camera(camera_id)
        if cam is None:
            for cid in scheduler.camera_ids:
                cam = scheduler.get_camera(cid)
                if cam:
                    jpg_bytes = cam.latest_frame()
                    if jpg_bytes:
                        frame = cv2.imdecode(np.frombuffer(jpg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            return frame
            return None

        jpg_bytes = cam.latest_frame()
        if jpg_bytes is None and timeout > 0:
            deadline = time.time() + timeout
            while time.time() < deadline and jpg_bytes is None:
                cam.wait_frame(timeout=min(1.0, max(0.0, deadline - time.time())))
                jpg_bytes = cam.latest_frame()
                if jpg_bytes:
                    break
        if jpg_bytes is None:
            return None

        frame = cv2.imdecode(np.frombuffer(jpg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            return frame
        return None
    except Exception:
        return None
