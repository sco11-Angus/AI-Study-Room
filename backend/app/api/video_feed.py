"""WebSocket 视频流推送 — 从 StreamScheduler 复用已解码帧推送到前端。

不再独立拉 RTMP 流，改为从 StreamScheduler 的 ring_buffer 读取最新 JPEG 帧，
通过事件通知（非轮询）推送到前端 canvas 渲染。
"""
import json
import logging
import time

from flask import Blueprint
from flask_sock import Sock
from simple_websocket import ConnectionClosed

from ..stream.scheduler import get_scheduler

bp = Blueprint("video_feed", __name__)
logger = logging.getLogger(__name__)

# 无新帧时的轮询间隔（秒）
_IDLE_INTERVAL = 0.05
# 等待新帧的超时（秒）
_FRAME_TIMEOUT = 1.0
# 超时后最多重试次数（避免短暂卡顿触发"缓冲中"）
_MAX_RETRIES = 3


def register_ws_routes(sock: Sock) -> None:
    """注册 WebSocket 路由（由 create_app 调用）。"""

    @sock.route("/ws/video_feed/<int:camera_id>")
    def ws_video_feed(ws, camera_id: int):
        """WebSocket 端点：事件驱动推送最新 JPEG 帧。"""
        logger.info(f"[video_feed_ws] 客户端已连接 camera_id={camera_id}")

        try:
            while True:
                scheduler = get_scheduler()
                if scheduler is None:
                    _safe_send(ws, json.dumps({"status": "no_scheduler"}))
                    time.sleep(2)
                    continue

                cs = scheduler.get_camera(camera_id)
                if cs is None:
                    _safe_send(ws, json.dumps({"status": "no_camera", "camera_id": camera_id}))
                    time.sleep(2)
                    continue

                if not cs.online:
                    _safe_send(ws, json.dumps({"status": "offline", "camera_id": camera_id}))
                    time.sleep(1)
                    continue

                # 等待新帧（事件驱动，帧到了立即推送，不丢帧）
                # 超时后重试，避免短暂解码卡顿触发前端"缓冲中"
                got_frame = False
                for _ in range(_MAX_RETRIES):
                    if cs.wait_frame(timeout=_FRAME_TIMEOUT):
                        got_frame = True
                        break

                if got_frame:
                    jpg = cs.latest_frame()
                    if jpg is not None:
                        _safe_send(ws, jpg)
                else:
                    _safe_send(ws, json.dumps({"status": "waiting"}))
                    time.sleep(_IDLE_INTERVAL)

        except ConnectionClosed:
            pass
        except Exception:
            logger.exception("[video_feed_ws] WebSocket 异常")
        finally:
            logger.info(f"[video_feed_ws] 客户端断开 camera_id={camera_id}")


def _safe_send(ws, data):
    """安全发送，忽略连接已断开的错误。"""
    try:
        ws.send(data)
    except ConnectionClosed:
        raise
    except Exception:
        pass
