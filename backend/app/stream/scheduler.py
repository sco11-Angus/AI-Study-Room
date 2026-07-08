"""拉流解码 + 跳帧调度器（任务书 A3）。

- 每路摄像头一个解码线程，写入有界环形帧缓冲（丢旧帧，保证低延迟 §3.3）。
- 显示链路：全帧通过环形缓冲供前端读取。
- 推理链路：每 SKIP_N 帧构造 Frame，提交 InferenceEngine.dispatch()。
- 流状态监控：实时追踪 online/offline，断流自动重连并告警。
"""
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import cv2

from ..config import Config
from ..detectors.base import Frame

logger = logging.getLogger(__name__)

# FFmpeg 拉流参数（作用于 demuxer + 解码器）
#  showall + ignore_err：H.264 参考帧缺失时容忍继续解码
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp"
    "|analyzeduration;100000|probesize;50000"
    "|fflags;nobuffer+genpts"
    "|flags;low_delay"
    "|flags2;showall"
    "|err_detect;ignore_err"
    "|strict;unofficial"
    "|max_delay;2000000",
)

# 目标分辨率（显示+推理共用）
TARGET_W, TARGET_H = 640, 360


@dataclass
class CameraStream:
    """单路摄像头的流状态。"""

    camera_id: int
    stream_name: str                    # RTMP 推流名称，如 "test"
    stream_url: str                     # 完整拉流地址（含 live=1）
    ring_buffer: deque = field(default_factory=lambda: deque(maxlen=5))
    online: bool = False
    _frame_idx: int = 0
    _thread: threading.Thread | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _new_frame: threading.Condition = field(default_factory=threading.Condition)

    # JPEG 编码参数，平衡清晰度与体积
    _encode_params: tuple = field(
        default_factory=lambda: (int(cv2.IMWRITE_JPEG_QUALITY), 65)
    )

    def latest_frame(self) -> bytes | None:
        """获取最新帧的 JPEG bytes（供 WebSocket 推送），线程安全。"""
        with self._lock:
            if self.ring_buffer:
                return self.ring_buffer[-1]
            return None

    def wait_frame(self, timeout: float = 1.0) -> bool:
        """阻塞等待新帧到达，timeout 秒后超时返回 False。"""
        with self._new_frame:
            return self._new_frame.wait(timeout)


