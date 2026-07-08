"""WebSocket 告警实时推送 — 看板订阅 (§7.3, §9.1)。"""
import json
import logging
import queue
import threading

from flask import Blueprint, jsonify

bp = Blueprint("ws", __name__)
logger = logging.getLogger(__name__)

# 人脸识别结果广播队列
face_result_queue = queue.Queue()
# 最新人脸识别结果
latest_face_result = None
_lock = threading.Lock()


def set_face_result(result: dict) -> None:
    """线程安全地更新最新人脸识别结果。"""
    global latest_face_result
    with _lock:
        latest_face_result = result


# ---- REST API（直接写在 ws 模块里，零跨文件导入） ----

@bp.get("/api/face_result")
def get_face_result():
    """获取最新人脸识别结果（前端每 500ms 轮询）。"""
    with _lock:
        data = latest_face_result
    return jsonify(code=0, message="ok", data=data)


# ---- WebSocket 路由 ----

def register_ws_routes(sock):
    @sock.route("/ws/face_recognition")
    def ws_face_recognition(ws):
        logger.info("[ws] 客户端已连接 face_recognition")
        try:
            while True:
                try:
                    msg = face_result_queue.get(timeout=0.5)
                    _safe_send(ws, json.dumps(msg, ensure_ascii=False))
                except queue.Empty:
                    continue
        except Exception:
            pass
        finally:
            logger.info("[ws] 客户端断开 face_recognition")


def _safe_send(ws, data):
    try:
        ws.send(data)
    except Exception:
        pass
