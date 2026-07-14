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
from typing import Any
from urllib.parse import urlparse

import cv2

from ..config import Config
from ..detectors.base import Frame

logger = logging.getLogger(__name__)

# FFmpeg 拉流参数（作用于 demuxer + 解码器）
#  showall + ignore_err：H.264 参考帧缺失时容忍继续解码
# 增加read_attempts解决packet read max attempts exceeded问题
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp"
    "|rtmp_live;live"
    "|analyzeduration;100000|probesize;50000"
    "|fflags;nobuffer+genpts"
    "|flags;low_delay"
    "|flags2;showall"
    "|err_detect;ignore_err"
    "|strict;unofficial"
    "|max_delay;2000000"
    "|read_attempts;10000",
)
os.environ["OPENCV_FFMPEG_READ_ATTEMPTS"] = "100000"

# 目标宽度上限（显示+推理共用）。高度按各摄像头原始宽高比等比推导，
# 避免把 4:3 摄像头硬压成 16:9 导致画面变形。
TARGET_W = 640


PRE_BUFFER_SIZE = Config.CLIP_PRE_SECONDS * Config.CLIP_FPS


@dataclass
class CameraStream:
    """单路摄像头的流状态。"""

    camera_id: int
    stream_name: str                    # RTMP 推流名称，如 "test"
    stream_url: Any                     # 完整拉流地址或本地摄像头索引
    ring_buffer: deque = field(default_factory=lambda: deque(maxlen=5))
    pre_buffer: deque = field(default_factory=lambda: deque(maxlen=PRE_BUFFER_SIZE))
    online: bool = False
    _frame_idx: int = 0
    _thread: threading.Thread | None = None
    _audio_thread: threading.Thread | None = None
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

    def get_frames_since(self, ts: float) -> list[tuple[float, bytes]]:
        """获取自 ts 时间戳以来的所有帧（用于片段录制），线程安全。"""
        with self._lock:
            return [(frame_ts, jpg) for frame_ts, jpg in self.pre_buffer if frame_ts >= ts]


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
        self._abnormal_sound_plugin = None

    @property
    def engine(self) -> "InferenceEngine":
        """暴露推理引擎，供 API 层触发 on_config_changed 热更新防区。"""
        return self._engine

    def set_abnormal_sound_plugin(self, plugin) -> None:
        """Set the AbnormalSoundPlugin reference for audio pipeline feeding."""
        self._abnormal_sound_plugin = plugin
        logger.info("[scheduler] abnormal_sound plugin registered")

    # ---- 摄像头管理 ----

    def add_camera(
        self,
        camera_id: int,
        stream_name: str | None = None,
        local_camera: int | None = None,
        stream_url: str | None = None,
    ) -> CameraStream:
        """添加一路摄像头，返回其流状态对象。
        
        Args:
            camera_id: 摄像头ID（数据库中的ID）
            stream_name: RTMP推流名称，如 "test"
            local_camera: 本地摄像头索引（0=第一个USB摄像头），为None时使用RTMP流
        """
        resolved_url = stream_url.strip() if isinstance(stream_url, str) else stream_url
        if local_camera is not None:
            resolved_url = local_camera
            stream_name = f"local_{local_camera}"
        else:
            if not resolved_url and stream_name is None:
                resolved_url = self._load_stream_url_from_db(camera_id)
            if not stream_name and resolved_url:
                stream_name = self._stream_name_from_url(str(resolved_url))
            stream_name = stream_name or "test"
            if not resolved_url:
                resolved_url = f"rtmp://{Config.RTMP_SERVER}:{Config.RTMP_PORT}/live/{stream_name}"
        cs = CameraStream(
            camera_id=camera_id,
            stream_name=stream_name,
            stream_url=resolved_url,
        )
        with self._lock:
            self._cameras[camera_id] = cs
        logger.info(f"[scheduler] 已添加摄像头: camera_id={camera_id}, stream={stream_name}{', local' if local_camera is not None else ''}")
        return cs

    def _load_stream_url_from_db(self, camera_id: int) -> str:
        """Load camera.stream_url when camera_id alone identifies the source."""
        try:
            from ..models.database import SessionLocal
            from ..models.entities import Camera

            session = SessionLocal()
            try:
                camera = session.get(Camera, camera_id)
                return str(camera.stream_url or "").strip() if camera else ""
            finally:
                session.close()
        except Exception:
            logger.exception("[scheduler] failed to load stream_url for camera_id=%s", camera_id)
            return ""

    def _stream_name_from_url(self, stream_url: str) -> str:
        parsed = urlparse(stream_url.split()[0])
        path = parsed.path.rstrip("/")
        if "/live/" in path:
            return path.rsplit("/live/", 1)[1].split("/", 1)[0] or "test"
        if path:
            return path.rsplit("/", 1)[-1] or "test"
        return "test"

    def _open_capture(self, stream_url: Any):
        if isinstance(stream_url, int):
            if os.name == "nt":
                return cv2.VideoCapture(stream_url, cv2.CAP_DSHOW)
            return cv2.VideoCapture(stream_url)
        return cv2.VideoCapture(str(stream_url), cv2.CAP_FFMPEG)

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
        """为单路摄像头启动解码线程（视频）+ 音轨线程（供打架检测音频侧）。"""
        cs._stop_event.clear()
        cs._thread = threading.Thread(
            target=self._decode_loop,
            args=(cs,),
            daemon=True,
            name=f"cam-{cs.camera_id}",
        )
        cs._thread.start()

        # 音轨线程：拉音频 -> 分窗 -> 喂给打架检测器音频侧 (任务书 D1)
        cs._audio_thread = threading.Thread(
            target=self._audio_loop,
            args=(cs,),
            daemon=True,
            name=f"cam-{cs.camera_id}-audio",
        )
        cs._audio_thread.start()

    def _audio_loop(self, cs: CameraStream) -> None:
        """单路音轨主循环：解音频 -> 累积 1s 窗口 -> 投递打架检测器 和 异常声音检测器。

        仅对网络流(str URL)启用；本地摄像头索引(int)无音轨则跳过。
        ffmpeg 缺失或无检测器时优雅退出，不影响视频链路。
        """
        if isinstance(cs.stream_url, int):
            return  # 本地摄像头无音轨

        fight = self._engine._detectors.get("fight") if self._engine else None
        abnormal = self._abnormal_sound_plugin

        has_fight = fight is not None and hasattr(fight, "feed_audio")
        has_abnormal = abnormal is not None and hasattr(abnormal, "feed_audio")

        if not has_fight and not has_abnormal:
            return  # 未注册任何音频检测器，无需拉音频

        from .audio import AudioWindower, FfmpegAudioSource, ffmpeg_available

        if not ffmpeg_available():
            logger.warning("[scheduler] 未检测到 ffmpeg，音轨管线跳过 camera_id=%s", cs.camera_id)
            return

        windower = AudioWindower(camera_id=cs.camera_id)
        while not cs._stop_event.is_set():
            source = FfmpegAudioSource(str(cs.stream_url).split()[0])
            try:
                for pcm in source.read():
                    if cs._stop_event.is_set():
                        break
                    for chunk in windower.feed(pcm, ts=time.time()):
                        if has_fight:
                            try:
                                fight.feed_audio(chunk)
                            except Exception:
                                logger.exception("[scheduler] feed_audio(fight) 失败 camera_id=%s", cs.camera_id)
                        if has_abnormal:
                            try:
                                abnormal.feed_audio(chunk)
                            except Exception:
                                logger.exception("[scheduler] feed_audio(abnormal_sound) 失败 camera_id=%s", cs.camera_id)
            except Exception:
                logger.exception("[scheduler] 音轨读取异常 camera_id=%s", cs.camera_id)
            finally:
                source.close()
            if not cs._stop_event.is_set():
                time.sleep(3)  # 音频流断开后重连退避
        logger.info("[scheduler] camera_id=%s 音轨线程退出", cs.camera_id)

    def stop_all(self) -> None:
        """停止所有摄像头解码线程。"""
        for cs in self._cameras.values():
            cs._stop_event.set()
        logger.info("[scheduler] 所有摄像头已停止")

    # ---- 解码主循环 ----

    def _decode_loop(self, cs: CameraStream) -> None:
        """单路解码主循环：拉流 -> 缩放 -> 缓冲 -> 跳帧推理 -> 断流重连。"""
        cap = None

        # 指数退避状态
        _reconnect_delay = 1  # 当前重连延迟（秒），成功后重置

        while not cs._stop_event.is_set():
            if cap is None or not cap.isOpened():
                logger.info(f"[scheduler] camera_id={cs.camera_id} 连接流: {cs.stream_url}")
                cap = self._open_capture(cs.stream_url)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    logger.info(f"[scheduler] camera_id={cs.camera_id} 拉流成功, 原始={w}x{h}")
                    cs.online = True
                else:
                    logger.error(f"[scheduler] camera_id={cs.camera_id} 连接失败，5s后重试")
                    cs.online = False
                    if cap:
                        cap.release()
                        cap = None
                    time.sleep(5)
                    continue

            decode_ok = 0
            decode_dropped = 0
            _last_log_ts = time.time()
            _consecutive_timeouts = 0
            _reconnect_delay = 1  # 正常读取时重置退避

            while not cs._stop_event.is_set() and cap.isOpened():
                ok, frame = cap.read()

                if not ok:
                    _consecutive_timeouts += 1
                    if _consecutive_timeouts >= 5:
                        if cs.online:
                            logger.warning(
                                f"[scheduler] camera_id={cs.camera_id} "
                                f"{_consecutive_timeouts}次超时，重连"
                            )
                        cs.online = False
                        cap.release()
                        cap = None
                        break
                    decode_dropped += 1
                    time.sleep(0.1)
                    continue

                _consecutive_timeouts = 0

                # 等比缩放：宽度超过上限才缩，高度按原始比例推导，保持画面不变形
                src_h, src_w = frame.shape[0], frame.shape[1]
                if src_w > TARGET_W:
                    target_h = max(1, round(src_h * TARGET_W / src_w))
                    frame = cv2.resize(frame, (TARGET_W, target_h))

                ret, jpg = cv2.imencode(".jpg", frame, cs._encode_params)
                if ret:
                    frame_ts = time.time()
                    with cs._lock:
                        cs.ring_buffer.append(jpg.tobytes())
                        cs.pre_buffer.append((frame_ts, jpg.tobytes()))
                    with cs._new_frame:
                        cs._new_frame.notify_all()

                if cs._frame_idx % Config.SKIP_N == 0:
                    f = Frame(
                        image=frame, ts=time.time(),
                        camera_id=cs.camera_id, frame_idx=cs._frame_idx,
                    )
                    self._engine.dispatch_async(f)

                cs._frame_idx += 1
                decode_ok += 1

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

        if cap:
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
