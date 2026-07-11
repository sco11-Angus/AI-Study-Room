"""存储管理服务 — 针对小服务器优化。

监控磁盘使用情况，自动清理过期文件，防止磁盘耗尽。
"""
import logging
import os
import shutil
import threading
import time

from ..config import Config

logger = logging.getLogger(__name__)


class StorageManager:
    """存储管理器。"""

    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        """启动存储监控线程。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="storage-manager",
        )
        self._thread.start()
        logger.info("[storage] 存储管理器已启动")

    def stop(self):
        """停止存储监控线程。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[storage] 存储管理器已停止")

    def _run(self):
        """存储监控主循环。"""
        while self._running:
            try:
                self._check_and_cleanup()
            except Exception:
                logger.exception("[storage] 存储检查异常")
            time.sleep(Config.AUTO_CLEANUP_INTERVAL)

    def _check_and_cleanup(self):
        """检查存储状态并执行清理。"""
        disk_usage = self._get_disk_usage()
        
        if disk_usage >= Config.STORAGE_CRITICAL_THRESHOLD:
            logger.warning("[storage] 磁盘使用率达%d%%，执行紧急清理", disk_usage)
            self._emergency_cleanup()
        elif disk_usage >= Config.STORAGE_WARNING_THRESHOLD:
            logger.warning("[storage] 磁盘使用率达%d%%，执行常规清理", disk_usage)
            self._cleanup_all()
        else:
            logger.info("[storage] 磁盘使用率正常: %d%%", disk_usage)

    def _get_disk_usage(self) -> int:
        """获取磁盘使用率(%)。"""
        try:
            usage = shutil.disk_usage(os.path.abspath(Config.SNAPSHOT_DIR))
            return int(usage.used / usage.total * 100)
        except Exception:
            logger.exception("[storage] 获取磁盘使用信息失败")
            return 0

    def _cleanup_all(self):
        """执行所有清理操作。"""
        self._cleanup_snapshots()
        self._cleanup_clips()
        self._cleanup_logs()

    def _emergency_cleanup(self):
        """紧急清理：删除更多文件以释放空间。"""
        logger.warning("[storage] 紧急清理模式：删除所有超过1天的文件")
        self._cleanup_snapshots(max_days=1)
        self._cleanup_clips(max_days=1)
        self._cleanup_logs(max_days=1)

    def _cleanup_snapshots(self, max_days: int = None):
        """清理过期抓拍文件。"""
        days = max_days if max_days is not None else Config.SNAPSHOT_MAX_DAYS
        self._cleanup_dir(Config.SNAPSHOT_DIR, days, "snapshot")

    def _cleanup_clips(self, max_days: int = None):
        """清理过期视频片段。"""
        days = max_days if max_days is not None else Config.CLIP_MAX_DAYS
        self._cleanup_dir(Config.CLIP_DIR, days, "clip")

    def _cleanup_logs(self, max_days: int = None):
        """清理过期日志文件。"""
        days = max_days if max_days is not None else Config.LOG_MAX_DAYS
        log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
        self._cleanup_dir(log_dir, days, "log")

    def _cleanup_dir(self, dir_path: str, max_days: int, file_type: str):
        """清理指定目录中超过指定天数的文件。"""
        if not os.path.exists(dir_path):
            return

        cutoff = time.time() - max_days * 24 * 60 * 60
        deleted = 0
        total_size = 0

        try:
            entries = list(os.scandir(dir_path))
        except FileNotFoundError:
            return

        for entry in entries:
            if not entry.is_file():
                continue

            try:
                if entry.stat().st_mtime < cutoff:
                    file_size = entry.stat().st_size
                    os.remove(entry.path)
                    deleted += 1
                    total_size += file_size
            except OSError:
                logger.exception("[storage] 删除%s失败: %s", file_type, entry.path)

        if deleted > 0:
            logger.info(
                "[storage] 清理%s: 删除%d个文件，释放%.2f MB",
                file_type, deleted, total_size / (1024 * 1024)
            )

    def get_storage_stats(self) -> dict:
        """获取存储统计信息。"""
        stats = {
            "disk_usage_percent": self._get_disk_usage(),
            "snapshot_count": self._count_files(Config.SNAPSHOT_DIR),
            "clip_count": self._count_files(Config.CLIP_DIR),
            "log_count": self._count_files(os.path.join(os.path.dirname(__file__), "..", "..", "logs")),
            "snapshot_size_mb": self._get_dir_size(Config.SNAPSHOT_DIR),
            "clip_size_mb": self._get_dir_size(Config.CLIP_DIR),
            "log_size_mb": self._get_dir_size(os.path.join(os.path.dirname(__file__), "..", "..", "logs")),
        }
        return stats

    def _count_files(self, dir_path: str) -> int:
        """统计目录中的文件数量。"""
        if not os.path.exists(dir_path):
            return 0
        try:
            return sum(1 for entry in os.scandir(dir_path) if entry.is_file())
        except Exception:
            return 0

    def _get_dir_size(self, dir_path: str) -> float:
        """获取目录大小(MB)。"""
        if not os.path.exists(dir_path):
            return 0.0
        try:
            total_size = sum(
                entry.stat().st_size
                for entry in os.scandir(dir_path)
                if entry.is_file()
            )
            return round(total_size / (1024 * 1024), 2)
        except Exception:
            return 0.0


_default_storage_manager: StorageManager | None = None


def get_storage_manager() -> StorageManager:
    """获取全局存储管理器实例。"""
    global _default_storage_manager
    if _default_storage_manager is None:
        _default_storage_manager = StorageManager()
    return _default_storage_manager