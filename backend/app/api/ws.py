"""WebSocket 告警实时推送 — 看板订阅 (§7.3, §9.1)。"""
import json
import logging
import threading

from flask import Blueprint
from flask_sock import Sock
from simple_websocket import ConnectionClosed

bp = Blueprint("ws", __name__)
logger = logging.getLogger(__name__)

_subscribers: set = set()
_lock = threading.Lock()


def register_ws_routes(sock: Sock) -> None:
    """注册告警 WebSocket 路由（由 create_app 调用）。"""

    @sock.route("/ws/alarms")
    def alarms_ws(ws):
        """看板订阅告警事件：格子 绿->红闪烁 + 蜂鸣。"""
        with _lock:
            _subscribers.add(ws)
        logger.info("[alarm_ws] 客户端已连接")

        try:
            while True:
                # simple-websocket 需要持续接收以感知断开；前端无需发业务消息。
                ws.receive()
        except ConnectionClosed:
            pass
        except Exception:
            logger.exception("[alarm_ws] WebSocket 异常")
        finally:
            with _lock:
                _subscribers.discard(ws)
            logger.info("[alarm_ws] 客户端断开")


def broadcast_alarm(payload: dict) -> int:
    """向所有告警看板连接推送 JSON，返回成功发送数。"""
    data = json.dumps(payload, ensure_ascii=False)
    with _lock:
        subscribers = list(_subscribers)

    sent = 0
    dead = []
    for ws in subscribers:
        try:
            ws.send(data)
            sent += 1
        except ConnectionClosed:
            dead.append(ws)
        except Exception:
            logger.exception("[alarm_ws] 告警推送失败")
            dead.append(ws)

    if dead:
        with _lock:
            for ws in dead:
                _subscribers.discard(ws)
    return sent
