"""延迟测试：经 FFmpeg 管道测量 RTMP 拉流延迟和帧率。"""
import subprocess
import time

import numpy as np

TARGET_W, TARGET_H = 640, 360
FRAME_SIZE = TARGET_W * TARGET_H * 3  # BGR24

URL = "rtmp://49.233.71.82:9090/live/test"
CMD = (
    "ffmpeg "
    "-fflags nobuffer+genpts "
    "-flags low_delay "
    "-flags2 showall+ignorecrop "
    "-err_detect ignore_err "
    "-strict unofficial "
    "-rtmp_live live "
    "-analyzeduration 100000 "
    "-probesize 50000 "
    "-threads 1 "
    "-ec favor_inter+deblock "
    "-skip_loop_filter all "
    f'-i "{URL}" '
    "-map 0:v "
    "-an "
    f"-vf scale={TARGET_W}:{TARGET_H} "
    "-f rawvideo "
    "-pix_fmt bgr24 "
    "pipe:1"
)

print(f"Connecting to RTMP...")
t0 = time.time()

try:
    proc = subprocess.Popen(
        CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
    )
except FileNotFoundError:
    print("ERROR: ffmpeg not found in PATH")
    exit(1)

t1 = time.time()
print(f"FFmpeg spawned: {round((t1 - t0) * 1000, 1)} ms")

raw = proc.stdout.read(FRAME_SIZE)
t2 = time.time()
if len(raw) == FRAME_SIZE:
    print(f"first frame: {round((t2 - t1) * 1000, 1)} ms")
    print(f"shape: {TARGET_H}x{TARGET_W}x3 OK")
else:
    print(f"first frame FAILED: got {len(raw)} bytes, expected {FRAME_SIZE}")
    stderr_data = proc.stderr.read()
    with open("ffmpeg_error.log", "wb") as f:
        f.write(stderr_data)
    print("FFmpeg stderr -> ffmpeg_error.log")
    proc.terminate()
    exit(1)

# 测 60 帧
intervals = []
prev = t2
for i in range(60):
    raw = proc.stdout.read(FRAME_SIZE)
    now = time.time()
    if len(raw) != FRAME_SIZE:
        print(f"\nFrame {i}: incomplete ({len(raw)}/{FRAME_SIZE})")
        break
    intervals.append(round((now - prev) * 1000, 1))
    prev = now

proc.terminate()
proc.wait(timeout=3)

if intervals:
    avg_ms = sum(intervals) / len(intervals)
    print(f"\n--- Summary ({len(intervals)} frames) ---")
    print(f"avg frame interval: {round(avg_ms, 1)} ms ({round(1000 / avg_ms, 1)} FPS)")
    print(f"min/max interval: {min(intervals)} / {max(intervals)} ms")
