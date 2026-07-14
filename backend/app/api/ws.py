"""WebSocket 告警实时推送 — 看板订阅 (§7.3, §9.1)。"""
import json
import logging
import json
import os

from flask import Blueprint, jsonify, request, send_from_directory

from ..config import Config

bp = Blueprint("ws", __name__)
logger = logging.getLogger(__name__)

"""WebSocket 实时推送接口。"""
import json
import logging
import queue
import threading

from flask import Blueprint, jsonify
from flask_sock import Sock
from simple_websocket import ConnectionClosed

bp = Blueprint("ws", __name__)
logger = logging.getLogger(__name__)

# ---- 任务 E：告警 WebSocket ----

_alarm_subscribers: set = set()
_alarm_lock = threading.Lock()
_companion_subscribers: dict[tuple[int, int], set] = {}


def broadcast_alarm(payload: dict) -> int:
    """向所有告警看板连接推送 JSON，返回成功发送数。"""
    data = json.dumps(payload, ensure_ascii=False)
    with _alarm_lock:
        subscribers = list(_alarm_subscribers)

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
        with _alarm_lock:
            for ws in dead:
                _alarm_subscribers.discard(ws)
    return sent


def broadcast_companion_alarm(payload: dict) -> int:
    """Deliver a fatigue reminder only to the matching companion session."""
    if payload.get("type") != "fatigue":
        return 0
    extra = payload.get("extra") or {}
    user_id = extra.get("user_id")
    region_id = payload.get("region_id")
    if user_id is None or region_id is None:
        return 0
    key = (int(user_id), int(region_id))
    with _alarm_lock:
        subscribers = list(_companion_subscribers.get(key, set()))
    data = json.dumps(payload, ensure_ascii=False)
    sent = 0
    dead = []
    for ws in subscribers:
        try:
            ws.send(data)
            sent += 1
        except ConnectionClosed:
            dead.append(ws)
        except Exception:
            logger.exception("[companion_ws] reminder delivery failed")
            dead.append(ws)
    if dead:
        with _alarm_lock:
            for ws in dead:
                _companion_subscribers.get(key, set()).discard(ws)
    return sent


def broadcast_alarm_update(alarm_id: int, updates: dict) -> int:
    """推送告警状态更新（确认、升级、片段就绪等）。"""
    payload = {
        "type": "update",
        "id": alarm_id,
        **updates,
    }
    return broadcast_alarm(payload)


# ---- 人脸识别结果 ----

face_result_queue = queue.Queue()
latest_face_result = None
_face_lock = threading.Lock()


def set_face_result(result: dict) -> None:
    """线程安全地更新最新人脸识别结果。"""
    global latest_face_result
    with _face_lock:
        latest_face_result = result


def broadcast_face_result(result: dict) -> None:
    """推送人脸识别结果到 WebSocket 广播队列（供前端实时订阅）。"""
    set_face_result(result)
    try:
        face_result_queue.put_nowait(result)
    except Exception:
        pass


# ---- 人脸框列表（供前端画框 + 平滑跟随）----

# maxsize=2：只保留最新框，满了丢旧，避免慢客户端积压延迟
face_boxes_queue = queue.Queue(maxsize=2)


def broadcast_face_boxes(faces: list) -> None:
    """推送本帧所有人脸框（归一化坐标 + 身份）到广播队列。"""
    try:
        if face_boxes_queue.full():
            face_boxes_queue.get_nowait()   # 丢最旧，只推最新
        face_boxes_queue.put_nowait({"type": "faces", "faces": faces})
    except Exception:
        pass


# ---- 街道监控：当前画面计数 + 检测框（旁路通道，不进告警中心）----

# maxsize=8：4 路识别流并发推送，避免互相挤掉；满则丢最旧只保留最新
street_stats_queue = queue.Queue(maxsize=8)


def broadcast_street_stats(payload: dict) -> None:
    """推送某识别路的当前画面计数与检测框到广播队列（供前端街道大屏订阅）。

    payload 形如 {"type":"street","camera_id":3,"ts":..,"counts":{..},"boxes":[..]}。
    """
    try:
        if street_stats_queue.full():
            street_stats_queue.get_nowait()   # 丢最旧，只推最新
        street_stats_queue.put_nowait(payload)
    except Exception:
        pass


# ---- REST API（直接写在 ws 模块里，零跨文件导入） ----

