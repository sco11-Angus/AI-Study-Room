"""统一推理引擎 — 杜绝算力争抢的核心（任务书 A2）。

维护唯一 ThreadPoolExecutor(max_workers=2)，所有检测器在此执行。
检测器内部禁止创建线程或推理循环（Code Review 逐项检查）。
"""
import logging
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from ..detectors.base import AlarmEvent, Detector, Frame
from ..detectors.person_source import Box

logger = logging.getLogger(__name__)


class SharedPersonContext:
    """Small thread-safe cache of person boxes keyed by camera/frame."""

    def __init__(self, max_entries: int = 64):
        self._max_entries = max_entries
        self._boxes: OrderedDict[tuple[int, int], list[Box]] = OrderedDict()
        self._lock = threading.Lock()

    def set(self, camera_id: int, frame_idx: int, boxes: list[Box]) -> None:
        key = (camera_id, frame_idx)
        with self._lock:
            self._boxes[key] = list(boxes)
            self._boxes.move_to_end(key)
            while len(self._boxes) > self._max_entries:
                self._boxes.popitem(last=False)

    def get_person_boxes(self, camera_id: int, frame_idx: int) -> list[Box]:
        with self._lock:
            return list(self._boxes.get((camera_id, frame_idx), []))


class InferenceEngine:
    """统一推理引擎 — 管理所有检测器的注册、启停与调度。

    用法：
        engine = InferenceEngine()
        engine.register(IntrusionDetector(...))
        engine.setup_all()
        events = engine.dispatch(frame)
    """

    def __init__(self, max_workers: int = 1):
        self._detectors: dict[str, Detector] = {}          # name -> detector（注册顺序）
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self.shared_ctx = SharedPersonContext()
        self._setup_done = False

    # ---- 注册与启停 ----

    def register(self, detector: Detector) -> None:
        """注册检测器。同名检测器后注册覆盖先注册。"""
        if detector.name in self._detectors:
            logger.warning(f"[engine] 检测器 {detector.name} 已存在，将被覆盖")
        self._detectors[detector.name] = detector
        logger.info(f"[engine] 已注册检测器: {detector.name}")

    def unregister(self, name: str) -> None:
        """注销检测器。"""
        if name in self._detectors:
            del self._detectors[name]
            logger.info(f"[engine] 已注销检测器: {name}")

    def set_enabled(self, name: str, enabled: bool) -> None:
        """启停指定检测器（供 C 的 seat_status 动态控制）。"""
        if name not in self._detectors:
            logger.warning(f"[engine] 检测器不存在: {name}")
            return
        self._detectors[name].enabled = enabled
        logger.info(f"[engine] 检测器 {name}: enabled={enabled}")

    # ---- 初始化 ----

    def setup_all(self) -> None:
        """引擎启动时对所有已注册检测器调用 setup() 加载权重。"""
        for name, detector in self._detectors.items():
            try:
                logger.info(f"[engine] 正在加载 {name} ...")
                detector.setup()
                logger.info(f"[engine] {name} 加载完成")
            except Exception:
                logger.exception(f"[engine] {name} 加载失败")
        self._setup_done = True

    # ---- 推理调度 ----

    def dispatch(self, frame: Frame) -> list[AlarmEvent]:
        """按注册顺序串行调用各 enabled 检测器，收集所有告警事件。

        由调度器 A3 通过 pool.submit 异步调用，不阻塞拉流线程。
        """
        events: list[AlarmEvent] = []
        for name, detector in self._detectors.items():
            if not detector.enabled:
                continue
            # camera_ids 过滤：None=所有摄像头都跑；否则仅在列表内的 camera_id 上执行。
            # 用于把重型检测器（如街道 YOLO）限定到指定几路，避免全路推理打爆线程池。
            allowed = getattr(detector, "camera_ids", None)
            if allowed is not None and frame.camera_id not in allowed:
                continue
            try:
                result = detector.detect(frame)
                if result:
                    events.extend(result)
            except Exception:
                logger.exception(f"[engine] {name}.detect() 异常，跳过本帧")
        return events

    def dispatch_async(self, frame: Frame) -> None:
        """异步调度：提交到线程池执行，告警传回 AlarmService。

        背压：池任务队列积压超过阈值时丢弃当前帧的推理，防止延迟无限累积。
        显示链路（ring_buffer）不受影响，仅跳过本帧推理。
        """
        if not self._detectors:
            return
        if self._pool._work_queue.qsize() > 2:
            logger.debug("[engine] 推理队列积压，丢弃本帧 camera_id=%s idx=%s",
                         frame.camera_id, frame.frame_idx)
            return
        self._pool.submit(self._dispatch_and_raise, frame)

    def _dispatch_and_raise(self, frame: Frame) -> None:
        """线程池中执行：推理 -> 提告警。"""
        events = self.dispatch(frame)
        if events:
            from ..services.alarm import get_alarm_service
            svc = get_alarm_service()
            for evt in events:
                try:
                    if not evt.camera_id:
                        evt.camera_id = frame.camera_id
                    if not evt.ts:
                        evt.ts = frame.ts
                    if "level" in evt.extra and evt.level == 1:
                        evt.level = int(evt.extra["level"])

                    if evt.extra.get("lifecycle") in {"cleared", "allowed"}:
                        from ..api.ws import broadcast_alarm

                        message = {
                            "event": "region_state",
                            "state": evt.extra["lifecycle"],
                            "region_id": evt.region_id,
                            "camera_id": evt.camera_id,
                            "alarm_type": evt.type,
                            "track_key": evt.extra.get("track_key", ""),
                        }
                        if evt.extra["lifecycle"] == "allowed":
                            message.update({
                                "seat_name": evt.extra.get("seat_name", ""),
                                "member_id": evt.extra.get("member_id"),
                                "member_name": evt.extra.get("member_name", ""),
                            })
                        broadcast_alarm(message)
                        continue

                    snapshot = evt.snapshot if evt.snapshot is not None else frame.image
                    svc.raise_alarm(evt, frame=snapshot)
                except Exception:
                    logger.exception(f"[engine] 告警推送失败: {evt}")

    # ---- 热更新 ----

    def on_config_changed(self, name: str, cfg: dict) -> None:
        """通知指定检测器配置变更（防区/参数热更新）。"""
        if name not in self._detectors:
            return
        try:
            self._detectors[name].on_config_changed(cfg)
        except Exception:
            logger.exception(f"[engine] {name}.on_config_changed() 失败")

    # ---- 查询 ----

    @property
    def detectors(self) -> list[str]:
        """返回已注册检测器名称列表。"""
        return list(self._detectors.keys())

    def is_enabled(self, name: str) -> bool:
        """查询检测器是否启用。"""
        d = self._detectors.get(name)
        return d.enabled if d else False

    # ---- 清理 ----

    def shutdown(self) -> None:
        """关闭线程池。"""
        self._pool.shutdown(wait=True)
        logger.info("[engine] 推理引擎已关闭")
