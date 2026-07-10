"""视频片段录制服务 — 任务书 G2。

检测到违规后，录制「违规前N秒 + 违规后M秒」的视频片段，
供安全员在告警中心回放取证。
"""
import logging
import os
import threading
import time
from datetime import datetime

import cv2
import numpy as np

from ..config import Config
from ..stream.scheduler import get_scheduler

logger = logging.getLogger(__name__)


class ClipRecorder:
    """视频片段录制器。"""

    def __init__(self, clip_dir: str = None):
        self.clip_dir = clip_dir or Config.CLIP_DIR
        os.makedirs(self.clip_dir, exist_ok=True)
        self._recording = {}
        self._lock = threading.Lock()

    def record(self, camera_id: int, alarm_id: int, event_ts: float, alarm_type: str) -> str:
        """异步录制视频片段。
        
        Args:
            camera_id: 摄像头ID
            alarm_id: 告警ID
            event_ts: 告警触发时间戳
            alarm_type: 告警类型
            
        Returns:
            clip_url: 片段访问URL（稍后回填）
        """
        with self._lock:
            if camera_id in self._recording:
                logger.info("[clip] camera_id=%d 正在录制中，跳过", camera_id)
                return ""
        self.cleanup_old_clips()

        ts_ms = int(event_ts * 1000)
        filename = f"alarm_{alarm_id}_{ts_ms}.mp4"
        clip_url = f"/api/alarms/clips/{filename}"

        thread = threading.Thread(
            target=self._do_record,
            args=(camera_id, alarm_id, event_ts, alarm_type, filename),
            daemon=True,
            name=f"clip-{alarm_id}",
        )
        thread.start()

        return clip_url

    def _do_record(self, camera_id: int, alarm_id: int, event_ts: float, alarm_type: str, filename: str):
        """实际执行片段录制（后台线程）。"""
        try:
            scheduler = get_scheduler()
            if scheduler is None:
                logger.error("[clip] scheduler 未启动")
                return

            cs = scheduler.get_camera(camera_id)
            if cs is None or not cs.online:
                logger.error("[clip] camera_id=%d 离线", camera_id)
                return

            with self._lock:
                self._recording[camera_id] = True

            pre_frames = cs.get_frames_since(event_ts - Config.CLIP_PRE_SECONDS)
            logger.info("[clip] alarm_id=%d 预录帧: %d 帧", alarm_id, len(pre_frames))

            post_frames = []
            post_end_ts = event_ts + Config.CLIP_POST_SECONDS
            post_start = time.time()

            while time.time() < post_end_ts:
                if cs.wait_frame(timeout=0.1):
                    jpg = cs.latest_frame()
                    if jpg:
                        post_frames.append((time.time(), jpg))
                if time.time() - post_start >= Config.CLIP_POST_SECONDS + 2:
                    break

            logger.info("[clip] alarm_id=%d 后录帧: %d 帧", alarm_id, len(post_frames))

            all_frames = sorted(pre_frames + post_frames, key=lambda x: x[0])
            if not all_frames:
                logger.error("[clip] alarm_id=%d 无帧可录", alarm_id)
                with self._lock:
                    self._recording.pop(camera_id, None)
                return

            path = os.path.join(self.clip_dir, filename)
            self._encode_mp4(all_frames, path)
            logger.info("[clip] alarm_id=%d 片段已保存: %s (%d帧)", alarm_id, filename, len(all_frames))

            self._update_alarm_clip_url(alarm_id, filename)

        except Exception:
            logger.exception("[clip] alarm_id=%d 录制失败", alarm_id)
        finally:
            with self._lock:
                self._recording.pop(camera_id, None)

    def _encode_mp4(self, frames: list[tuple[float, bytes]], output_path: str):
        """将JPEG帧编码为MP4。"""
        if not frames:
            return

        first_jpg = frames[0][1]
        first_frame = cv2.imdecode(np.frombuffer(first_jpg, np.uint8), cv2.IMREAD_COLOR)
        if first_frame is None:
            logger.error("[clip] 无法解码首帧")
            return

        height, width = first_frame.shape[:2]
        fps = Config.CLIP_FPS
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        if not writer.isOpened():
            logger.error("[clip] 无法创建VideoWriter: %s", output_path)
            return

        try:
            for _, jpg_bytes in frames:
                frame = cv2.imdecode(np.frombuffer(jpg_bytes, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    writer.write(frame)
        finally:
            writer.release()

    def _update_alarm_clip_url(self, alarm_id: int, filename: str):
        """更新告警记录的clip_url字段。"""
        from ..models.database import SessionLocal
        from ..models.entities import AlarmEvent

        clip_url = f"/api/alarms/clips/{filename}"
        session = SessionLocal()
        try:
            alarm = session.query(AlarmEvent).filter_by(id=alarm_id).first()
            if alarm:
                alarm.clip_url = clip_url
                session.commit()
                logger.info("[clip] alarm_id=%d clip_url已更新", alarm_id)

                self._broadcast_clip_ready(alarm_id, clip_url)
        except Exception:
            session.rollback()
            logger.exception("[clip] 更新clip_url失败")
        finally:
            session.close()

    def _broadcast_clip_ready(self, alarm_id: int, clip_url: str):
        """通过WebSocket广播片段就绪。"""
        try:
            from ..api.ws import broadcast_alarm_update
            broadcast_alarm_update(alarm_id, {"clip_url": clip_url})
        except Exception:
            logger.exception("[clip] 广播片段就绪失败")

    def cleanup_old_clips(self, max_days: int | None = None, now: float | None = None) -> int:
        """删除超过保留天数的视频片段，返回删除数量。"""
        days = Config.CLIP_MAX_DAYS if max_days is None else max_days
        if days <= 0:
            return 0

        cutoff = (time.time() if now is None else now) - days * 24 * 60 * 60
        deleted = 0
        try:
            entries = list(os.scandir(self.clip_dir))
        except FileNotFoundError:
            return 0

        for entry in entries:
            if not entry.is_file():
                continue
            if not entry.name.lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    os.remove(entry.path)
                    deleted += 1
            except OSError:
                logger.exception("[clip] 清理旧片段失败: %s", entry.path)
        if deleted:
            logger.info("[clip] 已清理过期片段: %d", deleted)
        return deleted


_default_clip_recorder: ClipRecorder | None = None


def get_clip_recorder() -> ClipRecorder:
    """获取全局片段录制器实例。"""
    global _default_clip_recorder
    if _default_clip_recorder is None:
        _default_clip_recorder = ClipRecorder()
    return _default_clip_recorder