@bp.get("/api/face_result")
def get_face_result():
    """获取最新人脸识别结果
    ---
    tags:
      - Face
    summary: 查询最新人脸识别/活体检测结果（前端每 500ms 轮询）
    responses:
      200:
        description: 人脸识别结果
        schema:
          properties:
            code: {type: integer, example: 0}
            message: {type: string, example: "ok"}
            data:
              type: object
              properties:
                type: {type: string, enum: [member, stranger, face_spoof], description: "结果类型"}
                member_id: {type: integer, description: "会员 ID（仅 member 类型）"}
                name: {type: string, description: "会员姓名（仅 member 类型）"}
                confidence: {type: number, description: "置信度（仅 face_spoof 类型）"}
                reasons: {type: array, items: {type: string}, description: "失败原因（仅 face_spoof 类型）"}
    """
    with _face_lock:
        data = latest_face_result
    return jsonify(code=0, message="ok", data=data)


# ---- WebSocket 路由 ----

def register_ws_routes(sock: Sock) -> None:
    """注册 WebSocket 路由（由 create_app 调用）。"""

    @sock.route("/ws/alarms")
    def alarms_ws(ws):
        """看板订阅告警事件：格子 绿->红闪烁 + 蜂鸣。"""
        with _alarm_lock:
            _alarm_subscribers.add(ws)

        # Historical alarms are not equivalent to somebody currently in a
        # zone. Send a live track snapshot whenever a dashboard reconnects.
        try:
            from ..stream.scheduler import get_scheduler

            scheduler = get_scheduler()
            engine = getattr(scheduler, "_engine", None) if scheduler else None
            detector = getattr(engine, "_detectors", {}).get("intrusion") if engine else None
            states = detector.get_active_alarm_states() if detector else []
            ws.send(json.dumps({"event": "region_state_snapshot", "states": states}, ensure_ascii=False))
        except Exception:
            logger.exception("[alarm_ws] failed to send live region-state snapshot")
        logger.info("[alarm_ws] 客户端已连接")

        try:
            while True:
                ws.receive()
        except ConnectionClosed:
            pass
        except Exception:
            logger.exception("[alarm_ws] WebSocket 异常")
        finally:
            with _alarm_lock:
                _alarm_subscribers.discard(ws)
            logger.info("[alarm_ws] 客户端断开")

    @sock.route("/ws/companion")
    def companion_ws(ws):
        """Subscribe to fatigue reminders for one selected demo companion."""
        try:
            user_id = int(request.args.get("user_id", ""))
            region_id = int(request.args.get("region_id", ""))
        except (TypeError, ValueError):
            ws.close()
            return
        key = (user_id, region_id)
        with _alarm_lock:
            _companion_subscribers.setdefault(key, set()).add(ws)
        try:
            while True:
                ws.receive()
        except ConnectionClosed:
            pass
        except Exception:
            logger.exception("[companion_ws] WebSocket error")
        finally:
            with _alarm_lock:
                subscribers = _companion_subscribers.get(key)
                if subscribers is not None:
                    subscribers.discard(ws)
                    if not subscribers:
                        _companion_subscribers.pop(key, None)

    @sock.route("/ws/face_recognition")
    def ws_face_recognition(ws):
        logger.info("[face_ws] 客户端已连接 face_recognition")
        try:
            while True:
                try:
                    msg = face_result_queue.get(timeout=0.5)
                    _safe_send(ws, json.dumps(msg, ensure_ascii=False))
                except queue.Empty:
                    continue
        except ConnectionClosed:
            pass
        except Exception:
            logger.exception("[face_ws] WebSocket 异常")
        finally:
            logger.info("[face_ws] 客户端断开 face_recognition")

    @sock.route("/ws/face_boxes")
    def ws_face_boxes(ws):
        """看板订阅人脸框列表：每帧所有脸的归一化坐标 + 身份。"""
        logger.info("[face_boxes_ws] 客户端已连接 face_boxes")
        try:
            while True:
                try:
                    msg = face_boxes_queue.get(timeout=0.5)
                    _safe_send(ws, json.dumps(msg, ensure_ascii=False))
                except queue.Empty:
                    continue
        except ConnectionClosed:
            pass
        except Exception:
            logger.exception("[face_boxes_ws] WebSocket 异常")
        finally:
            logger.info("[face_boxes_ws] 客户端断开 face_boxes")

    @sock.route("/ws/street")
    def ws_street(ws):
        """街道大屏订阅：各识别路的当前画面计数 + 检测框（按 camera_id 分发）。"""
        logger.info("[street_ws] 客户端已连接 street")
        try:
            while True:
                try:
                    msg = street_stats_queue.get(timeout=0.5)
                    _safe_send(ws, json.dumps(msg, ensure_ascii=False))
                except queue.Empty:
                    continue
        except ConnectionClosed:
            pass
        except Exception:
            logger.exception("[street_ws] WebSocket 异常")
        finally:
            logger.info("[street_ws] 客户端断开 street")


def _safe_send(ws, data):
    try:
        ws.send(data)
    except ConnectionClosed:
        raise
    except Exception:
        pass
