"""本地测试抓拍功能 — 不依赖 OBS 推流，使用电脑摄像头或本地视频文件。

用法：
    python scripts/test_local_capture.py --camera 0          # 使用摄像头
    python scripts/test_local_capture.py --video test.mp4    # 使用本地视频文件
"""
import argparse
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, ".")

from app.detectors.base import AlarmEvent
from app.services.alarm import get_alarm_service


def capture_from_camera(camera_index: int = 0, frame_count: int = 10) -> np.ndarray | None:
    """从摄像头捕获一帧图像。"""
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"[ERROR] 无法打开摄像头 {camera_index}")
        return None
    
    print(f"[INFO] 正在从摄像头 {camera_index} 捕获...")
    for _ in range(frame_count):
        ret, frame = cap.read()
        if not ret:
            print(f"[ERROR] 读取摄像头失败")
            cap.release()
            return None
        # 等待摄像头稳定
        time.sleep(0.1)
    
    cap.release()
    print(f"[INFO] 捕获成功，帧尺寸: {frame.shape}")
    return frame


def capture_from_video(video_path: str) -> np.ndarray | None:
    """从本地视频文件读取一帧图像。"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[ERROR] 无法打开视频文件: {video_path}")
        return None
    
    print(f"[INFO] 正在从视频文件 {video_path} 读取...")
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # 读取中间帧
    cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print(f"[ERROR] 读取视频帧失败")
        return None
    
    print(f"[INFO] 读取成功，帧尺寸: {frame.shape}")
    return frame


def test_alarm_with_frame(frame: np.ndarray):
    """使用捕获的帧测试告警中心。"""
    print(f"\n[INFO] ===== 测试告警中心 =====")
    
    alarm_service = get_alarm_service()
    
    event = AlarmEvent(
        type="fight",
        region_id=5,
        camera_id=5,
        level=2,
        confidence=0.95,
        snapshot=frame,
        face_match="stranger",
        extra={
            "actor": "测试用户",
            "behavior": "推搡同学，疑似发生肢体冲突",
            "source": "local_test_capture",
        },
    )
    
    result = alarm_service.raise_alarm(event, frame=frame)
    
    if result:
        print(f"[SUCCESS] 告警创建成功！")
        print(f"  告警ID: {result.get('id', 'N/A')}")
        print(f"  类型: {result.get('type', 'N/A')}")
        print(f"  级别: {result.get('level', 'N/A')}")
        print(f"  状态: {result.get('status', 'N/A')}")
        print(f"  抓拍URL: {result.get('snapshot_url', 'N/A')}")
    else:
        print(f"[WARNING] 告警被去重（30秒内同类型同防区）")


def main():
    parser = argparse.ArgumentParser(description="本地测试抓拍功能")
    parser.add_argument("--camera", type=int, default=None, help="摄像头索引（默认0）")
    parser.add_argument("--video", type=str, default=None, help="本地视频文件路径")
    args = parser.parse_args()
    
    if args.camera is not None:
        frame = capture_from_camera(args.camera)
    elif args.video is not None:
        frame = capture_from_video(args.video)
    else:
        print("[INFO] 未指定摄像头或视频文件，尝试使用摄像头 0...")
        frame = capture_from_camera(0)
    
    if frame is None:
        print("[ERROR] 无法获取图像帧")
        sys.exit(1)
    
    test_alarm_with_frame(frame)
    print("\n[INFO] 测试完成！")


if __name__ == "__main__":
    main()