class StreamScheduler:
    """多摄像头拉流调度器 — 管理所有摄像头解码线程。

    用法：
        scheduler = StreamScheduler(engine)
        scheduler.add_camera(camera_id=0, stream_name="test")
        scheduler.start_all()
    """

    def __init__(self, engine: "InferenceEngine"):
        self._engine = engine          # 统一推理引擎 A2
        self._cameras: dict[int, CameraStream] = {}
        self._lock = threading.Lock()

    # ---- 摄像头管理 ----

    def add_camera(self, camera_id: int, stream_name: str) -> CameraStream:
        """添加一路摄像头，返回其流状态对象。"""
        stream_url = f"rtmp://{Config.RTMP_SERVER}:{Config.RTMP_PORT}/live/{stream_name} live=1"
        cs = CameraStream(
            camera_id=camera_id,
            stream_name=stream_name,
            stream_url=stream_url,
        )
        with self._lock:
            self._cameras[camera_id] = cs
        logger.info(f"[scheduler] 已添加摄像头: camera_id={camera_id}, stream={stream_name}")
        return cs

    def remove_camera(self, camera_id: int) -> None:
        """移除摄像头并停止其解码线程。"""
        with self._lock:
            cs = self._cameras.pop(camera_id, None)
        if cs:
            cs._stop_event.set()
            if cs._thread and cs._thread.is_alive():
                cs._thread.join(timeout=5)
            logger.info(f"[scheduler] 已移除摄像头: camera_id={camera_id}")

    def get_camera(self, camera_id: int) -> CameraStream | None:
        return self._cameras.get(camera_id)

    @property
    def camera_ids(self) -> list[int]:
        return list(self._cameras.keys())

    @property
    def status(self) -> dict[int, bool]:
        """返回所有摄像头的在线状态。"""
        return {cid: cs.online for cid, cs in self._cameras.items()}

    # ---- 启动 / 停止 ----

    def start_all(self) -> None:
        """启动所有摄像头的解码线程。"""
        for camera_id, cs in self._cameras.items():
            self._start_camera(cs)
        logger.info(f"[scheduler] 已启动 {len(self._cameras)} 路摄像头")

    def _start_camera(self, cs: CameraStream) -> None:
        """为单路摄像头启动解码线程。"""
        cs._stop_event.clear()
        cs._thread = threading.Thread(
            target=self._decode_loop,
            args=(cs,),
            daemon=True,
            name=f"cam-{cs.camera_id}",
        )
        cs._thread.start()

    def stop_all(self) -> None:
        """停止所有摄像头解码线程。"""
        for cs in self._cameras.values():
            cs._stop_event.set()
        logger.info("[scheduler] 所有摄像头已停止")

    # ---- 解码主循环 ----

    def _decode_loop(self, cs: CameraStream) -> None:
        """单路解码主循环：拉流 -> 缩放 -> 缓冲 -> 跳帧推理 -> 断流重连。"""
        cap = cv2.VideoCapture(cs.stream_url, cv2.CAP_FFMPEG)

        if not cap.isOpened():
            logger.error(f"[scheduler] camera_id={cs.camera_id} 无法打开流，3s 后重试")
            logger.error(f"               URL: {cs.stream_url}")
            cap.release()
            time.sleep(3)
            if not cs._stop_event.is_set():
                cap = cv2.VideoCapture(cs.stream_url, cv2.CAP_FFMPEG)

        cs.online = cap.isOpened()
        if cs.online:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            logger.info(f"[scheduler] camera_id={cs.camera_id} 拉流成功, 原始={w}x{h}")
        else:
            logger.error(f"[scheduler] camera_id={cs.camera_id} 重试失败")

        # 超时控制：参考帧缺失时 5s 超时而非 30s
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)

        decode_ok = 0
        decode_dropped = 0
        _last_log_ts = time.time()
        _consecutive_timeouts = 0

        while not cs._stop_event.is_set():
            ok, frame = cap.read()

            if not ok:
                _consecutive_timeouts += 1
                # ---- 超时/断流：累计 3 次超时才重连 ----
                if _consecutive_timeouts >= 3:
                    if cs.online:
                        logger.warning(
                            f"[scheduler] camera_id={cs.camera_id} "
                            f"{_consecutive_timeouts}次超时，重连"
                        )
                    cs.online = False
                    cap.release()
                    time.sleep(2)
                    if cs._stop_event.is_set():
                        return
                    cap = cv2.VideoCapture(cs.stream_url, cv2.CAP_FFMPEG)
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
                    cs._frame_idx = 0
                    _consecutive_timeouts = 0
                decode_dropped += 1
                continue

            _consecutive_timeouts = 0

            # ---- 流恢复 ----
            if not cs.online:
                logger.info(f"[scheduler] camera_id={cs.camera_id} 流已恢复, {frame.shape[1]}x{frame.shape[0]}")
                cs.online = True

            # ---- 缩放 ----
            if frame.shape[1] != TARGET_W or frame.shape[0] != TARGET_H:
                frame = cv2.resize(frame, (TARGET_W, TARGET_H))

            # ---- 环形缓冲（编码为 JPEG 供 WebSocket 推送）----
            ret, jpg = cv2.imencode(".jpg", frame, cs._encode_params)
            if ret:
                with cs._lock:
                    cs.ring_buffer.append(jpg.tobytes())
                with cs._new_frame:
                    cs._new_frame.notify_all()

            # ---- 跳帧推理 ----
            if cs._frame_idx % Config.SKIP_N == 0:
                f = Frame(
                    image=frame, ts=time.time(),
                    camera_id=cs.camera_id, frame_idx=cs._frame_idx,
                )
                self._engine.dispatch_async(f)

            cs._frame_idx += 1
            decode_ok += 1

            # 每 10s 输出解码统计
            now = time.time()
            if now - _last_log_ts >= 10:
                total = decode_ok + decode_dropped
                drop_pct = (decode_dropped / total * 100) if total else 0
                logger.info(
                    f"[scheduler] cam-{cs.camera_id} 解码统计: ok={decode_ok}, "
                    f"dropped={decode_dropped}, 掉帧率={drop_pct:.1f}%"
                )
                decode_ok = 0
                decode_dropped = 0
                _last_log_ts = now

        cap.release()
        cs.online = False
        logger.info(f"[scheduler] camera_id={cs.camera_id} 解码线程退出")


# ---- 模块级单例（供 WebSocket 等模块访问）----

_scheduler: StreamScheduler | None = None


def get_scheduler() -> StreamScheduler | None:
    """获取当前 StreamScheduler 实例。"""
    return _scheduler


def set_scheduler(scheduler: StreamScheduler) -> None:
    """设置 StreamScheduler 实例（应用启动时调用）。"""
    global _scheduler
    _scheduler = scheduler
