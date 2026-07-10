import requests

BASE = 'http://localhost:5000'

types = [
    ('fight', 2, '学生A', '与学生B发生肢体冲突'),
    ('intrusion', 1, '陌生人', '非法进入防区'),
    ('fire_smoke', 2, '系统', '检测到烟雾'),
    ('face_recognition', 1, '陌生人', '未注册人脸'),
    ('fatigue', 0, '学生C', '闭眼超过2秒'),
    ('occupy', 1, '学生D', '占用自习座位'),
]

for alarm_type, level, actor, behavior in types:
    print('\n测试:', alarm_type)
    r = requests.post(BASE + '/api/alarms/test-capture', json={
        'camera_id': 5, 'region_id': 5, 'type': alarm_type,
        'level': level, 'actor': actor, 'behavior': behavior
    })
    print('  状态:', r.status_code)
    if r.status_code == 200:
        data = r.json()
        print('  告警ID:', data['data']['id'], '状态:', data['data']['status'])

r = requests.get(BASE + '/api/alarms')
data = r.json()
print('\n\n总告警数:', len(data['data']))
pending = [a for a in data['data'] if a['status'] == 'pending']
print('待处理:', len(pending))
