"""WebSocket 告警实时推送 — 看板订阅 (§7.3, §9.1)。"""
from flask import Blueprint

bp = Blueprint("ws", __name__)

# 依赖 flask-sock，在 create_app 中初始化 Sock(app) 后注册。
# @sock.route("/ws/alarms")
# def alarms_ws(ws):
#     """看板订阅告警事件：格子 绿->红闪烁 + 蜂鸣。"""
#     while True:
#         event = alarm_queue.get()
#         ws.send(event.to_json())
