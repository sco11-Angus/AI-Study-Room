"""入侵检测时空防抖单元测试 (对应 §5.4)。"""
from app.detectors.intrusion import IntrusionDetector

SQUARE = [[0, 0], [100, 0], [100, 100], [0, 100]]


def test_base_point_is_box_bottom_center():
    assert IntrusionDetector(SQUARE, 10, 5).base_point((10, 10, 30, 50)) == (20, 50)


def test_alarm_after_stay_time():
    det = IntrusionDetector(SQUARE, x_distance=10, y_stay_time=5)
    box = (40, 40, 60, 60)  # 基准点 (50,60) 在区域内
    assert det.judge(box, ts=0) is False
    assert det.judge(box, ts=5) is True  # 无间断累计达阈值


def test_timer_resets_when_leaving():
    det = IntrusionDetector(SQUARE, x_distance=10, y_stay_time=5)
    inside = (40, 40, 60, 60)
    outside = (400, 400, 420, 420)  # 远离区域
    det.judge(inside, ts=0)
    det.judge(outside, ts=2)        # 离开 -> 清零
    assert det.judge(inside, ts=4) is False  # 重新计时，未达阈值
