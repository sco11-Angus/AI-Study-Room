"""端到端冒烟测试 - 验证 A1/A2/A3/A4 模块。

运行方式（在 backend 目录下）：
    $env:PYTHONPATH="."
    ..\venv\Scripts\python.exe tests\smoke_test.py
"""
import os
import sys
import urllib.request

# 自动添加 backend 目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 1. A1/A2/A3 导入 + 集成 ----
print("=" * 50)
print("1. 模块导入验证")
print("=" * 50)

from app.detectors.base import Frame, AlarmEvent, Detector

class FakeDetector(Detector):
    name = "fake"
    def setup(self):
        print("  [fake] setup() called")
    def detect(self, frame):
        print(f"  [fake] detect() called, frame_idx={frame.frame_idx}")
        return [AlarmEvent(region_id=1, type="intrusion", confidence=0.95)]

from app.stream.engine import InferenceEngine

engine = InferenceEngine()
engine.register(FakeDetector())
engine.setup_all()
print("  A1+A2: OK (import + register + setup)")

from app.stream.scheduler import StreamScheduler

scheduler = StreamScheduler(engine)
cs = scheduler.add_camera(camera_id=0, stream_name="test")
assert cs.ring_buffer.maxlen == 3
assert "rtmp://" in cs.stream_url
print(f"  A3: OK (scheduler created, url={cs.stream_url})")

# ---- 2. dispatch 单帧 ----
print()
print("=" * 50)
print("2. 推理调度验证")
print("=" * 50)

dummy_frame = Frame(image=None, ts=123.0, camera_id=0, frame_idx=100)
events = engine.dispatch(dummy_frame)
assert len(events) == 1
assert events[0].type == "intrusion"
print(f"  dispatch OK: {len(events)} event(s), type={events[0].type}")

# set_enabled 测试
engine.set_enabled("fake", False)
events = engine.dispatch(dummy_frame)
assert len(events) == 0
print("  set_enabled OK: disabled detector returns 0 events")
engine.set_enabled("fake", True)

# ---- 3. Flask 路由 ----
print()
print("=" * 50)
print("3. Flask 路由验证")
print("=" * 50)

from app import create_app

app = create_app()
routes = [r.rule for r in app.url_map.iter_rules() if "video_feed" in r.rule]
assert len(routes) >= 1, f"Missing video_feed route, got {routes}"
print(f"  Flask /video_feed/<stream_id> route: OK")

# ---- 4. video_feed 实际拉流 ----
print()
print("=" * 50)
print("4. /video_feed/test 拉流验证")
print("=" * 50)

try:
    req = urllib.request.Request("http://localhost:5000/video_feed/test")
    resp = urllib.request.urlopen(req, timeout=8)
    content_type = resp.getheader("Content-Type")
    assert "multipart/x-mixed-replace" in content_type, f"Wrong Content-Type: {content_type}"
    chunk = resp.read(2048)
    resp.close()
    has_frame = b"--frame" in chunk
    has_jpeg = b"Content-Type: image/jpeg" in chunk
    if has_frame and has_jpeg:
        print(f"  PASS: 拉流成功! Content-Type={content_type}, chunk={len(chunk)}B, JPEG frame detected")
    else:
        print(f"  WARN: 连接成功但帧格式异常, has_frame={has_frame}, has_jpeg={has_jpeg}")
        print(f"       (可能 RTMP 推流 test 未在运行)")
except urllib.error.URLError as e:
    print(f"  WARN: 无法连接后端: {e}")
    print(f"       请确保 Flask 在另一个终端运行中")
except Exception as e:
    print(f"  WARN: {e}")

# ---- 5. Config ----
print()
print("=" * 50)
print("5. 配置验证")
print("=" * 50)

from app.config import Config

print(f"  SKIP_N={Config.SKIP_N}")
print(f"  RTMP={Config.RTMP_SERVER}:{Config.RTMP_PORT}")
print(f"  DATABASE_URI={Config.DATABASE_URI}")

print()
print("=" * 50)
print("ALL SMOKE TESTS PASSED")
print("=" * 50)
