"""视频拉流 API — 从 RTMP 服务器拉流，以 MJPEG 格式提供给前端。

后端从 rtmp://49.233.71.82:9090/live/<stream_id> 拉取 RTMP 流，
编码为 JPEG 后以 multipart/x-mixed-replace 格式推送给前端 <img> 标签。
"""
import logging
import time

import cv2
from flask import Blueprint, Response, jsonify

from ..config import Config

bp = Blueprint("video_feed", __name__)
logger = logging.getLogger(__name__)


def generate_frames(stream_id: str):
    """生成器：从 RTMP 拉流，跳帧编码后 yield MJPEG 帧，断流自动重连。"""
    stream_url = f"rtmp://{Config.RTMP_SERVER}:{Config.RTMP_PORT}/live/{stream_id} live=1"
    logger.info(f"[video_feed] 开始拉流: {stream_url}")

    cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        logger.error(f"[video_feed] 无法打开流: {stream_url}，请检查推流是否在运行")
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + b"\r\n"
        )
        return

    # 降低分辨率减少延迟
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 480)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    frame_skip = 5   # 跳帧数
    frame_count = 0
    logger.info(f"[video_feed] 拉流成功，开始输出帧 stream_id={stream_id}")

    while True:
        success, frame = cap.read()
        if not success:
            logger.warning(f"[video_feed] 读取帧失败，尝试重连... stream_id={stream_id}")
            cap.release()
            time.sleep(2)
            cap = cv2.VideoCapture(stream_url)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 480)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            frame_count = 0
            continue

        if frame_count % frame_skip == 0:
            ret, buffer = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70]
            )
            if not ret:
                frame_count += 1
                continue
            frame_bytes = buffer.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
        frame_count += 1

    cap.release()


@bp.route("/video_feed/<stream_id>")
def video_feed(stream_id: str):
    """MJPEG 视频流接口。
    
    前端用法：<img src="http://localhost:5000/video_feed/1" />
    ---
    tags:
      - 视频流
    parameters:
      - name: stream_id
        in: path
        type: string
        required: true
        description: 推流 ID，如 1, 2, 3
    responses:
      200:
        description: MJPEG 视频流
    """
    try:
        return Response(
            generate_frames(stream_id),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )
    except Exception as e:
        return jsonify({"error": f"推流 {stream_id} 不存在或已断开: {str(e)}"}), 500
