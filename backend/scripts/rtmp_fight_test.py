"""RTMP 打架检测联调 — 拉真实 RTMP 流跑通 FightPlugin 整链路并导出测试数据。

配合推流使用（另一个终端把 mp4 推到同一流名）：
    ffmpeg -re -stream_loop -1 -i "打架测试2.mp4" -c:v libx264 -preset ultrafast \
           -c:a aac -f flv rtmp://49.233.71.82:9090/live/fighttest2

本脚本做的事（等价于生产 run.py 的 RTMP 链路，只裁掉无关检测器与 DB 落库）：
    - 用真实 StreamScheduler + InferenceEngine 拉这一路 RTMP 流；
    - 视频侧：解码 -> SKIP_N 抽帧 -> FightPlugin.detect()（dlib 人脸框近距离/高速运动）；
    - 音频侧：scheduler._audio_loop 用 FfmpegAudioSource 从同一路 RTMP 抽音轨 ->
      1s 窗口 -> FightPlugin.feed_audio()（YAMNet 语义 + DSP 兜底）；
    - 探针①：拦截 FusionDebouncer.update 记录每窗 vis/aud/emo/fuse 时间序列；
    - 探针②：假 AlarmService 捕获真实产出的 fight 告警（含 extra 全部分值），不落库。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import Config
from app.detectors.fight import FightPlugin, FusionDebouncer
from app.detectors.person_source import FaceBoxProvider, YoloPersonProvider
from app.stream.engine import InferenceEngine
from app.stream.scheduler import StreamScheduler, set_scheduler
import app.services.alarm as alarm_mod

SAMPLES = []   # 每次融合判断的输入快照
ALARMS = []    # 真实产出的 fight 告警事件


def _install_probes():
    """挂探针：记录融合时间序列 + 捕获告警（不落库）。"""
    orig_update = FusionDebouncer.update

    def traced_update(self, vis_score, aud_score, emo_risk=0.0, ts=0, emo_gate=1.0):
        res = orig_update(self, vis_score, aud_score, emo_risk, ts, emo_gate)
        SAMPLES.append({
            "ts": round(ts, 2),
            "vis": round(float(vis_score), 3),
            "aud": round(float(aud_score), 3),
            "emo_risk": round(float(emo_risk), 3),
            "emo_gate": round(float(emo_gate), 3),
            "fired": res is not None,
            "fuse": res["fuse"] if res else None,
        })
        return res

    FusionDebouncer.update = traced_update

    class _FakeAlarmService:
        def raise_alarm(self, evt, frame=None):
            ALARMS.append(evt)

    alarm_mod.get_alarm_service = lambda: _FakeAlarmService()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="rtmp://49.233.71.82:9090/live/fighttest2")
    ap.add_argument("--camera-id", type=int, default=1)
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--person-source", default="yolo", choices=["yolo", "face"])
    args = ap.parse_args()

    _install_probes()

    provider = YoloPersonProvider() if args.person_source == "yolo" else FaceBoxProvider()
    engine = InferenceEngine(max_workers=2)
    engine.register(FightPlugin(region_id=args.camera_id, person_provider=provider))
    engine.setup_all()
    print(f"[test] 人员框来源: {type(provider).__name__}", flush=True)

    scheduler = StreamScheduler(engine)
    set_scheduler(scheduler)
    scheduler.add_camera(camera_id=args.camera_id, stream_url=args.url)

    print(f"[test] 开始拉流 {args.url}，运行 {args.seconds}s ...", flush=True)
    scheduler.start_all()

    t0 = time.time()
    try:
        while time.time() - t0 < args.seconds:
            time.sleep(1.0)
    finally:
        scheduler.stop_all()
        engine.shutdown()

    _report()


def _report():
    print("\n" + "=" * 68, flush=True)
    print("打架检测测试结果", flush=True)
    print("=" * 68, flush=True)
    print(f"融合判断样本数（视频抽帧数）: {len(SAMPLES)}", flush=True)

    vis_hits = [s for s in SAMPLES if s["vis"] > 0]
    aud_hits = [s for s in SAMPLES if s["aud"] > 0]
    both = [s for s in SAMPLES if s["vis"] > 0 and s["aud"] > 0]
    print(f"  视觉有信号帧 (vis>0): {len(vis_hits)}", flush=True)
    print(f"  音频有信号帧 (aud>0): {len(aud_hits)}", flush=True)
    print(f"  双模同时有信号帧    : {len(both)}", flush=True)

    def _stat(key):
        vals = [s[key] for s in SAMPLES if s[key] is not None]
        if not vals:
            return "无数据"
        return f"max={max(vals):.3f} mean={sum(vals)/len(vals):.3f}"

    print(f"  vis 分布: {_stat('vis')}", flush=True)
    print(f"  aud 分布: {_stat('aud')}", flush=True)
    print(f"  emo_gate 分布: {_stat('emo_gate')}", flush=True)

    print(f"\n阈值配置: FUSE_THRESH={Config.FIGHT_FUSE_THRESH} "
          f"DURATION={Config.FIGHT_DURATION}s "
          f"W(vis/aud/emo)={Config.FIGHT_W_VIS}/{Config.FIGHT_W_AUD}/{Config.FIGHT_W_EMO} "
          f"ALIGN_TOL={Config.FIGHT_ALIGN_TOL}s", flush=True)

    # 打印双模都有信号的关键窗口（最能说明问题的样本）
    key_rows = both[:40] if both else [s for s in SAMPLES if s["vis"] > 0][:40]
    if key_rows:
        print("\n关键窗口明细 (vis>0 的帧):", flush=True)
        print(f"{'ts':>8} {'vis':>7} {'aud':>7} {'emo_g':>7} {'fired':>6} {'fuse':>7}", flush=True)
        for s in key_rows:
            fuse = f"{s['fuse']:.3f}" if s["fuse"] is not None else "-"
            print(f"{s['ts']:>8.2f} {s['vis']:>7.3f} {s['aud']:>7.3f} "
                  f"{s['emo_gate']:>7.3f} {str(s['fired']):>6} {fuse:>7}", flush=True)

    print(f"\n===> 打架告警触发次数: {len(ALARMS)}", flush=True)
    for i, evt in enumerate(ALARMS, 1):
        ex = evt.extra
        print(f"  [告警{i}] type={evt.type} level={ex.get('level')} "
              f"confidence(fuse)={evt.confidence} "
              f"vis={ex.get('vis_score')} aud={ex.get('aud_score')} "
              f"emo_gate={ex.get('emo_gate')} duration={ex.get('duration')}s "
              f"人员框数={len(ex.get('person_boxes', []))}", flush=True)
    if not ALARMS:
        print("  （未触发打架告警 —— 见上方分值判断原因）", flush=True)


if __name__ == "__main__":
    main()
