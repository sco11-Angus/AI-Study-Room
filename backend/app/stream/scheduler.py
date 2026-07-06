"""拉流解码 + 跳帧调度器 (§3.1, §3.2)。

- 每路摄像头一个解码线程，写入有界环形帧缓冲（丢旧帧，保证低延迟 §3.3）。
- 显示链路：全帧交由 Nginx-RTMP 转发前端。
- 推理链路：每 SKIP_N 帧取 1 帧送入算法线程池。
"""
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import cv2

from ..config import Config


class StreamScheduler:
    def __init__(self, stream_url: str, buffer_size: int = 3):
        self.stream_url = stream_url
        self.ring_buffer: deque = deque(maxlen=buffer_size)  # 丢旧帧
        self.infer_pool = ThreadPoolExecutor(max_workers=2)
        self.running = False
        self._frame_idx = 0

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        cap = cv2.VideoCapture(self.stream_url)
        while self.running:
            ok, frame = cap.read()
            if not ok:                      # 断流自动重连 (§10.2)
                cap.release()
                cap = cv2.VideoCapture(self.stream_url)
                continue
            self.ring_buffer.append(frame)  # 供显示/推流
            if self._frame_idx % Config.SKIP_N == 0:
                self.infer_pool.submit(self._analyze, frame)
            self._frame_idx += 1
        cap.release()

    def _analyze(self, frame):
        # TODO: 编排 detectors（入侵/烟火/疲劳/人脸），产出告警事件
        ...

    def stop(self):
        self.running = False
