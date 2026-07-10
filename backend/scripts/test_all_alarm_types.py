"""测试所有告警类型的综合脚本。"""
import requests

BASE_URL = "http://localhost:5000"


def test_alarm_type(alarm_type, level=2, actor="测试用户", behavior="测试行为"):
    """测试指定类型的告警。"""
    print(f"\n{'='*60}")
    print(f"测试告警类型: {alarm_type}")
    print(f"级别: {level}, 行为: {behavior}")
    print(f"{'='*60}")
    
    payload = {
        "camera_id": 5,
        "region_id": 5,
        "type": alarm_type,
        "level": level,
        "actor": actor,
        "behavior": behavior,
        "extra": {
            "source": "manual_test",
            "test_type": alarm_type,
        },
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/alarms/test-capture", json=payload)
        print(f"HTTP状态: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"告警ID: {data['data']['id']}")
            print(f"状态: {data['data']['status']}")
            print(f"抓拍URL: {data['data']['snapshot_url']}")
            
            snapshot_response = requests.get(f"{BASE_URL}{data['data']['snapshot_url']}")
            print(f"抓拍图片大小: {len(snapshot_response.content)} bytes")
            return True
        else:
            print(f"失败: {response.text}")
            return False
    except Exception as e:
        print(f"请求异常: {e}")
        return False


def test_fight_detection():
    """测试打架检测 - 需要在摄像头前模拟打架行为。"""
    print("\n\n📢 请在摄像头前模拟打架行为（两个人靠近并做出推搡动作）")
    print("持续 5-10 秒...")
    input("按 Enter 开始监控...")
    
    import time
    start_time = time.time()
    alarm_count_before = get_alarm_count("pending")
    
    print(f"监控开始，等待 15 秒...")
    time.sleep(15)
    
    alarm_count_after = get_alarm_count("pending")
    new_alarms = alarm_count_after - alarm_count_before
    
    print(f"\n监控结束")
    print(f"新增告警数: {new_alarms}")
    
    if new_alarms > 0:
        print("✅ 打架检测成功！")
    else:
        print("⚠️ 未检测到打架行为，请尝试更明显的动作")


def get_alarm_count(status=None):
    """获取告警数量。"""
    url = f"{BASE_URL}/api/alarms"
    if status:
        url += f"?status={status}"
    try:
        response = requests.get(url)
        data = response.json()
        return len(data.get("data", []))
    except:
        return 0


def main():
    print("🚀 告警类型综合测试")
    print(f"当前待处理告警: {get_alarm_count('pending')}")
    
    tests = [
        ("fight", 2, "学生A", "与学生B发生肢体冲突，互相推搡"),
        ("intrusion", 1, "陌生人", "非法进入自习室防区"),
        ("fire_smoke", 2, "系统", "检测到烟雾，疑似火灾"),
        ("face_recognition", 1, "陌生人", "检测到未注册人脸"),
        ("fatigue", 0, "学生C", "闭眼超过2秒，疑似疲劳"),
    ]
    
    for alarm_type, level, actor, behavior in tests:
        test_alarm_type(alarm_type, level, actor, behavior)
    
    print("\n\n" + "="*60)
    print("📊 测试结果统计")
    print("="*60)
    print(f"待处理告警: {get_alarm_count('pending')}")
    print(f"已通知告警: {get_alarm_count('notified')}")
    print(f"已确认告警: {get_alarm_count('confirmed')}")
    
    print("\n\n🎯 真实行为测试 - 打架检测")
    print("-"*60)
    test_fight_detection()


if __name__ == "__main__":
    main()