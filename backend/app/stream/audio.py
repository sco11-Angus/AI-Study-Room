"""音轨抽取管线 — 从 RTMP/FLV 解出音频，分帧聚合成分析窗口 (任务书 D1)。

与 A 的边界（协作红线③"音轨只解一次"）：
    A 给音轨字节流/解码句柄，或 D 直读同一路 RTMP 音轨；二选一，当面定死。
    本模块把"音轨来源"抽象为 AudioSource，默认 FfmpegAudioSource（D 直读），
    A 若改为给字节流，换个 AudioSource 实现即可，下游不动。

处理链：AAC 音轨 -> ffmpeg 解码重采样 16kHz 单声道 PCM(s16le)
        -> 25ms 帧长 / 10ms 帧移分帧 -> 聚合成 AUDIO_WINDOW(1s) 分析窗口
        -> 产出 AudioChunk 投递给打架检测器。

注意：本机需安装 ffmpeg（`ffmpeg -version` 可用）。缺失时优雅降级、不崩。
"""
import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from ..config import Config

logger = logging.getLogger(__name__)

# 25ms 帧长 / 10ms 帧移（语音分析常用），采样点数按 AUDIO_SR 换算
_FRAME_MS = 25
_HOP_MS = 10


@dataclass
class AudioChunk:
    """1s 分析窗口 — 音轨管线产出，投递给打架检测器音频侧 (D3)。"""

    camera_id: int
    ts: float                 # 窗口起始时间戳（秒）
    pcm: np.ndarray           # 单声道 float32 PCM，[-1, 1]，长度 = AUDIO_SR * AUDIO_WINDOW
    sample_rate: int          # 采样率（= Config.AUDIO_SR）
    frames: np.ndarray = field(default=None)  # 可选：分帧后 (n_frames, frame_len)


def ffmpeg_available() -> bool:
    """本机是否可用 ffmpeg。"""
    return shutil.which("ffmpeg") is not None


def frame_signal(pcm: np.ndarray, sample_rate: int) -> np.ndarray:
    """按 25ms 帧长 / 10ms 帧移分帧。

    返回 (n_frames, frame_len)；不足一帧返回 (0, frame_len)。
    """
    frame_len = int(sample_rate * _FRAME_MS / 1000)
    hop_len = int(sample_rate * _HOP_MS / 1000)
    if len(pcm) < frame_len:
        return np.empty((0, frame_len), dtype=np.float32)
    n_frames = 1 + (len(pcm) - frame_len) // hop_len
    # 用 stride 视图避免拷贝
    idx = np.arange(frame_len)[None, :] + hop_len * np.arange(n_frames)[:, None]
    return pcm[idx]


class AudioSource(ABC):
    """音轨来源抽象 — 屏蔽"音频从哪来"（D 直读 or A 给字节流）。

    产出连续的 float32 单声道 PCM 块（原始时序，未分窗）。
    """

    @abstractmethod
    def read(self) -> Iterator[np.ndarray]:
        """持续产出 PCM 片段（float32, [-1,1], 单声道, Config.AUDIO_SR）。"""
        ...

    def close(self) -> None:
        """释放底层资源（子进程/句柄）。"""
        pass


class FfmpegAudioSource(AudioSource):
    """D 直读同一路 RTMP/FLV，用 ffmpeg 子进程解码重采样为 16k 单声道 PCM。

    ffmpeg 缺失时 read() 直接返回空迭代并告警，不抛异常拖垮引擎。
    """

    def __init__(self, url: str, sample_rate: int = None, chunk_ms: int = 100):
        self.url = url
        self.sample_rate = sample_rate or Config.AUDIO_SR
        self._chunk_bytes = int(self.sample_rate * chunk_ms / 1000) * 2  # s16le=2B
        self._proc: subprocess.Popen | None = None

    def read(self) -> Iterator[np.ndarray]:
        if not ffmpeg_available():
            logger.warning("[audio] 未检测到 ffmpeg，音轨管线降级为空（联调阶段需安装）")
            return
        cmd = [
            "ffmpeg", "-nostdin", "-loglevel", "error",
            "-i", self.url,
            "-vn",                      # 丢弃视频
            "-ac", "1",                 # 单声道
            "-ar", str(self.sample_rate),
            "-f", "s16le", "-",         # 裸 PCM 到 stdout
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                raw = self._proc.stdout.read(self._chunk_bytes)
                if not raw:
                    break
                pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                yield pcm
        finally:
            self.close()

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None


class AudioWindower:
    """把连续 PCM 累积成固定长度分析窗口（与视频跳帧解耦，音频独立累积）。

    feed() 送入任意长度 PCM，满 AUDIO_WINDOW 秒即吐一个 AudioChunk。
    """

    def __init__(self, camera_id: int, sample_rate: int = None, window_s: float = None):
        self.camera_id = camera_id
        self.sample_rate = sample_rate or Config.AUDIO_SR
        self.window_len = int(self.sample_rate * (window_s or Config.AUDIO_WINDOW))
        self._buf = np.empty(0, dtype=np.float32)
        self._elapsed = 0.0  # 已消费样本对应的累计秒数

    def feed(self, pcm: np.ndarray, ts: float = None) -> list[AudioChunk]:
        """送入 PCM，返回本次凑满的 0 或多个 AudioChunk。

        ts 为该 PCM 片段起始时间戳；缺省用内部累计时长。
        """
        self._buf = np.concatenate([self._buf, pcm.astype(np.float32)])
        chunks: list[AudioChunk] = []
        while len(self._buf) >= self.window_len:
            win = self._buf[: self.window_len]
            self._buf = self._buf[self.window_len :]
            start_ts = ts - (len(self._buf) + self.window_len) / self.sample_rate \
                if ts is not None else self._elapsed
            chunks.append(AudioChunk(
                camera_id=self.camera_id,
                ts=start_ts,
                pcm=win,
                sample_rate=self.sample_rate,
                frames=frame_signal(win, self.sample_rate),
            ))
            self._elapsed += self.window_len / self.sample_rate
        return chunks
